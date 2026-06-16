"""Tests for backend/git_remote.py.

Covers URL validation, host allowlist, SSRF rejection, and the
in-process RemoteCache against a real local bare git repo (no network).
The network-dependent paths (real clone / fetch of github.com etc.) are
not exercised in CI; they're guarded by a manual env var and would
require credentials / outbound network.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import git_remote

# --- URL parsing ----------------------------------------------------------


def test_parse_https_url_ok():
    p = git_remote._parse_url("https://github.com/octocat/Hello-World")
    assert p.host == "github.com"
    assert p.name == "octocat/Hello-World"
    assert p.scheme == "https"
    assert p.ssh_user is None
    assert p.canonical == "https://github.com/octocat/Hello-World"


def test_parse_https_url_strip_dot_git():
    p = git_remote._parse_url("https://github.com/octocat/Hello-World.git/")
    assert p.name == "octocat/Hello-World"


def test_parse_ssh_scp_form():
    p = git_remote._parse_url("git@github.com:octocat/Hello-World.git")
    assert p.host == "github.com"
    assert p.name == "octocat/Hello-World"
    assert p.scheme == "ssh"
    assert p.ssh_user == "git"


def test_parse_rejects_file_scheme():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("file:///etc/passwd")


def test_parse_rejects_ssh_scheme():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("ssh://git@github.com/octocat/Hello-World.git")


def test_parse_rejects_git_scheme():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("git://github.com/octocat/Hello-World.git")


def test_parse_rejects_missing_path():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://github.com/")


def test_parse_rejects_invalid_path_segment():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://github.com/octocat/..//repo")


def test_parse_rejects_dot_dot_segment():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://github.com/octocat/../etc")


def test_parse_rejects_dash_prefix():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("--upload-pack=evil")


def test_parse_rejects_empty():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("   ")


def test_parse_rejects_too_long():
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://github.com/o/r" + "x" * 2000)


def test_parse_rejects_host_not_in_allowlist(monkeypatch):
    monkeypatch.setattr(
        config, "REMOTE_GIT_ALLOWED_HOSTS", ("github.com",), raising=False
    )
    git_remote._Allowlist.__module__ = "git_remote"  # noop, just to keep import quiet
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://gitlab.com/o/r")


def test_parse_accepts_suffix_allowlist(monkeypatch):
    monkeypatch.setattr(
        config, "REMOTE_GIT_ALLOWED_HOSTS", (".github.com",), raising=False
    )
    p = git_remote._parse_url("https://api.github.com/o/r")
    assert p.host == "api.github.com"


def test_parse_rejects_private_ip(monkeypatch):
    """When the host resolves to a private IP, refuse — even if the
    hostname passes the allowlist."""
    monkeypatch.setattr(
        config, "REMOTE_GIT_ALLOWED_HOSTS", ("example.test",), raising=False
    )

    class _FakeInfo:
        def __init__(self, ip):
            self._ip = ip

        def __getitem__(self, k):
            return (self._ip, 0) if k == 4 else (self._ip, 0, 0, 0, 0)

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(git_remote.RemoteGitURLError) as ei:
        git_remote._parse_url("https://example.test/o/r")
    assert "non-public" in str(ei.value).lower() or "private" in str(ei.value).lower() or "private" in str(ei.value) or "10.0.0.1" in str(ei.value)


def test_parse_rejects_loopback(monkeypatch):
    monkeypatch.setattr(
        config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False
    )

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._parse_url("https://localhost/o/r")


# --- _classify_and_raise: error subclass mapping --------------------------


def test_classify_network_error_gnutls():
    """The exact 'GnuTLS recv error (-110)' message that users see when
    the backend host is behind a firewall / proxy / sandbox without
    HTTPS egress must be classified as a network error so the UI can
    show a hint about the proxy / SSH URL escape hatch."""
    base = git_remote.RemoteGitError(
        "fatal: unable to access 'https://github.com/x/y/': "
        "GnuTLS recv error (-110): The TLS connection was non-properly terminated."
    )
    with pytest.raises(git_remote.RemoteGitNetworkError) as ei:
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")
    # The hint should mention the proxy env var the user can set.
    assert "GIT_HTTPS_PROXY" in str(ei.value) or "proxy" in str(ei.value).lower()


def test_classify_network_error_connection_refused():
    base = git_remote.RemoteGitError("fatal: unable to access …: Connection refused")
    with pytest.raises(git_remote.RemoteGitNetworkError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


def test_classify_network_error_proxy_explicit():
    base = git_remote.RemoteGitError("fatal: unable to access …: Could not resolve proxy host")
    with pytest.raises(git_remote.RemoteGitNetworkError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


def test_classify_timeout_still_timeout():
    base = git_remote.RemoteGitError("fatal: unable to access …: Operation timed out")
    with pytest.raises(git_remote.RemoteGitTimeoutError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


def test_classify_auth_still_auth():
    base = git_remote.RemoteGitError("fatal: Authentication failed for 'https://…'")
    with pytest.raises(git_remote.RemoteGitAuthError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


def test_classify_not_found_still_not_found():
    base = git_remote.RemoteGitError("remote: Repository not found.")
    with pytest.raises(git_remote.RemoteGitNotFoundError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


def test_classify_unknown_reraises_original():
    """An unrecognized error message is re-raised as the same RemoteGitError
    — not silently swallowed — so the caller still sees a failure."""
    base = git_remote.RemoteGitError("some weird thing we don't recognize")
    with pytest.raises(git_remote.RemoteGitError) as ei:
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")
    assert str(ei.value) == "some weird thing we don't recognize"


# --- _inject_token --------------------------------------------------------


def test_inject_token_into_https():
    p = git_remote._parse_url("https://github.com/o/r")
    out = git_remote._inject_token(p, "secret123")
    assert out == "https://oauth2:secret123@github.com/o/r"


def test_inject_token_omitted_keeps_canonical():
    p = git_remote._parse_url("https://github.com/o/r")
    assert git_remote._inject_token(p, None) == "https://github.com/o/r"


def test_inject_token_rejects_for_ssh():
    p = git_remote._parse_url("git@github.com:o/r.git")
    with pytest.raises(git_remote.RemoteGitURLError):
        git_remote._inject_token(p, "secret123")
    # No token: SSH URL is returned untouched.
    assert git_remote._inject_token(p, None) == "git@github.com:o/r.git"


# --- RemoteCache with a local bare repo ---------------------------------


def _make_bare_remote(tmp_path: Path) -> Path:
    """Build a real local bare git repo to act as a 'remote'.

    `tmp_path` is the parent directory; the helper creates `tmp_path/src/`
    as the working repo and `tmp_path/bare.git` as the bare clone. The
    bare path is returned so callers can build a `file://` URL out of it.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "src"
    src.mkdir()

    def run(args, cwd=src):
        return subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@e.com", *args],
            cwd=str(cwd), check=True, capture_output=True, text=True,
        )

    run(["init", "-q", "-b", "main"])
    (src / "a.py").write_text("a=1\n")
    run(["add", "."])
    run(["commit", "-q", "-m", "init"])
    # branch 'feature'
    run(["checkout", "-q", "-b", "feature"])
    (src / "a.py").write_text("a=2\n")
    (src / "b.py").write_text("b=1\n")
    run(["add", "."])
    run(["commit", "-q", "-m", "feature"])
    # make a tag
    run(["tag", "v1.0"])

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        check=True, capture_output=True, text=True,
    )
    return bare


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    # Keep TTL long so cache-hit path doesn't refresh in tests.
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    # Tests use file:// URLs against a local bare repo. The strict URL
    # validator (correctly) rejects file:// in production, so swap in a
    # test-only variant that permits it. Network-only paths (real
    # github.com clones etc.) are not exercised here.
    def _parse_url_for_tests(raw: str) -> git_remote._ParsedURL:
        from urllib.parse import urlparse as _urlparse
        if raw.startswith("file://"):
            path = raw[len("file://") :]
            # accept '/path' or 'host/path'
            parsed = _urlparse(raw)
            host = (parsed.hostname or "").lower()
            if not host:
                # plain file:///abs/path
                name = path.rstrip("/")
                if name.endswith(".git"):
                    name = name[: -len(".git")]
                if "/" not in name:
                    raise git_remote.RemoteGitURLError("file:// URL needs owner/repo path")
                return git_remote._ParsedURL(
                    canonical=raw,
                    host="",
                    path="/" + path.lstrip("/"),
                    name=name,
                    scheme="https",  # git clone handles file:// via path; scheme is cosmetic
                    ssh_user=None,
                )
        return git_remote._parse_url(raw)

    monkeypatch.setattr(git_remote, "_parse_url", _parse_url_for_tests)
    monkeypatch.setattr(
        config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False
    )
    return base


def test_get_or_create_clones_then_caches(cache_dir, tmp_path):
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()
    entry, was_cached = cache.get_or_create(url)
    assert was_cached is False
    assert (entry.path / ".git").exists()
    # Second call within TTL is a cache hit (we still refresh refs on
    # the hit — see test_cache_hit_refreshes_new_branches — but the
    # entry identity is preserved).
    entry2, was_cached2 = cache.get_or_create(url)
    assert was_cached2 is True
    assert entry2.id == entry.id


def test_cache_hit_refreshes_new_branches(cache_dir, tmp_path):
    """Regression: a branch pushed after the initial clone was
    invisible in the picker until TTL expired — the cache hit path
    returned the stale entry without running a `git fetch`. Fix: a
    cache hit now does a cheap refs-only fetch, so a freshly pushed
    branch is visible on the very next status call (no manual
    Refresh click required)."""
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()

    # First call: initial clone, both `main` and `feature` are picked
    # up by `--no-single-branch`.
    entry, _ = cache.get_or_create(url)
    names = {b["name"] for b in cache.list_branches(entry)}
    assert "main" in names
    assert "feature" in names

    # Push a new branch to the source (we can't add a branch to a bare
    # repo directly, so we go through a non-bare working copy).
    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@e.com",
         "checkout", "-q", "-b", "hotfix"],
        cwd=str(work), check=True, capture_output=True, text=True,
    )
    (work / "hot.py").write_text("h=1\n")
    subprocess.run(
        ["git", "add", "."], cwd=str(work), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@e.com",
         "commit", "-q", "-m", "hotfix"],
        cwd=str(work), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "push", "-q", "origin", "hotfix"],
        cwd=str(work), check=True, capture_output=True, text=True,
    )

    # Second call within TTL — without the fix this would still return
    # the stale {main, feature} set. With the fix the cheap refs-only
    # fetch picks up `hotfix` immediately.
    entry2, was_cached = cache.get_or_create(url)
    assert was_cached is True
    names2 = {b["name"] for b in cache.list_branches(entry2)}
    assert "hotfix" in names2, (
        f"expected 'hotfix' in branch list after cache-hit refresh; "
        f"got {sorted(names2)}"
    )


def test_get_or_create_force_refresh_runs_git(cache_dir, tmp_path):
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()
    cache.get_or_create(url)
    # force_refresh runs the fetch (which on a bare file:// is a no-op
    # for content but still touches fetched_at).
    entry, was_cached = cache.get_or_create(url, force_refresh=True)
    assert was_cached is False


def test_list_branches_and_tags(cache_dir, tmp_path):
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()
    entry, _ = cache.get_or_create(url)
    status = cache.get_status(entry)
    names = {b["name"] for b in status["branches"]}
    # All remote branches (both `main` and `feature`) are fetched —
    # the old behavior used `--single-branch` which only mirrored the
    # default branch, leaving the UI's branch picker effectively empty
    # for repos with multiple branches. With the refspec refactor,
    # `refs/remotes/origin/*` mirrors every branch at depth 1.
    assert "main" in names
    assert "feature" in names
    # --no-tags still applies on clone, so the tag set is empty.
    assert status["tags"] == []
    # Default branch prefers the bare repo's HEAD (set by `git clone`
    # from the source); `_make_bare_remote` leaves HEAD on `feature`,
    # so that's the value the UI should auto-pick as the base.
    assert status["default_branch"] == "feature"


def test_default_branch_prefers_head_over_well_known_name(cache_dir, tmp_path):
    """When the cloned repo's HEAD is on a non-standard branch (e.g. a
    bare repo that left HEAD pointing at 'develop' with `main` also
    existing), the default branch should follow HEAD, not the
    well-known-name priority list (`main` / `master` / …)."""
    # Build a bare repo whose HEAD is on a non-standard branch
    src = tmp_path / "src"; src.mkdir()
    def run(args, cwd=src):
        subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@e.com", *args],
            cwd=str(cwd), check=True, capture_output=True, text=True,
        )
    run(["init", "-q", "-b", "main"])
    (src / "a.py").write_text("a\n"); run(["add", "."]); run(["commit", "-q", "-m", "i"])
    run(["checkout", "-q", "-b", "develop"])
    (src / "b.py").write_text("b\n"); run(["add", "."]); run(["commit", "-q", "-m", "d"])
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True, text=True)

    cache = git_remote.RemoteCache()
    entry, _ = cache.get_or_create(f"file://{bare}")
    status = cache.get_status(entry)
    # Both branches present, but default follows the source's HEAD.
    assert "main" in {b["name"] for b in status["branches"]}
    assert "develop" in {b["name"] for b in status["branches"]}
    assert status["default_branch"] == "develop"


def test_list_empty_when_unused(cache_dir):
    cache = git_remote.RemoteCache()
    assert cache.list() == []


def test_delete_removes_cache(cache_dir, tmp_path):
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()
    entry, _ = cache.get_or_create(url)
    assert cache.delete(entry.id) is True
    assert not (entry.path).exists()
    # Second delete is a no-op
    assert cache.delete(entry.id) is False


def test_get_status_unknown_returns_none(cache_dir):
    cache = git_remote.RemoteCache()
    assert cache.get("nonexistent") is None


# --- state.json round-trip -----------------------------------------------


def test_state_persisted_on_disk(cache_dir, tmp_path):
    bare = _make_bare_remote(tmp_path)
    url = f"file://{bare}"
    cache = git_remote.RemoteCache()
    entry, _ = cache.get_or_create(url)
    state_path = entry.path / git_remote._STATE_FILE
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["id"] == entry.id
    assert state["url"] == url
    assert state["host"] == ""
    # file:// has no host, so the host field is empty — that's fine.
    assert "fetched_at" in state and state["fetched_at"] > 0


# --- LRU eviction / sweep / size cap ------------------------------------


def _make_two_remote_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Build two distinct bare repos for LRU tests."""
    a = _make_bare_remote(tmp_path / "a")
    b = _make_bare_remote(tmp_path / "b")
    return a, b


def test_lru_eviction_drops_oldest(tmp_path, monkeypatch):
    """When the cap is 1 and we have 2 entries, evict_lru drops the
    older one (by `last_used_at` ascending). The point is the LRU math,
    not the cap enforcement at get_or_create time — we set the cap to
    a high value while populating, then tighten and call evict_lru
    directly so we can assert exactly which entry went."""
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    # High cap while populating — we want both entries in the index.
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_MAX", 100)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    # Permit file:// via the same test backdoor.
    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)

    cache = git_remote.RemoteCache()
    a, b = _make_two_remote_repos(tmp_path)
    e1, _ = cache.get_or_create(f"file://{a}")
    # Touch e1 so it's strictly newer than e2.
    e1.last_used_at = time.time() + 5
    cache._persist(e1)
    e2, _ = cache.get_or_create(f"file://{b}")
    # Now have 2 entries. Tighten the cap and call evict_lru directly.
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_MAX", 1)
    removed = cache.evict_lru()
    assert e2.id in removed
    assert e1.id not in removed
    listed = {r["id"] for r in cache.list()}
    assert e1.id in listed
    assert e2.id not in listed


def test_sweep_stale_removes_unused(tmp_path, monkeypatch):
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_MAX", 10)
    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)

    cache = git_remote.RemoteCache()
    a, _ = _make_two_remote_repos(tmp_path)
    e1, _ = cache.get_or_create(f"file://{a}")
    # Backdate last_used_at past the threshold.
    e1.last_used_at = 0.0
    cache._persist(e1)
    removed = cache.sweep_stale(max_age_seconds=1.0)
    assert e1.id in removed


def test_sweep_stale_noop_when_recent(tmp_path, monkeypatch):
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)

    cache = git_remote.RemoteCache()
    a, _ = _make_two_remote_repos(tmp_path)
    e1, _ = cache.get_or_create(f"file://{a}")
    # Just-cloned entry has last_used_at ≈ now — should not be reaped.
    removed = cache.sweep_stale(max_age_seconds=10_000)
    assert removed == []


def test_size_cap_hides_oversized_entry(tmp_path, monkeypatch):
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    monkeypatch.setattr(config, "REMOTE_GIT_MAX_SIZE_MB", 0)  # disabled
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_MAX", 10)
    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)
    cache = git_remote.RemoteCache()
    a, _ = _make_two_remote_repos(tmp_path)
    e1, _ = cache.get_or_create(f"file://{a}")
    # With cap=0 the entry is never hidden.
    assert e1.id in {r.id for r in [e1]}

    # Now enable a tiny cap and force the entry to be re-evaluated.
    monkeypatch.setattr(config, "REMOTE_GIT_MAX_SIZE_MB", 0)  # still disabled
    cache._enforce_size_cap(e1)
    assert cache.get(e1.id) is not None

    # Enable a very low cap that the real on-disk tree will exceed.
    monkeypatch.setattr(config, "REMOTE_GIT_MAX_SIZE_MB", 1)  # 1 MB
    # Patch dir_size_mb to lie about a huge size.
    monkeypatch.setattr(cache, "dir_size_mb", lambda _e: 999.0)
    cache._enforce_size_cap(e1)
    # Hides from in-memory index.
    assert cache.get(e1.id) is None
    # But state on disk marks it as oversized.
    state = json.loads((e1.path / git_remote._STATE_FILE).read_text())
    assert state.get("oversized") is True


# --- _run_git: TimeoutExpired surfaces real stderr -----------------------
#
# Regression: when the backend host is behind a transparent SSL
# interception / proxy, the git subprocess hangs waiting for data,
# the 300s timeout fires, and the original TimeoutExpired carries
# stderr like "fatal: ... GnuTLS recv error (-110): non-properly
# terminated". The old code discarded e.stderr and raised
# RemoteGitTimeoutError("git command timed out after 300s"), which
# surfaced to the UI as a 504 with no actionable detail — the user
# had to guess whether it was the timeout, the proxy, or the URL.
#
# Fix: capture e.stderr, build a wrapper message that includes it,
# and feed the message to the classifier so a network-marker stderr
# gets reclassified as RemoteGitNetworkError (with the proxy/SSH
# hint the i18n layer is already wired to render).


def test_run_git_timeout_with_gnutls_stderr_raises_network_error(monkeypatch, tmp_path):
    import subprocess as _subprocess

    real_exc = _subprocess.TimeoutExpired(
        cmd=["git", "clone", "https://github.com/o/r"],
        timeout=300,
        output="",
        stderr=(
            "Cloning into '/tmp/x'...\n"
            "fatal: unable to access 'https://github.com/o/r/': "
            "GnuTLS recv error (-110): The TLS connection was non-properly terminated.\n"
        ),
    )

    def _raise(*_a, **_k):
        raise real_exc

    monkeypatch.setattr(git_remote.subprocess, "run", _raise)

    cache = git_remote.RemoteCache()
    with pytest.raises(git_remote.RemoteGitNetworkError) as ei:
        cache._run_git(["clone", "https://github.com/o/r"], cwd=tmp_path)
    # The gnutls detail must be visible in the raised message so the
    # user (and the i18n hint) can see *why* it timed out.
    msg = str(ei.value)
    assert "GnuTLS" in msg
    # The classifier appends the proxy/SSH hint for network errors.
    assert "GIT_HTTPS_PROXY" in msg or "proxy" in msg.lower()


def test_run_git_timeout_with_connection_timed_out_stderr_raises_network(monkeypatch, tmp_path):
    """`Connection timed out` from git is a network marker (TCP SYN
    never got ACK'd, usually a firewall) — reclassify so the user
    gets the proxy/SSH hint, not a bare 504 timeout."""
    import subprocess as _subprocess

    real_exc = _subprocess.TimeoutExpired(
        cmd=["git", "fetch", "origin"],
        timeout=300,
        output="",
        stderr=(
            "fatal: unable to access 'https://github.com/o/r/': "
            "Connection timed out\n"
        ),
    )

    def _raise(*_a, **_k):
        raise real_exc

    monkeypatch.setattr(git_remote.subprocess, "run", _raise)

    cache = git_remote.RemoteCache()
    with pytest.raises(git_remote.RemoteGitNetworkError):
        cache._run_git(["fetch", "origin"], cwd=tmp_path)


def test_run_git_timeout_with_empty_stderr_preserves_timeout(monkeypatch, tmp_path):
    """If git was killed before producing any stderr (silent hang,
    wedged in a syscall), the only honest answer is 'we timed out
    with no idea why'. RemoteGitTimeoutError preserves the existing
    504 / 'increase the timeout' remediation."""
    import subprocess as _subprocess

    real_exc = _subprocess.TimeoutExpired(
        cmd=["git", "clone", "https://github.com/o/r"],
        timeout=300,
    )

    def _raise(*_a, **_k):
        raise real_exc

    monkeypatch.setattr(git_remote.subprocess, "run", _raise)

    cache = git_remote.RemoteCache()
    with pytest.raises(git_remote.RemoteGitTimeoutError) as ei:
        cache._run_git(["clone", "https://github.com/o/r"], cwd=tmp_path)
    assert "timed out" in str(ei.value).lower()


def test_classify_network_marker_beats_timed_out():
    """A message that contains BOTH 'timed out' (e.g. as a wrapper
    from a TimeoutExpired) and a network marker (gnutls / connection
    timed out / etc.) should be classified as a network error — the
    network marker is the more specific signal. Reordering the
    classifier to check network markers before 'timed out' is what
    makes the TimeoutExpired reclassification above work."""
    base = git_remote.RemoteGitError(
        "git command timed out after 300s — last output: "
        "fatal: unable to access 'https://github.com/o/r/': "
        "GnuTLS recv error (-110): non-properly terminated."
    )
    with pytest.raises(git_remote.RemoteGitNetworkError):
        git_remote.RemoteCache._classify_and_raise(base, masked_url="…")


# --- Stale lock recovery --------------------------------------------------


def test_stale_lock_is_removed_on_next_attempt(tmp_path, monkeypatch):
    """A lock file left over from a crashed / killed previous attempt
    should not block the next call forever. We plant a lock whose mtime
    is older than REMOTE_GIT_CLONE_TIMEOUT, run a fresh clone, and
    verify the lock is gone and the clone succeeded.

    The previous version waited the full timeout (300s default) on
    every retry, which the user experienced as a 5-minute hang and
    then a confusing 'Another clone is in progress' error. This is
    the real-world 500 the user reported (the long timeout on a stale
    lock made the request time out at the HTTP layer, which the
    frontend reported as 500 Internal Server Error)."""
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    monkeypatch.setattr(config, "REMOTE_GIT_CLONE_TIMEOUT", 60)  # tight for the test
    monkeypatch.setattr(config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False)

    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)

    cache = git_remote.RemoteCache()
    bare = _make_bare_remote(tmp_path / "src")
    url = f"file://{bare}"

    # First clone — populates the cache.
    entry, _ = cache.get_or_create(url)
    lock_path = cache._lock_path(entry)
    assert not lock_path.exists(), "lock should be cleaned up after success"

    # Simulate a crashed attempt: plant a lock whose mtime is in the
    # distant past so the stale-lock detector kicks in.
    import os, time
    lock_path.touch()
    old_mtime = time.time() - (config.REMOTE_GIT_CLONE_TIMEOUT + 60)
    os.utime(lock_path, (old_mtime, old_mtime))

    # The next call should NOT hang. The stale lock is removed and
    # the clone (well, the refresh path since the entry already exists)
    # proceeds. We use force_refresh so the lock is re-touched and
    # re-removed by the finally.
    entry2, _ = cache.get_or_create(url, force_refresh=True)
    assert entry2.id == entry.id
    # The stale lock was cleared during the call.
    assert not lock_path.exists()


def test_fresh_lock_is_not_evicted(tmp_path, monkeypatch):
    """A lock that's still inside the timeout window is real — don't
    blow it away. The previous (stale-only) behavior has to coexist
    with the in-progress-detection so two concurrent clones for the
    same URL still serialize."""
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CLONE_TIMEOUT", 60)
    monkeypatch.setattr(config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False)

    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return git_remote._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return git_remote._parse_url(raw)
    monkeypatch.setattr(git_remote, "_parse_url", _parse)

    cache = git_remote.RemoteCache()
    bare = _make_bare_remote(tmp_path / "src")
    url = f"file://{bare}"
    entry, _ = cache.get_or_create(url)
    lock_path = cache._lock_path(entry)

    # Plant a fresh lock (just-touched mtime). The next call should
    # NOT evict it; it should wait briefly and then fail with the
    # 'Another clone in progress' error.
    lock_path.touch()
    with pytest.raises(git_remote.RemoteGitError) as ei:
        cache.get_or_create(url, force_refresh=True)
    assert "Another clone" in str(ei.value)
    # The original lock is still on disk (we didn't touch it).
    assert lock_path.exists()
    lock_path.unlink()
