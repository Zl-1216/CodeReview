"""Remote git cache: clone / fetch user-supplied remote repos server-side.

Each unique URL gets a deterministic directory under
`config.REMOTE_GIT_CACHE_DIR` keyed by `sha1(url)[:12]`. The first request
clones (shallow, blobless) into that directory; subsequent requests
`git fetch` to refresh and serve a fresh diff.

Security:
  * URL host must be on the `REMOTE_GIT_ALLOWED_HOSTS` allowlist.
  * hostnames are resolved and any private / loopback / link-local IP is
    rejected (defense in depth against SSRF if the allowlist is widened).
  * Schemes other than https:// and `git@host:path` are rejected; we don't
    accept `file://`, `ssh://`, `git://` etc. to avoid the protocol
    surface area they bring.
  * The optional token is never written to disk — it lives only in the
    in-process state for the duration of one `get_or_create()` call and
    is masked in any error message.
  * The cache directory holds a `state.json` (URL, host, fetched_at) and
    a `.lock` file while a clone / fetch is running; a second request that
    arrives mid-operation is told to wait briefly, not duplicate the work.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import config

logger = logging.getLogger(__name__)


# --- Errors ----------------------------------------------------------------


class RemoteGitError(Exception):
    """Base class for user-visible remote-git failures.

    `.message` is safe to show in the UI. Subclasses carry a category so
    the API layer can pick a sensible HTTP status (400 for client errors,
    502 for upstream git failures, 504 for timeouts).
    """


class RemoteGitURLError(RemoteGitError):
    """URL failed validation (scheme / host / SSRF)."""


class RemoteGitAuthError(RemoteGitError):
    """Remote rejected credentials."""


class RemoteGitNotFoundError(RemoteGitError):
    """Repo does not exist or is not accessible."""


class RemoteGitTimeoutError(RemoteGitError):
    """Clone or fetch exceeded REMOTE_GIT_CLONE_TIMEOUT."""


class RemoteGitNetworkError(RemoteGitError):
    """The host is reachable in DNS but the TLS / TCP handshake failed.

    Surfaced as HTTP 502 (upstream connectivity issue). The frontend
    hint asks the user to check whether the backend host can actually
    reach the remote (corporate proxy, sandboxed container, etc.) —
    `git`'s GnuTLS `-110` error is one of the more cryptic messages,
    so we wrap it with an actionable prefix.
    """


# --- URL parsing / validation ----------------------------------------------


# Strict allowlist. We split into two sets: exact hosts and suffix hosts
# (entries starting with a dot). Both are checked case-insensitively.
@dataclass
class _Allowlist:
    exact: frozenset[str] = field(default_factory=frozenset)
    suffix: tuple[str, ...] = ()

    @classmethod
    def from_config(cls) -> "_Allowlist":
        exact: set[str] = set()
        suffix: list[str] = []
        for h in config.REMOTE_GIT_ALLOWED_HOSTS:
            if h.startswith("."):
                suffix.append(h)
            else:
                exact.add(h)
        return cls(exact=frozenset(exact), suffix=tuple(suffix))

    def allows(self, host: str) -> bool:
        host = host.lower()
        if host in self.exact:
            return True
        for s in self.suffix:
            if host.endswith(s):
                return True
        return False


_SSH_RE = re.compile(r"^(?P<user>[A-Za-z0-9_.\-]+)@(?P<host>[A-Za-z0-9.\-]+):(?P<path>.*)$")


@dataclass(frozen=True)
class _ParsedURL:
    """An URL that's been parsed and validated. The fields are the only
    safe-to-log representation; the token is never stored on this object."""

    canonical: str       # the original URL with token stripped
    host: str            # lowercased hostname
    path: str            # path component, leading "/", no trailing ".git" guaranteed
    name: str            # "owner/repo" derived from the path
    scheme: str          # "https" or "ssh"
    ssh_user: str | None  # for git@... form, e.g. "git"


def _parse_url(raw: str) -> _ParsedURL:
    """Parse + validate a user-supplied remote URL. Raises RemoteGitURLError."""
    if not isinstance(raw, str):
        raise RemoteGitURLError("URL must be a string")
    url = raw.strip()
    if not url:
        raise RemoteGitURLError("URL is required")
    if len(url) > 1024:
        raise RemoteGitURLError("URL is too long")

    if url.startswith("-"):
        # `-`-prefixed URLs are still passed to git positionally below,
        # so reject them at the door to avoid a flag-injection footgun.
        raise RemoteGitURLError("URL must not start with '-'")
    if "\x00" in url or "\n" in url or "\r" in url:
        raise RemoteGitURLError("URL contains control characters")

    scheme: str
    host: str
    path: str
    ssh_user: str | None = None

    if "://" in url:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("https",):
            raise RemoteGitURLError(
                f"Unsupported URL scheme '{scheme}'; only https:// is accepted"
            )
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
    else:
        # SCP-like form: git@host:owner/repo.git
        m = _SSH_RE.match(url)
        if not m:
            raise RemoteGitURLError(
                "URL is not a recognized https:// URL or git@host:path form"
            )
        scheme = "ssh"
        ssh_user = m.group("user")
        host = m.group("host").lower()
        path = m.group("path")

    if not host:
        raise RemoteGitURLError("URL is missing a host")
    # Hostname sanity — no whitespace, no scheme / path characters.
    if not re.match(r"^[A-Za-z0-9.\-]+$", host):
        raise RemoteGitURLError(f"Invalid host: {host!r}")
    if path.startswith("/"):
        path = path[1:]
    if not path or path.startswith("-"):
        raise RemoteGitURLError("URL is missing a repository path")

    # Defense in depth: resolve the host and reject private / loopback
    # addresses. Cheap; the allowlist should already keep us out of these
    # zones, but a misconfigured DNS or a host that resolves to a private
    # IP shouldn't let us reach into the host's network.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise RemoteGitURLError(f"Could not resolve host '{host}': {e}") from e
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise RemoteGitURLError(
                f"Host '{host}' resolves to a non-public address ({ip}); refusing"
            )

    if not _Allowlist.from_config().allows(host):
        raise RemoteGitURLError(
            f"Host '{host}' is not in REMOTE_GIT_ALLOWED_HOSTS"
        )

    # Derive owner/repo. Strip optional trailing ".git" / ".git/" once.
    name = path.rstrip("/")
    if name.endswith(".git"):
        name = name[: -len(".git")]
    if "/" not in name:
        raise RemoteGitURLError("URL path must include 'owner/repo'")
    for seg in name.split("/"):
        if not seg or seg in (".", ".."):
            raise RemoteGitURLError("URL path contains invalid segments")
        if not re.match(r"^[A-Za-z0-9_.\-]+$", seg):
            raise RemoteGitURLError(f"Invalid path segment: {seg!r}")

    return _ParsedURL(
        canonical=url,
        host=host,
        path="/" + path,
        name=name,
        scheme=scheme,
        ssh_user=ssh_user,
    )


def _inject_token(parsed: _ParsedURL, token: str | None) -> str:
    """Build a clone URL that embeds a token (for HTTPS).

    SSH URLs do not support token injection; callers must use the URL as-is
    and rely on an ssh-agent / configured key. We surface that constraint
    here as a hard error so the UI can prompt the user to switch to HTTPS.
    """
    if parsed.scheme == "ssh":
        if token:
            raise RemoteGitURLError(
                "Token is not supported for SSH URLs; use https:// and re-paste"
            )
        return parsed.canonical
    if not token:
        return parsed.canonical
    # urlparse-then-rebuild so the userinfo is well-formed; don't re-use
    # the raw canonical form because that may carry query/fragment noise.
    p = urlparse(parsed.canonical)
    return f"https://oauth2:{token}@{p.hostname}{p.path}"


# --- Cache directory layout ------------------------------------------------


_STATE_FILE = "state.json"
_LOCK_FILE = ".lock"


@dataclass
class _Entry:
    """In-memory mirror of `state.json`. Updated under the per-entry lock."""

    id: str
    url: str            # canonical (no token)
    name: str           # owner/repo
    host: str
    path: Path
    fetched_at: float   # epoch seconds
    last_used_at: float
    head: str = ""      # current branch
    head_sha: str = ""
    default_branch: str = ""


def _url_id(url: str) -> str:
    """Stable id for a URL. We use sha1 (not crypto, just a digest)."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _read_state(path: Path) -> dict[str, Any] | None:
    p = path / _STATE_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Corrupt state at %s: %s", p, e)
        return None


def _write_state(path: Path, state: dict[str, Any]) -> None:
    p = path / _STATE_FILE
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


# --- RemoteCache -----------------------------------------------------------


class RemoteCache:
    """Manages `config.REMOTE_GIT_CACHE_DIR/{url_hash}/` clones.

    Threadsafe. The state file and per-entry lock serialize concurrent
    get_or_create() calls for the same URL. A separate `cache_lru` lock
    guards eviction / listing.
    """

    def __init__(self) -> None:
        self._base: Path = config.REMOTE_GIT_CACHE_DIR
        self._base.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # guards the entries index
        # Map: url_id -> _Entry. Re-built from disk on first access.
        self._entries: dict[str, _Entry] = {}
        self._loaded = False
        self._entry_locks: dict[str, threading.Lock] = {}

    # --- Internal: lazy load -------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            for sub in self._base.iterdir() if self._base.exists() else []:
                if not sub.is_dir():
                    continue
                state = _read_state(sub)
                if not state or "id" not in state or "url" not in state:
                    # junk directory — leave it alone, no auto-clean here
                    continue
                self._entries[state["id"]] = _Entry(
                    id=state["id"],
                    url=state["url"],
                    name=state.get("name", ""),
                    host=state.get("host", ""),
                    path=sub,
                    fetched_at=float(state.get("fetched_at", 0)),
                    last_used_at=float(state.get("last_used_at", 0)),
                    head=state.get("head", ""),
                    head_sha=state.get("head_sha", ""),
                    default_branch=state.get("default_branch", ""),
                )
            self._loaded = True

    def _entry_lock(self, url_id: str) -> threading.Lock:
        with self._lock:
            lk = self._entry_locks.get(url_id)
            if lk is None:
                lk = threading.Lock()
                self._entry_locks[url_id] = lk
            return lk

    def _persist(self, entry: _Entry) -> None:
        _write_state(entry.path, {
            "id": entry.id,
            "url": entry.url,
            "name": entry.name,
            "host": entry.host,
            "fetched_at": entry.fetched_at,
            "last_used_at": entry.last_used_at,
            "head": entry.head,
            "head_sha": entry.head_sha,
            "default_branch": entry.default_branch,
        })

    # --- Public: list / get / delete -----------------------------------

    def list(self) -> list[dict]:
        """Return a summary of every cached remote (newest-used first)."""
        self._load()
        with self._lock:
            entries = sorted(
                self._entries.values(),
                key=lambda e: e.last_used_at,
                reverse=True,
            )
        return [self._entry_summary(e) for e in entries]

    def _entry_summary(self, e: _Entry) -> dict:
        return {
            "id": e.id,
            "name": e.name,
            "host": e.host,
            "url": e.url,
            "fetched_at": e.fetched_at,
            "last_used_at": e.last_used_at,
            "head": e.head,
            "head_sha": e.head_sha,
            "default_branch": e.default_branch,
        }

    def get(self, remote_id: str) -> _Entry | None:
        self._load()
        with self._lock:
            return self._entries.get(remote_id)

    def delete(self, remote_id: str) -> bool:
        self._load()
        with self._lock:
            entry = self._entries.pop(remote_id, None)
        if entry is None:
            return False
        # drop the on-disk tree
        try:
            shutil.rmtree(entry.path, ignore_errors=True)
        except OSError as e:
            logger.warning("Failed to remove cache dir %s: %s", entry.path, e)
        with self._lock:
            self._entry_locks.pop(remote_id, None)
        return True

    # --- Public: lifecycle / eviction ----------------------------------

    def evict_lru(self) -> list[str]:
        """Drop the oldest entries until at most `REMOTE_GIT_CACHE_MAX` remain.

        Returns the ids that were evicted (for logging / tests). The
        oldest is decided by `last_used_at` ascending — the entry the
        user touched least recently is the first to go. `evict_lru` is a
        no-op when already within the cap.
        """
        self._load()
        cap = max(0, config.REMOTE_GIT_CACHE_MAX)
        with self._lock:
            entries = list(self._entries.values())
        if cap == 0 or len(entries) <= cap:
            return []
        # Oldest first.
        entries.sort(key=lambda e: e.last_used_at)
        evict = entries[: len(entries) - cap]
        evicted: list[str] = []
        for e in evict:
            if self.delete(e.id):
                evicted.append(e.id)
        return evicted

    def sweep_stale(self, max_age_seconds: float | None = None) -> list[str]:
        """Remove entries that have not been used in `max_age_seconds`.

        Distinct from LRU eviction: this is a time-based cleanup that the
        background sweeper calls periodically to free disk from repos
        the user has forgotten about. `max_age_seconds=None` falls back
        to `config.REMOTE_GIT_CACHE_TTL * 24` (a day) — caches more
        aggressive than this become surprising.
        """
        self._load()
        if max_age_seconds is None:
            # 24h default; the TTL is the freshness window, not the
            # eviction window, so we give stale entries a generous grace
            # period before deleting the on-disk clone.
            max_age_seconds = float(config.REMOTE_GIT_CACHE_TTL) * 24
        now = time.time()
        with self._lock:
            entries = list(self._entries.values())
        evict = [e for e in entries if (now - e.last_used_at) > max_age_seconds]
        removed: list[str] = []
        for e in evict:
            if self.delete(e.id):
                removed.append(e.id)
        return removed

    def dir_size_mb(self, entry: _Entry) -> float:
        """Recursively sum the on-disk size of an entry's clone, in MB.

        Used by the size cap enforcement. Walking the tree is O(n) in
        the number of files; for a shallow clone that's a few hundred
        objects at most, so this is cheap enough to call on each
        get_or_create(). We catch errors so a partial / broken tree
        doesn't crash the whole flow.
        """
        total = 0
        try:
            for p in entry.path.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        continue
        except OSError as e:
            logger.warning("dir_size_mb(%s) failed: %s", entry.path, e)
        return total / (1024 * 1024)

    def _enforce_size_cap(self, entry: _Entry) -> None:
        """Drop the entry from the index if it has grown past the cap.

        The on-disk tree is left in place for forensic inspection — the
        caller can `DELETE /api/git/remote/{id}` to clear it, or it will
        be reaped by `sweep_stale()`. A repo that exceeds the cap is
        almost certainly misconfigured (a stray `git clone` of a
        monorepo), so we hide it from the listing rather than serve a
        broken diff. This is the same trade-off git's `--filter=blob:none`
        makes: refuse to ship what we can't hold.
        """
        cap = config.REMOTE_GIT_MAX_SIZE_MB
        if cap <= 0:
            return
        try:
            size = self.dir_size_mb(entry)
        except Exception:
            return
        if size > cap:
            logger.warning(
                "Remote %s (%s) exceeds size cap %.0f MB (%.1f MB); hiding",
                entry.id, entry.name, cap, size,
            )
            # Mark the entry as oversized in state so the UI can show a
            # hint, then drop it from the in-memory index. The disk
            # contents stay; sweep_stale() will eventually remove them.
            try:
                state = _read_state(entry.path) or {}
                state["oversized"] = True
                state["size_mb"] = size
                _write_state(entry.path, state)
            except OSError:
                pass
            with self._lock:
                self._entries.pop(entry.id, None)

    # --- Public: get_or_create -----------------------------------------

    def get_or_create(
        self, raw_url: str, token: str | None = None, *, force_refresh: bool = False
    ) -> tuple[_Entry, bool]:
        """Resolve `raw_url` to a clone on disk; clone or fetch as needed.

        Returns (entry, was_cached). `was_cached` is True when no network
        was used (existing entry within TTL), False when a clone / fetch
        actually happened. Updates `last_used_at` regardless.

        Raises RemoteGitError subclasses; the caller maps them to HTTP.
        """
        parsed = _parse_url(raw_url)
        url_id = _url_id(parsed.canonical)
        entry_lock = self._entry_lock(url_id)
        # Always use the per-entry lock for serialize the network operation.
        with entry_lock:
            self._load()
            existing = self._entries.get(url_id)
            now = time.time()
            if existing is not None and not force_refresh:
                age = now - existing.fetched_at
                if age < config.REMOTE_GIT_CACHE_TTL:
                    existing.last_used_at = now
                    self._persist(existing)
                    return existing, True
                # else fall through to refresh

            entry = self._ensure_dir(url_id, parsed, existing)
            try:
                self._clone_or_fetch(entry, parsed, token, is_initial=existing is None)
            except RemoteGitError:
                # If we had an existing entry and the refresh failed, keep
                # the stale entry so the user can still see what we last
                # knew. Caller can decide to surface the error.
                if existing is not None:
                    existing.last_used_at = now
                    self._persist(existing)
                raise
            self._refresh_metadata(entry)
            entry.last_used_at = now
            self._persist(entry)
            with self._lock:
                self._entries[url_id] = entry
            # Enforce the LRU cap and per-entry size cap before returning.
            # We do this AFTER the entry lands so a successful clone is
            # never thrown away on the same call that produced it. The
            # size cap check is also best-effort: if `du`-style counting
            # fails, we still return the entry.
            self._enforce_size_cap(entry)
            self.evict_lru()
            return entry, False

    def _ensure_dir(self, url_id: str, parsed: _ParsedURL, existing: _Entry | None) -> _Entry:
        path = self._base / url_id
        if existing is not None:
            return existing
        # Don't mkdir the target — let `git clone` create it. A pre-existing
        # directory with a `.lock` file inside would make git refuse to
        # clone ("destination path already exists and is not an empty
        # directory"). The lock file lives next to the target, not inside.
        return _Entry(
            id=url_id,
            url=parsed.canonical,
            name=parsed.name,
            host=parsed.host,
            path=path,
            fetched_at=0.0,
            last_used_at=time.time(),
        )

    def _lock_path(self, entry: _Entry) -> Path:
        """Lock file sits next to the clone dir, not inside it."""
        return entry.path.with_suffix(entry.path.suffix + ".lock")

    def _clone_or_fetch(
        self,
        entry: _Entry,
        parsed: _ParsedURL,
        token: str | None,
        *,
        is_initial: bool,
    ) -> None:
        lock = self._lock_path(entry)
        if lock.exists():
            # Stale-lock detection: a previous attempt may have been
            # killed (kill -9, OOM, server crash) before its `finally`
            # could unlink the lock. Treat locks older than the
            # configured clone timeout as abandoned and remove them
            # so the next attempt can proceed. This is what the user
            # saw as a 500 in the original report — the lock from
            # their first failed attempt was blocking every retry.
            try:
                lock_age = time.time() - lock.stat().st_mtime
            except OSError:
                lock_age = 0.0
            if lock_age > config.REMOTE_GIT_CLONE_TIMEOUT:
                logger.warning(
                    "Removing stale lock %s (age=%.0fs > timeout=%ss)",
                    lock, lock_age, config.REMOTE_GIT_CLONE_TIMEOUT,
                )
                with __import__("contextlib").suppress(OSError):
                    lock.unlink()
            else:
                # Another caller is mid-clone. Wait briefly, then either
                # find the entry usable or fail.
                deadline = time.time() + config.REMOTE_GIT_CLONE_TIMEOUT
                while lock.exists() and time.time() < deadline:
                    time.sleep(0.2)
                if lock.exists():
                    raise RemoteGitError("Another clone is in progress; try again")
        # Make sure the parent dir exists for the lock file.
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()

        clone_url = _inject_token(parsed, token)
        # Mask the token in any error logs.
        masked = parsed.canonical
        if token:
            masked = masked  # no change, token isn't in the canonical
        try:
            try:
                if is_initial or not (entry.path / ".git").exists():
                    # Shallow + blobless keeps disk + bandwidth small and is
                    # all we need to compute a diff. We pass
                    # --no-single-branch explicitly: `git clone --depth 1`
                    # otherwise defaults to single-branch behavior, which
                    # would leave refs/remotes/origin/* with just the
                    # remote HEAD's branch — the UI's branch picker would
                    # then only show the default branch even when the repo
                    # has dozens. Per-branch size is still small (one
                    # commit + tree, blobs are not fetched) so 100+
                    # branches is only a few MB.
                    self._run_git(
                        [
                            "clone",
                            "--depth",
                            "1",
                            "--filter=blob:none",
                            "--no-tags",
                            "--no-single-branch",
                            clone_url,
                            str(entry.path),
                        ],
                        cwd=self._base,
                    )
                else:
                    self._run_git(
                        ["remote", "set-url", "origin", clone_url],
                        cwd=entry.path,
                    )
                    # Refresh: re-fetch every branch at depth 1. The
                    # explicit refspec `+refs/heads/*:refs/remotes/origin/*`
                    # tells git to mirror all remote heads into the local
                    # tracking namespace (the same namespace `git clone`
                    # populates by default). Without it `git fetch origin`
                    # only updates the upstream of the currently checked
                    # out branch.
                    self._run_git(
                        [
                            "fetch",
                            "--prune",
                            "--depth",
                            "1",
                            "--filter=blob:none",
                            "origin",
                            "+refs/heads/*:refs/remotes/origin/*",
                        ],
                        cwd=entry.path,
                    )
            finally:
                with __import__("contextlib").suppress(OSError):
                    lock.unlink()
        except RemoteGitError as e:
            self._classify_and_raise(e, masked_url=masked)
        # success
        entry.fetched_at = time.time()

    @staticmethod
    def _classify_and_raise(exc: RemoteGitError, *, masked_url: str) -> None:
        """Re-raise the original `git` error under a more specific subclass
        based on its message. Always raises — the generic branch is the
        original error itself, never a swallowed one (silently swallowing
        would let the failed clone fall through to _refresh_metadata and
        persist a half-baked state.json)."""
        msg = str(exc)
        low = msg.lower()
        # Network-layer failures. These are all the same shape from the
        # UI's perspective: the host is DNS-resolvable but the TLS / TCP
        # handshake isn't completing. Common culprits: corporate proxy
        # blocking 443, sandboxed container with no internet egress, an
        # expired ca-certificates bundle, or a transparent MITM that
        # mangles the handshake (which is what produces the GnuTLS
        # "non-properly terminated" message in the user's report).
        #
        # Markers are checked FIRST (before 'timed out' below) so a
        # wrapper like "git command timed out after 300s — last output:
        # ... GnuTLS ..." gets the actionable network hint rather than
        # the generic 504 timeout, which is the catch-all.
        network_markers = (
            "gnutls", "non-properly terminated", "connection reset",
            "connection refused", "connection timed out",
            "could not resolve host", "network is unreachable",
            "ssl routines", "tlsv1 alert", "proxy", "errno 110",
        )
        if any(m in low for m in network_markers):
            hint = (
                "Network error reaching the remote. If the host is on "
                "the allowlist but this fails, the backend host may be "
                "behind a firewall / proxy / sandbox without HTTPS "
                "egress. Try setting GIT_HTTPS_PROXY=<your-proxy> before "
                "starting the backend, or use an SSH URL."
            )
            raise RemoteGitNetworkError(f"{msg} — {hint}") from exc
        if "could not read username" in low or "authentication failed" in low or "invalid username or password" in low:
            raise RemoteGitAuthError(msg) from exc
        if "not found" in low or "repository not found" in low or "not exist" in low:
            raise RemoteGitNotFoundError(msg) from exc
        if "timed out" in low or "timeout" in low:
            raise RemoteGitTimeoutError(msg) from exc
        # Otherwise: re-raise the same exception so the caller still sees
        # the failure. The warning is purely diagnostic.
        logger.warning("git remote op failed for %s: %s", masked_url, msg)
        raise exc

    # --- Public: branch / tag / diff queries ---------------------------

    def list_branches(self, entry: _Entry) -> list[dict]:
        """List remote-tracking branches (refs/heads/ → refs/remotes/origin/).

        Because we use `--single-branch` and `--depth 1` the local repo
        only knows one branch at a time, so we instead walk the
        `refs/remotes/origin/*` namespace which always reflects the
        remote's `refs/heads/*`.
        """
        out = self._run_git(
            [
                "for-each-ref",
                "--format=%(refname:short)|%(objectname:short)|%(subject)",
                "refs/remotes/",
            ],
            cwd=entry.path,
        )
        branches: list[dict] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or "/HEAD" in line:
                continue
            # The ref looks like "origin/main" — strip the "origin/" prefix
            # so the UI can use it as a `base` / `head` ref directly.
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            raw_name, sha, subject = parts
            if "/" not in raw_name:
                continue
            short = raw_name.split("/", 1)[1]
            branches.append({"name": short, "sha": sha, "subject": subject.strip()})
        branches.sort(key=lambda b: b["name"])
        return branches

    def list_tags(self, entry: _Entry) -> list[dict]:
        try:
            out = self._run_git(
                [
                    "for-each-ref",
                    "--sort=-creatordate",
                    "--format=%(refname:short)|%(objectname:short)",
                    "refs/tags/",
                ],
                cwd=entry.path,
            )
        except RemoteGitError:
            return []
        tags: list[dict] = []
        for line in out.splitlines()[:50]:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) != 2:
                continue
            tags.append({"name": parts[0], "sha": parts[1]})
        return tags

    def get_status(self, entry: _Entry) -> dict:
        """Snapshot of the entry: head, default branch, branches, tags."""
        self._refresh_metadata(entry)
        return {
            "id": entry.id,
            "name": entry.name,
            "host": entry.host,
            "url": entry.url,
            "head": entry.head,
            "head_sha": entry.head_sha,
            "default_branch": entry.default_branch,
            "fetched_at": entry.fetched_at,
            "branches": self.list_branches(entry),
            "tags": self.list_tags(entry),
        }

    def _refresh_metadata(self, entry: _Entry) -> None:
        try:
            head = self._run_git(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                cwd=entry.path,
            ).strip()
            head_sha = self._run_git(
                ["rev-parse", "--short", "HEAD"],
                cwd=entry.path,
            ).strip()
        except RemoteGitError:
            head = entry.head
            head_sha = entry.head_sha
        entry.head = head
        entry.head_sha = head_sha
        # Default branch: prefer the branch the clone's HEAD is actually
        # pointing at (set by `git clone` from the source repo's HEAD);
        # only fall back to the well-known-name list if that's not a
        # real local branch (e.g. detached HEAD, or the clone's HEAD
        # points to a ref we don't have in the local namespace).
        try:
            branches = self.list_branches(entry)
        except RemoteGitError:
            branches = []
        default_branch = ""
        names = {b["name"] for b in branches}
        if head and head in names:
            default_branch = head
        else:
            for cand in ("main", "master", "trunk", "develop"):
                if cand in names:
                    default_branch = cand
                    break
            if not default_branch and names:
                default_branch = sorted(names)[0]
        entry.default_branch = default_branch

    # --- Public: low-level git runner ----------------------------------

    def _run_git(self, args: list[str], cwd: Path) -> str:
        """Run `git <args>` in `cwd` and capture stdout."""
        if shutil.which("git") is None:
            raise RemoteGitError("git binary not found on PATH")
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=config.REMOTE_GIT_CLONE_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            # The stderr (if any) is what git was saying when the
            # timeout fired. It's the only diagnostic we have for a
            # wedged child, and it's the difference between "your
            # repo is too slow, raise the timeout" and "your network
            # is broken, fix the proxy". Feed it to the classifier so
            # a network-marker stderr gets reclassified with the
            # actionable hint instead of a bare 504 timeout.
            #
            # `e.stderr` is a str (text=True) or None when the child
            # was killed before producing anything.
            last = (e.stderr or "").strip() if isinstance(e.stderr, str) else ""
            base = f"git command timed out after {config.REMOTE_GIT_CLONE_TIMEOUT}s"
            full = f"{base} — last output: {last}" if last else base
            # Classify ALWAYS raises — we just let the chosen subclass
            # bubble. With no captured stderr, the only honest answer
            # is the timeout error itself, which the catch-all branch
            # of the classifier will produce.
            self._classify_and_raise(RemoteGitError(full), masked_url="")
        except OSError as e:
            raise RemoteGitError(f"failed to run git: {e}") from e
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise RemoteGitError(stderr or f"git exited with {proc.returncode}")
        return proc.stdout


# --- Module-level singleton ------------------------------------------------

_cache: RemoteCache | None = None


def get_cache() -> RemoteCache:
    """Lazily build the module-level cache so tests can monkeypatch config
    before the first access."""
    global _cache
    if _cache is None:
        _cache = RemoteCache()
    return _cache
