"""Tests for the auth dependency and rate limiter."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth
import config
from main import app
from rate_limit import SlidingWindowCounter

# --- SlidingWindowCounter -------------------------------------------------

def test_sliding_window_allows_up_to_limit():
    c = SlidingWindowCounter(limit=3, window_seconds=60)
    assert c.consume("a")
    assert c.consume("a")
    assert c.consume("a")
    assert not c.consume("a")


def test_sliding_window_keys_are_independent():
    c = SlidingWindowCounter(limit=1, window_seconds=60)
    assert c.consume("a")
    assert not c.consume("a")
    # Different key starts fresh
    assert c.consume("b")


def test_sliding_window_window_slides():
    c = SlidingWindowCounter(limit=1, window_seconds=0.1)
    assert c.consume("a")
    assert not c.consume("a")
    time.sleep(0.15)
    assert c.consume("a")


def test_sliding_window_evicts_idle_keys_above_threshold():
    """After the dict grows past the eviction threshold, idle keys are
    dropped on the next consume() so the limiter doesn't leak entries
    for callers that go silent forever.
    """
    c = SlidingWindowCounter(limit=10, window_seconds=0.05)
    c._evict_threshold = 4  # shrink so the test runs fast
    # Five distinct keys, each one and done.
    for i in range(5):
        assert c.consume(f"k{i}")
    assert len(c._buckets) == 5
    # Wait past the window so every stamp is stale.
    time.sleep(0.1)
    # Next consume() sweeps the stale entries.
    c.consume("trigger")
    assert all(not q for q in c._buckets.values()) is False  # trigger is fresh
    assert "k0" not in c._buckets
    assert "k4" not in c._buckets
    assert "trigger" in c._buckets


# --- Auth dependency (via TestClient) -------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    # Use a fresh DB per test so we don't trample the on-disk data/reviews.db
    # (which carries over state from previous test runs and may have an older
    # schema). Mirrors the conftest's client fixture.
    import persistence
    db = tmp_path / "reviews.db"
    monkeypatch.setattr(persistence.config, "DB_PATH", db)
    persistence.init_schema()
    return TestClient(app)


def _review_payload():
    return {
        "title": "t",
        "files": [{"path": "a.py", "content": "x = 1\n", "language": "python"}],
        "focuses": ["bug"],
    }


def test_api_key_required_when_configured(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_API_KEY", "secret")
    resp = client.post("/api/review", json=_review_payload())
    assert resp.status_code == 401
    assert "Bearer" in resp.headers.get("www-authenticate", "")


def test_api_key_accepted_with_correct_header(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_API_KEY", "secret")
    resp = client.post(
        "/api/review",
        json=_review_payload(),
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200


def test_api_key_rejects_wrong_value(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_API_KEY", "secret")
    resp = client.post(
        "/api/review",
        json=_review_payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_api_key_disabled_when_unset(client):
    # No env var; default empty. Should accept any request.
    resp = client.post("/api/review", json=_review_payload())
    assert resp.status_code == 200


def test_rate_limit_blocks_after_quota(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_RATE_LIMIT_PER_MIN", 2)
    # Reset module-level limiter so the new config takes effect
    auth._limiter = None
    try:
        r1 = client.post("/api/review", json=_review_payload())
        r2 = client.post("/api/review", json=_review_payload())
        r3 = client.post("/api/review", json=_review_payload())
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
    finally:
        auth._limiter = None


def test_rate_limit_disabled_when_zero(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_RATE_LIMIT_PER_MIN", 0)
    auth._limiter = None
    try:
        for _ in range(5):
            r = client.post("/api/review", json=_review_payload())
            assert r.status_code == 200
    finally:
        auth._limiter = None


def test_rate_limit_keys_separate_per_bearer(monkeypatch, client):
    """Per-caller rate limiting: a failing key doesn't exhaust a fresh one.

    The underlying per-key isolation is unit-tested in
    `test_sliding_window_keys_are_independent`; this test just confirms
    the dependency wires that isolation into the HTTP layer.
    """
    monkeypatch.setattr(config, "REVIEW_API_KEY", "k1")
    monkeypatch.setattr(config, "REVIEW_RATE_LIMIT_PER_MIN", 1)
    auth._limiter = None
    try:
        r1 = client.post(
            "/api/review",
            json=_review_payload(),
            headers={"Authorization": "Bearer k1"},
        )
        r2 = client.post(
            "/api/review",
            json=_review_payload(),
            headers={"Authorization": "Bearer k1"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 429
        # A different bearer key starts fresh — even though it's not the
        # configured key, the rate-limit key derived from the first 8
        # characters of the token is different.
        r3 = client.post(
            "/api/review",
            json=_review_payload(),
            headers={"Authorization": "Bearer different-token-here"},
        )
        # Will be 401 (wrong key), but importantly NOT 429 — the rate
        # limit didn't carry over.
        assert r3.status_code == 401
    finally:
        auth._limiter = None


# --- Long review id ------------------------------------------------------

def test_review_id_length_uses_configured_value(monkeypatch, client):
    monkeypatch.setattr(config, "REVIEW_ID_LENGTH", 16)
    resp = client.post("/api/review", json=_review_payload())
    assert resp.status_code == 200
    assert len(resp.json()["id"]) == 16
