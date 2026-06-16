"""End-to-end API tests using FastAPI's TestClient."""
import config
import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ai_provider" in body


def test_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "ai_enabled" in body
    assert "focuses" in body
    assert "default_model" in body
    # I1 addition: the public config also reports whether the remote-git
    # feature is enabled, so the frontend can hide the Remote tab.
    assert "remote_git_enabled" in body
    assert body["remote_git_enabled"] is True
    # The local-git (`REPO_PATH`) and snippet/diff modes were removed —
    # `git_enabled` / `git_repo_path` should no longer be exposed.
    assert "git_enabled" not in body
    assert "git_repo_path" not in body


def test_review_round_trip(client, wait_for_completion):
    payload = {
        "files": [{"path": "x.py", "language": "python", "content": "eval('1')\n"}],
        "title": "t",
        "focuses": ["security", "bug"],
    }
    r = client.post("/api/review", json=payload)
    assert r.status_code == 200
    rid = r.json()["id"]

    body = wait_for_completion(rid)
    assert body["id"] == rid
    assert body["status"] == "completed"
    # mock review of `eval('1')` should produce at least one finding
    assert isinstance(body["findings"], list)
    assert len(body["findings"]) >= 1
    # finding should mention eval
    assert any("eval" in f["title"].lower() for f in body["findings"])


def test_review_not_found(client):
    r = client.get("/api/reviews/does-not-exist")
    assert r.status_code == 404


def test_list_reviews(client, wait_for_completion):
    rids = []
    for i in range(2):
        r = client.post(
            "/api/review",
            json={"files": [{"path": f"x{i}.py", "content": "pass\n"}], "title": f"t{i}"},
        )
        assert r.status_code == 200
        rids.append(r.json()["id"])
    for rid in rids:
        wait_for_completion(rid)

    r = client.get("/api/reviews")
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    # items should not include the full findings list
    assert all("findings" not in i for i in body["items"])


def test_delete_review(client):
    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    r = client.delete(f"/api/reviews/{rid}")
    assert r.status_code == 200
    r = client.get(f"/api/reviews/{rid}")
    assert r.status_code == 404


def test_review_too_many_files(client):
    # Pydantic enforces max_length=50 on the files list, so this returns
    # 422 (validation error) rather than 400 (custom check).
    files = [{"path": f"x{i}.py", "content": "pass\n"} for i in range(60)]
    r = client.post("/api/review", json={"files": files, "title": "t"})
    assert r.status_code == 422


def test_review_with_focuses(client, wait_for_completion):
    """Different focuses should be respected (in mock, all rules fire — but
    the request body is preserved)."""
    r = client.post(
        "/api/review",
        json={
            "files": [{"path": "x.py", "language": "python", "content": "eval('1')\n"}],
            "title": "t",
            "focuses": ["security"],
        },
    )
    rid = r.json()["id"]
    body = wait_for_completion(rid)
    assert "security" in body["focuses"]


def test_sse_terminal_review(client, wait_for_completion):
    """The SSE endpoint should not block when the review is already complete."""
    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    wait_for_completion(rid)

    # Open the SSE stream — it should emit the terminal status and close.
    with client.stream("GET", f"/api/reviews/{rid}/events") as resp:
        assert resp.status_code == 200
        # Read the first chunk
        chunks = []
        for line in resp.iter_lines():
            chunks.append(line)
            if any("event: done" in c for c in chunks):
                break
        assert any("event:" in c for c in chunks)


def test_sse_terminal_review_emits_done_event(client, wait_for_completion):
    """Regression: a synthetic `done` SSE event must be emitted for an
    already-terminal review, so useReviewSession closes its EventSource
    even when it never connected to the live stream (e.g. user opens a
    completed review from history). Without this, the EventSource would
    leak until the server-side generator returns."""
    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    final = wait_for_completion(rid)

    with client.stream("GET", f"/api/reviews/{rid}/events") as resp:
        assert resp.status_code == 200
        # Read until the connection closes (the terminal-review path
        # doesn't push an _eof; it just returns).
        body = b""
        for chunk in resp.iter_bytes():
            body += chunk
    text = body.decode()
    assert "event: done" in text
    assert f'"status": "{final["status"]}"' in text


def test_sse_terminates_when_aupsert_fails(client, monkeypatch):
    """Regression for P0-#5: even if persistence.aupsert throws inside the
    background task, the SSE consumer must still see a terminal event
    and not hang waiting for messages that never arrive."""
    import persistence

    real_aupsert = persistence.aupsert
    state = {"calls": 0}

    async def flaky_aupsert(review):
        state["calls"] += 1
        # Call 1: initial pending row in submit_review — succeed.
        # Call 2: streaming status update in _run_review — fail.
        # Call 3+: the recovery aupsert in the finally block — succeed
        # so the failed state actually lands in the DB.
        if state["calls"] in (1, 3):
            return await real_aupsert(review)
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(persistence, "aupsert", flaky_aupsert)

    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    assert r.status_code == 200
    rid = r.json()["id"]

    # Open the SSE stream. The consumer must see a terminal event
    # (either an in-band `done` while the background task is still
    # running, or a one-shot `status` event when the review is already
    # terminal). Either way, the stream must close — not hang.
    with client.stream("GET", f"/api/reviews/{rid}/events") as resp:
        assert resp.status_code == 200
        chunks = []
        for line in resp.iter_lines():
            chunks.append(line)
            if any("event: done" in c for c in chunks):
                break
            if any("event: status" in c for c in chunks):
                break
        assert any(
            ("event: done" in c) or ("event: status" in c) for c in chunks
        ), "SSE consumer hung — no terminal event ever arrived"

    # The persisted row should also be in a terminal state.
    final = client.get(f"/api/reviews/{rid}").json()
    assert final["status"] == "failed"
    assert "simulated DB outage" in final["error"]


def test_cancel_review(client, wait_for_completion):
    """POST /api/reviews/{id}/cancel should mark a streaming review as failed."""
    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    # Cancel right away; mock review completes very quickly so the
    # cancel may race with completion. Either way, the row should end
    # up in a terminal state.
    client.post(f"/api/reviews/{rid}/cancel")
    body = wait_for_completion(rid)
    assert body["status"] in ("failed", "completed")
    if body["status"] == "failed":
        assert body["error"] == "cancelled"


def test_cancel_unknown_review(client):
    r = client.post("/api/reviews/does-not-exist/cancel")
    assert r.status_code == 404


def test_cancel_does_not_leak_id_for_terminal_review(client, wait_for_completion):
    """Regression for P1-#13: cancelling a review whose background task is
    already done must NOT leave its id in the `_cancelled` set — there's
    no live task to pick it up, so it would sit there forever."""
    import main

    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    wait_for_completion(rid)  # background task is now done
    # cancel should be a no-op for the set, even though it returns 200.
    client.post(f"/api/reviews/{rid}/cancel")
    assert rid not in main._cancelled


def test_cancel_keeps_id_for_in_flight_review(client):
    """A cancel for a still-streaming review DOES register in `_cancelled`
    so the background task can pick it up and bail."""
    import main

    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    # We don't wait for completion — the task may still be running. The
    # race is fine: the assert is "not absent", which holds whenever the
    # cancel arrived before the task's finally block ran.
    if rid in main._event_queues:
        client.post(f"/api/reviews/{rid}/cancel")
        assert rid in main._cancelled
    # Either way, after the task ends, the id should be gone from the set.
    import time
    for _ in range(20):
        if rid not in main._cancelled:
            break
        time.sleep(0.05)
    assert rid not in main._cancelled


def test_event_queues_cleaned_after_review_completes(client, wait_for_completion):
    """Regression: the per-review asyncio.Queue must be popped from
    `_event_queues` once the background task ends, otherwise the dict
    grows unbounded across many reviews."""
    import main

    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "pass\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    wait_for_completion(rid)
    # After completion, the queue entry should be gone.
    import time
    for _ in range(20):
        if rid not in main._event_queues:
            break
        time.sleep(0.05)
    assert rid not in main._event_queues


def test_rerun_review(client, wait_for_completion):
    """POST /api/reviews/{id}/rerun should produce a new review with the same
    files. Both the original and the rerun should reach 'completed'."""
    r = client.post(
        "/api/review",
        json={"files": [{"path": "x.py", "content": "eval('1')\n"}], "title": "t"},
    )
    rid = r.json()["id"]
    wait_for_completion(rid)

    rr = client.post(f"/api/reviews/{rid}/rerun")
    assert rr.status_code == 200
    new_id = rr.json()["id"]
    assert new_id != rid
    new_body = wait_for_completion(new_id)
    assert new_body["status"] == "completed"
    assert new_body["file_count"] == 1


def test_rerun_unknown_review(client):
    r = client.post("/api/reviews/does-not-exist/rerun")
    assert r.status_code == 404


# --- Remote git integration ----------------------------------------------

import subprocess as _sp  # local alias to avoid shadowing in earlier tests


def _make_bare_repo(path) -> str:
    """Build a tiny local bare repo and return its file:// URL."""
    src = path / "src"
    src.mkdir()
    def run(args, cwd=src):
        _sp.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", *args],
                cwd=str(cwd), check=True, capture_output=True, text=True)
    run(["init", "-q", "-b", "main"])
    (src / "a.py").write_text("a=1\n")
    run(["add", "."]); run(["commit", "-q", "-m", "init"])
    run(["checkout", "-q", "-b", "feature"])
    (src / "a.py").write_text("a=2\n")
    (src / "b.py").write_text("b=1\n")
    run(["add", "."]); run(["commit", "-q", "-m", "feature"])
    bare = path / "bare.git"
    _sp.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True, text=True)
    return f"file://{bare}"


@pytest.fixture
def _remote_gate(monkeypatch, tmp_path):
    """Wire up the file:// test backdoor so API tests can clone a local
    bare repo without hitting the network."""
    import git_remote as _gr
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    monkeypatch.setattr(config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False)
    # Disable the rate limiter so a sequence of remote calls in one
    # test doesn't trip the module-level 20/min budget shared across
    # tests in the same process.
    monkeypatch.setattr(config, "REVIEW_RATE_LIMIT_PER_MIN", 0)
    # file:// allowlist bypass
    def _parse(raw):
        from urllib.parse import urlparse as _up
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return _gr._ParsedURL(canonical=raw, host="", path="/" + p.lstrip("/"),
                                  name=name, scheme="https", ssh_user=None)
        return _gr._parse_url(raw)
    monkeypatch.setattr(_gr, "_parse_url", _parse)
    return base


def test_remote_clone_status_diff_delete_round_trip(client, _remote_gate, tmp_path):
    url = _make_bare_repo(tmp_path)

    # clone
    r = client.post("/api/git/remote/clone", json={"url": url})
    assert r.status_code == 200, r.text
    body = r.json()
    # The file:// test backdoor derives `name` from the URL path; for
    # https URLs the helper splits on owner/repo. The point of this test
    # is the API surface — that the name is non-empty, an id was issued,
    # and the branch list is non-empty.
    assert body["name"]
    assert "feature" in {b["name"] for b in body["branches"]}
    rid = body["id"]
    assert rid and len(rid) == 12

    # list
    r = client.get("/api/git/remote")
    assert r.status_code == 200
    assert any(rem["id"] == rid for rem in r.json()["remotes"])

    # get status
    r = client.get(f"/api/git/remote/{rid}")
    assert r.status_code == 200

    # diff between the same ref (empty diff, no errors)
    r = client.post(f"/api/git/remote/{rid}/diff",
                    json={"base": "feature", "head": "feature"})
    assert r.status_code == 200, r.text
    assert r.json()["files"] == []

    # delete
    r = client.delete(f"/api/git/remote/{rid}")
    assert r.status_code == 200
    r = client.get(f"/api/git/remote/{rid}")
    assert r.status_code == 404


def test_remote_clone_rejects_bad_url(client):
    r = client.post("/api/git/remote/clone", json={"url": "file:///etc/passwd"})
    assert r.status_code == 400


def test_remote_clone_rejects_disallowed_host(client, monkeypatch):
    monkeypatch.setattr(config, "REMOTE_GIT_ALLOWED_HOSTS", ("github.com",), raising=False)
    r = client.post("/api/git/remote/clone", json={"url": "https://gitlab.com/x/y"})
    assert r.status_code == 400
    assert "not in" in r.json()["detail"].lower() or "allowlist" in r.json()["detail"].lower()


def test_remote_diff_unknown_remote(client, _remote_gate):
    r = client.post("/api/git/remote/deadbeef0000/diff", json={"base": "a", "head": "b"})
    assert r.status_code == 404


def test_remote_diff_rejects_bad_ref(client, _remote_gate, tmp_path):
    url = _make_bare_repo(tmp_path)
    r = client.post("/api/git/remote/clone", json={"url": url})
    rid = r.json()["id"]
    r = client.post(f"/api/git/remote/{rid}/diff",
                    json={"base": "main; rm -rf /", "head": "feature"})
    assert r.status_code == 400
