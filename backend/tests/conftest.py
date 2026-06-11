"""Shared pytest fixtures."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main
import persistence
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Build a TestClient with a fresh SQLite file for each test."""
    db = tmp_path / "reviews.db"
    monkeypatch.setattr(persistence.config, "DB_PATH", db)
    persistence.init_schema()
    return TestClient(main.app)


@pytest.fixture
def wait_for_completion(client):
    """Return a helper that polls a review until it reaches a terminal state."""
    import time

    def _wait(rid, timeout_s=5.0):
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            r = client.get(f"/api/reviews/{rid}")
            last = r.json()
            if last.get("status") in ("completed", "failed"):
                return last
            time.sleep(0.05)
        raise AssertionError(f"Review {rid} did not complete in {timeout_s}s; last status={last.get('status') if last else 'unknown'}")

    return _wait
