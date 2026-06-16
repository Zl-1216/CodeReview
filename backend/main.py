"""FastAPI app for the CodeReview service.

Routes:
  POST   /api/review             Submit a review (runs in background; returns id)
  GET    /api/reviews            List past reviews
  GET    /api/reviews/{id}       Fetch a single review with findings
  DELETE /api/reviews/{id}       Delete a review
  GET    /api/reviews/{id}/events  SSE stream of review progress
  GET    /api/health             Liveness probe
  GET    /api/config             Public config (AI enabled, default model, etc.)
  POST   /api/git/remote/clone   Clone / fetch a user-supplied remote repo
  GET    /api/git/remote         List cached remote repos
  GET    /api/git/remote/{id}    Query a cached remote's head / branches / tags
  POST   /api/git/remote/{id}/diff  Compute a diff for two refs on a remote
  DELETE /api/git/remote/{id}    Drop a cached remote from disk
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import auth
import config
import git_diff
import persistence
from diff_parser import _infer_language
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import (
    CodeFile,
    Review,
    ReviewListResponse,
    ReviewRequest,
)
from pydantic import BaseModel
from reviewer import run_review
from sse_starlette.sse import EventSourceResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# --- Per-review event queues ----------------------------------------------
# A separate asyncio.Queue for each in-flight review. We hold at most one
# queue per review id; once consumed it is removed. Background tasks
# themselves are managed by FastAPI's BackgroundTasks machinery, so we
# don't keep references to them here.
_event_queues: dict[str, asyncio.Queue] = {}


# --- Lifespan --------------------------------------------------------------

async def _remote_sweep_loop() -> None:
    """Background sweeper for the remote-git cache.

    Every `interval_s` seconds, run the time-based cleanup and the LRU
    cap enforcement. We do this in a daemon task (not a lifespan-scoped
    timer) so the event loop keeps running; cancelling on shutdown is
    handled by the `try/finally` in `lifespan` setting `_sweep_stop`.
    """
    interval_s = 300.0  # 5 min
    while not _sweep_stop.is_set():
        try:
            cache = git_remote.get_cache()
            removed = cache.sweep_stale()
            evicted = cache.evict_lru()
            if removed or evicted:
                logger.info(
                    "Remote cache sweep: removed=%s evicted=%s",
                    removed, evicted,
                )
        except Exception:
            logger.exception("Remote cache sweep failed")
        try:
            await asyncio.wait_for(_sweep_stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            continue


_sweep_stop = asyncio.Event()
_sweep_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    persistence.init_schema()
    logger.info("Code review service started; AI provider: %s", _ai_label())
    global _sweep_task
    if config.REVIEW_GIT_REMOTE_ENABLED:
        _sweep_stop.clear()
        _sweep_task = asyncio.create_task(_remote_sweep_loop())
    try:
        yield
    finally:
        _event_queues.clear()
        _tasks.clear()
        if _sweep_task is not None:
            _sweep_stop.set()
            _sweep_task.cancel()
            try:
                await _sweep_task
            except (asyncio.CancelledError, Exception):
                pass
            _sweep_task = None
        logger.info("Code review service stopped")


def _ai_label() -> str:
    if config.ANTHROPIC_API_KEY:
        return f"anthropic/{config.ANTHROPIC_MODEL}"
    return "mock (no ANTHROPIC_API_KEY)"


# --- App -------------------------------------------------------------------

app = FastAPI(title="CodeReview", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health & config -------------------------------------------------------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "time": datetime.now().isoformat(timespec="seconds"),
        "ai_provider": _ai_label(),
    }


@app.get("/api/config")
async def public_config():
    return {
        "ai_enabled": bool(config.ANTHROPIC_API_KEY),
        "default_model": config.ANTHROPIC_MODEL,
        "focuses": config.REVIEW_FOCUSES,
        "max_files": config.MAX_FILES_PER_REVIEW,
        "max_file_bytes": config.MAX_FILE_BYTES,
        "remote_git_enabled": bool(config.REVIEW_GIT_REMOTE_ENABLED),
        # True iff the server is configured with REVIEW_API_KEY. When
        # true, every write endpoint (review, upload, cancel, rerun,
        # the new /api/git/remote/* set) requires a Bearer token; the
        # frontend surfaces an input for the user to enter it and
        # persists it in localStorage.
        "requires_api_key": bool(config.REVIEW_API_KEY),
    }


# --- Remote git integration -----------------------------------------------
# A second, independent git workflow: the user pastes an https://... or
# git@host:owner/repo.git URL, the server clones it into
# REVIEW_DATA_DIR/remotes/{url_hash}/, and the same diff/parse path used
# for REPO_PATH is reused against that working tree. All endpoints below
# require REVIEW_API_KEY (consistent with the user's chosen design) — no
# anonymous cloning of arbitrary URLs. Set REVIEW_GIT_REMOTE_ENABLED=false
# to turn the whole feature off (the UI then hides the Remote tab).

import git_remote  # imported lazily so a missing file doesn't break unrelated tests


def _remote_feature_gate() -> None:
    """Raise 404 when the feature is disabled. Keeps a clean API surface."""
    if not config.REVIEW_GIT_REMOTE_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Remote git integration is disabled (REVIEW_GIT_REMOTE_ENABLED)",
        )


class _RemoteCloneRequest(BaseModel):
    url: str
    token: str | None = None
    refresh: bool = False


class _RemoteStatusResponse(BaseModel):
    id: str
    name: str
    host: str
    url: str
    head: str
    head_sha: str
    default_branch: str
    fetched_at: float
    branches: list[dict]
    tags: list[dict]


class _RemoteRemoteDiffRequest(BaseModel):
    base: str
    head: str
    path: str | None = None


def _remote_to_response(entry, status: dict) -> _RemoteStatusResponse:
    return _RemoteStatusResponse(
        id=entry.id,
        name=entry.name,
        host=entry.host,
        url=entry.url,
        head=status["head"],
        head_sha=status["head_sha"],
        default_branch=status["default_branch"],
        fetched_at=entry.fetched_at,
        branches=status["branches"],
        tags=status["tags"],
    )


def _map_remote_error(e: git_remote.RemoteGitError) -> HTTPException:
    """Map a RemoteGitError subclass to the right HTTP status."""
    if isinstance(e, git_remote.RemoteGitURLError):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, git_remote.RemoteGitAuthError):
        return HTTPException(status_code=401, detail=str(e))
    if isinstance(e, git_remote.RemoteGitNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, git_remote.RemoteGitTimeoutError):
        return HTTPException(status_code=504, detail=str(e))
    if isinstance(e, git_remote.RemoteGitNetworkError):
        # Network / TLS / proxy problems: upstream connectivity, not a
        # logical error in our request. The frontend surfaces a hint
        # about proxy / firewall.
        return HTTPException(status_code=502, detail=str(e))
    return HTTPException(status_code=502, detail=str(e))


@app.post(
    "/api/git/remote/clone",
    response_model=_RemoteStatusResponse,
    dependencies=[Depends(auth.require_api_key), Depends(auth.enforce_rate_limit)],
)
async def git_remote_clone(req: _RemoteCloneRequest):
    """Clone (or refresh) a user-supplied remote repo and return its status."""
    _remote_feature_gate()
    cache = git_remote.get_cache()
    try:
        entry, was_cached = cache.get_or_create(
            req.url, token=req.token, force_refresh=req.refresh
        )
    except git_remote.RemoteGitError as e:
        raise _map_remote_error(e) from e
    except Exception:
        # Any non-RemoteGitError exception (e.g. PermissionError on
        # the cache dir, OSError on a full disk) is logged with full
        # traceback and surfaced as a 502 with a generic message —
        # the alternative is FastAPI's default 500 page which gives
        # the user no actionable hint.
        logger.exception("Unexpected error in git_remote_clone")
        raise HTTPException(
            status_code=502,
            detail="Internal error during clone — check the backend logs.",
        ) from None
    status = cache.get_status(entry)
    return _remote_to_response(entry, status)


@app.get(
    "/api/git/remote",
    dependencies=[Depends(auth.require_api_key)],
)
async def git_remote_list():
    """List every cached remote (newest-used first)."""
    _remote_feature_gate()
    cache = git_remote.get_cache()
    return {"remotes": cache.list()}


@app.get(
    "/api/git/remote/{remote_id}",
    response_model=_RemoteStatusResponse,
    dependencies=[Depends(auth.require_api_key)],
)
async def git_remote_status(remote_id: str):
    """Return the current status (head, branches, tags) of a cached remote."""
    _remote_feature_gate()
    cache = git_remote.get_cache()
    entry = cache.get(remote_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Remote not found")
    try:
        status = cache.get_status(entry)
    except git_remote.RemoteGitError as e:
        raise _map_remote_error(e) from e
    except Exception:
        logger.exception("Unexpected error in git_remote_status(%s)", remote_id)
        raise HTTPException(
            status_code=502,
            detail="Internal error fetching remote status — check the backend logs.",
        ) from None
    return _remote_to_response(entry, status)


class _RemoteDiffResponse(BaseModel):
    base: str
    head: str
    path: str | None = None
    stat: str
    files: list[CodeFile]
    raw: str
    binary_skipped: int = 0
    truncated: bool = False


@app.post(
    "/api/git/remote/{remote_id}/diff",
    response_model=_RemoteDiffResponse,
    dependencies=[Depends(auth.require_api_key), Depends(auth.enforce_rate_limit)],
)
async def git_remote_diff(remote_id: str, req: _RemoteRemoteDiffRequest):
    """Compute a diff for two refs on a previously-cloned remote repo."""
    _remote_feature_gate()
    cache = git_remote.get_cache()
    entry = cache.get(remote_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Remote not found; please reconnect")
    try:
        # refs_prefix="origin/" because the remote cache's working tree
        # only has refs/remotes/origin/* (no local branches), and the
        # UI's RefPicker sends short names like `main` or
        # `feature/remote-git`. The local-git path (REPO_PATH) doesn't
        # need this — its working tree has real local branches.
        #
        # use_three_dot=False because the remote cache is a depth=1
        # shallow clone — the merge-base commit is typically NOT in
        # the local history, so the three-dot form would fail with
        # "no merge base". Two-dot compares the two tips directly,
        # which is what the code-review use case actually wants.
        result = git_diff.diff_refs(
            req.base, req.head, req.path,
            cwd=entry.path,
            refs_prefix="origin/",
            use_three_dot=False,
        )
    except git_diff.GitError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _RemoteDiffResponse(**result)


@app.delete(
    "/api/git/remote/{remote_id}",
    dependencies=[Depends(auth.require_api_key)],
)
async def git_remote_delete(remote_id: str):
    """Drop a cached remote repo from disk."""
    _remote_feature_gate()
    cache = git_remote.get_cache()
    if not cache.delete(remote_id):
        raise HTTPException(status_code=404, detail="Remote not found")
    return {"ok": True}


# --- Review submission -----------------------------------------------------

@app.post("/api/review", dependencies=[Depends(auth.require_api_key), Depends(auth.enforce_rate_limit)])
async def submit_review(req: ReviewRequest, background: BackgroundTasks):
    if not req.files:
        raise HTTPException(status_code=400, detail="No files supplied")
    if len(req.files) > config.MAX_FILES_PER_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files ({len(req.files)} > {config.MAX_FILES_PER_REVIEW})",
        )
    for f in req.files:
        if len(f.content.encode("utf-8")) > config.MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File '{f.path}' exceeds {config.MAX_FILE_BYTES} bytes",
            )

    review = Review(
        id=uuid.uuid4().hex[: config.REVIEW_ID_LENGTH],
        created_at=datetime.now(),
        title=req.title or _default_title(req.files),
        description=req.description,
        file_count=len(req.files),
        focuses=req.focuses,
        model=req.model or config.ANTHROPIC_MODEL,
        status="pending",
        files=req.files,
        source=req.source,
    )
    await persistence.aupsert(review)

    queue: asyncio.Queue = asyncio.Queue(maxsize=128)
    _event_queues[review.id] = queue
    # BackgroundTasks is what runs the function under the FastAPI
    # TestClient (asyncio.create_task is *not* scheduled there). The
    # function self-registers its current task in `_tasks` at the top
    # of its body so /cancel can interrupt the long httpx wait via
    # task.cancel().
    background.add_task(_run_review, review, req.files, queue)

    return {"id": review.id, "status": review.status}


def _default_title(files: list[CodeFile]) -> str:
    if not files:
        return "Untitled review"
    if len(files) == 1:
        return files[0].path
    return f"{files[0].path} (+{len(files) - 1} more)"


async def _run_review(review: Review, files: list[CodeFile], queue: asyncio.Queue) -> None:
    """Background task: run the review, persist state, fan out events."""
    # Self-register the running task so /cancel can interrupt the long
    # httpx wait inside run_review() via task.cancel(). BackgroundTasks
    # doesn't expose its own handle, so we grab the current one. The
    # cancel endpoint polls briefly for it to appear.
    current = asyncio.current_task()
    if current is not None:
        _tasks[review.id] = current
    started = time.monotonic()
    # Accumulate findings in a local list and only commit them to the
    # `review` object once at the end. This keeps the persisted row from
    # being mutated concurrently with `aupsert` calls and avoids the
    # "extend-during-write" race.
    findings: list = []
    summary = None
    error: str | None = None

    def _emit(event: str, data) -> None:
        """Non-blocking queue put; drops on full or cancelled.

        `put_nowait` instead of `put` so a missing SSE consumer never
        blocks the engine. The terminal `done` event is the only one
        the consumer cannot reconstruct itself, so we still try
        `put_nowait` for it — and fall back to a no-op if the queue
        is full. The `_cancelled` short-circuit stops further events
        the moment /cancel lands.
        """
        if review.id in _cancelled:
            return
        try:
            queue.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:
            # Consumer is gone or slow. Drop the event; the terminal
            # `done` is the one event that MUST be seen, and we retry
            # it via _finalize below.
            if event == "done":
                # The consumer will see the persisted state on its
                # next reconnect via GET /api/reviews/{id}.
                logger.warning("Dropped done event for review %s (queue full)", review.id)

    async def _finalize() -> None:
        """Persist the terminal state of a review.

        Sets status to 'failed' (with `error`) or 'completed', writes
        duration_ms, and aupserts. Wrapped in its own try so a persist
        failure here doesn't bubble up and prevent the terminal
        `done` event from being emitted.
        """
        nonlocal error
        review.findings = findings
        review.summary = summary
        review.duration_ms = int((time.monotonic() - started) * 1000)
        if error:
            review.status = "failed"
            review.error = error
        else:
            review.status = "completed"
        try:
            await persistence.aupsert(review)
        except Exception:
            logger.exception("Review %s final persist failed", review.id)

    try:
        try:
            review.status = "streaming"
            await persistence.aupsert(review)
            _emit("status", {"status": "streaming"})

            # Fill in language if missing
            for f in files:
                if not f.language:
                    f.language = _infer_language(f.path)

            try:
                async for event in run_review(review, files):
                    if review.id in _cancelled:
                        error = "cancelled"
                        break
                    if event.error:
                        error = event.error
                        break
                    if event.findings:
                        findings.extend(event.findings)
                        _emit("findings", [f.model_dump() for f in event.findings])
                    if event.summary:
                        summary = event.summary
                        _emit("summary", event.summary.model_dump())
            except asyncio.CancelledError:
                # task.cancel() arrived (e.g. /cancel). The engine's
                # httpx wait was interrupted; stop emitting and let
                # the finally block run.
                error = "cancelled"
                raise
            except Exception as exc:
                logger.exception("Review %s failed", review.id)
                error = str(exc)

            await _finalize()
        except asyncio.CancelledError:
            # Task cancellation should not be logged as a failure — let
            # it propagate to the caller / event loop.
            raise
        except Exception as exc:
            # Setup or final aupsert threw (e.g. DB locked at startup).
            # Make sure we still record a failure and unblock the consumer.
            logger.exception("Review %s setup failed", review.id)
            if not error:
                error = str(exc)
            await _finalize()
        finally:
            # Always emit a terminal `done` + `_eof` so the SSE consumer
            # never hangs waiting for messages that will never arrive.
            # Use a one-shot blocking put (with the standard 128-slot
            # buffer, this only blocks if the consumer has gone away
            # for many seconds — in which case task.cancel() is the
            # right escape hatch anyway).
            try:
                queue.put_nowait({
                    "event": "done",
                    "data": {
                        "status": review.status,
                        "error": error,
                        "duration_ms": review.duration_ms,
                    },
                })
            except Exception:
                logger.exception("Review %s done-event put failed", review.id)
            try:
                queue.put_nowait({"event": "_eof", "data": None})
            except Exception:
                logger.exception("Review %s eof-event put failed", review.id)
    finally:
        # Drop the per-review queue from the module-level registry so it
        # can be garbage-collected. The consumer's local reference is
        # unaffected — it will break out on _eof and the dict entry is
        # just bookkeeping.
        _event_queues.pop(review.id, None)
        _cancelled.discard(review.id)
        _tasks.pop(review.id, None)


# --- Streaming (SSE) -------------------------------------------------------

@app.get("/api/reviews/{review_id}/events")
async def review_events(review_id: str):
    review = await persistence.aget(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    queue = _event_queues.get(review_id)

    async def event_gen() -> AsyncIterator[dict]:
        # If the review is already terminal, emit a status + the synthetic
        # `done` event so the front-end's useReviewSession can null out
        # the EventSource. Without the done event, the live session would
        # never flip out of 'streaming' and the EventSource would leak
        # until the server-side stream closes.
        if queue is None or review.status in ("completed", "failed"):
            yield {
                "event": "status",
                "data": json.dumps({"status": review.status, "error": review.error}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "status": review.status,
                    "error": review.error,
                    "duration_ms": review.duration_ms,
                }),
            }
            return

        # emit current findings so a late subscriber gets the snapshot
        if review.findings:
            yield {
                "event": "findings",
                "data": json.dumps([f.model_dump() for f in review.findings]),
            }

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                # heartbeat — keeps the connection open through proxies
                yield {"event": "ping", "data": ""}
                continue
            if msg.get("event") == "_eof":
                break
            payload = msg.get("data")
            yield {
                "event": msg["event"],
                "data": payload if isinstance(payload, str) else json.dumps(payload),
            }

    return EventSourceResponse(event_gen())


# --- Review CRUD -----------------------------------------------------------

@app.get("/api/reviews", response_model=ReviewListResponse)
async def list_reviews(limit: int = 50, offset: int = 0):
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    items, total = await persistence.alist_recent(limit=limit, offset=offset)
    return ReviewListResponse(items=items, total=total)


@app.get("/api/reviews/{review_id}", response_model=Review)
async def get_review(review_id: str):
    review = await persistence.aget(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@app.delete("/api/reviews/{review_id}")
async def delete_review(review_id: str):
    if not await persistence.adelete(review_id):
        raise HTTPException(status_code=404, detail="Review not found")
    return {"ok": True}


# Reviews that have been cancelled mid-flight. The background task checks
# this set; if its id is present it stops emitting events and writes a
# 'failed' / cancelled terminal status. The set is consulted in O(1) and
# grows at most by the number of in-flight cancellations.
_cancelled: set[str] = set()

# Background tasks by review id, kept so /cancel can interrupt a long-
# running httpx wait via task.cancel(). _run_review removes its own entry
# in its outer finally; we never leave a finished task in the registry.
_tasks: dict[str, asyncio.Task] = {}


@app.post("/api/reviews/{review_id}/cancel", dependencies=[Depends(auth.require_api_key)])
async def cancel_review(review_id: str):
    review = await persistence.aget(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status in ("completed", "failed"):
        return {"ok": True, "already_terminal": True}
    # _run_review self-registers when it starts. There's a small race
    # where /cancel lands between BackgroundTasks.add_task and the
    # first await inside _run_review — wait briefly for the task to
    # appear. If it never does (queue drained, task about to finish),
    # fall back to the set-based check.
    task = _tasks.get(review_id)
    for _ in range(20):  # up to ~100ms
        if task is not None or review_id not in _event_queues:
            break
        await asyncio.sleep(0.005)
        task = _tasks.get(review_id)
    if task is not None and not task.done():
        _cancelled.add(review_id)
        task.cancel()
    elif review_id in _event_queues:
        # Task is between events (or hasn't started yet). The set is
        # still useful: the next between-event check in _run_review
        # will pick it up.
        _cancelled.add(review_id)
    return {"ok": True}


@app.post("/api/reviews/{review_id}/rerun", response_model=dict, dependencies=[Depends(auth.require_api_key), Depends(auth.enforce_rate_limit)])
async def rerun_review(review_id: str, background: BackgroundTasks):
    """Re-submit a past review with the same files / focuses / model.

    The original review row is left untouched; a new id is returned and
    streamed via /events as usual.
    """
    review = await persistence.aget(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if not review.files:
        raise HTTPException(
            status_code=400,
            detail="Original review has no files stored; cannot rerun",
        )
    new_review = Review(
        id=uuid.uuid4().hex[: config.REVIEW_ID_LENGTH],
        created_at=datetime.now(),
        title=review.title,
        description=review.description,
        file_count=review.file_count,
        focuses=review.focuses,
        model=review.model,
        status="pending",
        files=review.files,
    )
    await persistence.aupsert(new_review)
    queue: asyncio.Queue = asyncio.Queue(maxsize=128)
    _event_queues[new_review.id] = queue
    background.add_task(_run_review, new_review, review.files, queue)
    return {"id": new_review.id, "status": new_review.status}


# --- Entrypoint ------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
