# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Note:** The repository root IS the project root — there is no separate compute dir to look in.

## Project: CodeReview

A self-hosted, AI-powered code review tool. Paste a snippet, drop a file, paste
`git diff` output, or compare two git refs; the service streams structured
findings back to the UI in real time. Two review engines share the same finding
schema:

* **Anthropic Claude** — used when `ANTHROPIC_API_KEY` is set.
* **Mock rule engine** — a deterministic, language-aware regex set in
  `backend/reviewer/rules.py`. Lets the UI stay fully functional without an API
  key and is what the test suite runs against.

The full user-facing reference (API, env vars, finding schema, mock rule list,
directory tree) is in `README.md`. This file documents the *architecture and
conventions* that aren't visible from the README alone.

## Quick start

Backend (port 8770):
```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8770
```

Frontend (port 5273, Vite proxies `/api` → :8770 with `strictPort`):
```bash
cd frontend
npm install
npm run dev
# or with a non-default backend:
VITE_API_TARGET=http://localhost:8765 npm run dev
```

Tests:
```bash
# Backend (pytest, currently 130 tests)
cd backend
python3 -m pytest -q                          # everything
python3 -m pytest tests/test_api.py -q         # one file
python3 -m pytest -k "cancel" -q               # by name pattern
python3 -m ruff check .                       # lint

# Frontend (vitest, currently 75 tests; ESLint)
cd ../frontend
npm test                                      # all (vitest run)
npm test -- -t "useReview"                    # by name
npm run lint
npm run build                                 # also validates async code-splitting
```

## Architectural decisions

These are the load-bearing choices that a future change is likely to break if
it doesn't know about them.

### Backend

- **`BackgroundTasks` over `asyncio.create_task`.** The FastAPI `TestClient`
  doesn't schedule bare `create_task` calls, so test runs would hang on `done`.
  `_run_review` is registered via `BackgroundTasks.add_task` and self-registers
  its own `asyncio.Task` handle into `main._tasks` (via
  `asyncio.current_task()` at the top of its body) so `/cancel` can interrupt
  the long `httpx` wait with `task.cancel()`.
- **Per-review `asyncio.Queue` + SSE generator.** Each review has a queue
  registered under its id; `_run_review` writes events with `put_nowait` (drops
  on full to avoid a slow consumer blocking the engine) and the SSE generator
  reads until an internal `_eof` sentinel, then emits a terminal `done` event
  so the client can flip its status to `completed`. The `done` event is
  re-emitted even for already-terminal reviews so a late `EventSource`
  subscription doesn't hang.
- **Streaming JSON peel.** `_peel_complete_findings` runs on every SSE delta
  and pulls out the first complete finding object, so findings appear in the
  UI as the model writes them rather than at the end of the response. The
  buffer has a 1 MB hard cap (`_MAX_STREAM_BUFFER`) — over the cap, an error
  event is yielded and the rest of the stream is dropped.
- **SQLite, single file, sync `sqlite3` wrapped in `asyncio.to_thread`.** A
  module-level `sqlite3.Connection` is reused (no per-request open/close).
  PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `temp_store=MEMORY`. The
  `files` and `total_findings` columns are filled in by an `ALTER TABLE`
  migration in `persistence.init_schema()` so older on-disk DBs upgrade
  in-place.
- **Sliding-window rate limiter (`auth.py` + `rate_limit.py`).** Per caller
  (Bearer token prefix or IP). Lazy-evicts idle keys to keep the dict bounded
  — a one-shot caller that goes silent would otherwise own its deque forever.
  `TokenBucket` was removed; only `SlidingWindowCounter` is in use.
- **Pydantic `Field(description=...)` everywhere.** The OpenAPI page is the
  only API doc.

### Frontend

- **Composables split.** `useReviewSession` owns the SSE stream and finding
  state; `useReviewHistory` owns the sidebar list; `useReview` is the
  orchestrator (active review, files, filters, submit/open/cancel/rerun
  actions). `App.vue` is a thin shell.
- **`useReview` watches `session.status` for terminal transitions** and
  re-fetches the canonical review record via `api.getReview` exactly once
  per `idle → completed/failed` transition. `prevStatus` is seeded from
  `session.status.value` at construction so an HMR remount into an already-
  terminal session doesn't fire a redundant fetch.
- **`useReviewSession.findingKey` for reconnect dedup.** The model doesn't
  assign stable ids, so each finding is keyed by
  `(file_path, line_start, line_end, title, severity, category)`. `detail` /
  `suggestion` are intentionally excluded so a slightly rephrased replay
  isn't dropped as a duplicate.
- **i18n is a hand-rolled `t(key, params)` in `src/i18n/messages.js` —
  vue-i18n is not used.** Two flat string tables (en / zh), `useI18n()` is a
  Vue ref so a locale flip re-renders all consumers immediately. The
  fallback chain is `active locale → zh → en → raw key`, so a partially-
  translated locale never shows a raw key. Default locale is `zh` (browser
  detection + localStorage). Header has an EN / 中 switcher.
- **Severity / category labels go through `severityLabel(s, locale)` /
  `categoryLabel(c, locale)` in `utils/format.js`.** The `best_practice`
  id maps to the i18n key `label.bestPractice` inside `categoryLabel`.
- **`utils/api.js:request` always combines `AbortSignal.timeout(30_000)` with
  any caller signal.** No caller has to remember to add the timeout.
- **`RefPicker` is `defineAsyncComponent` lazy-loaded** in `InputPanel.vue`
  because it's only used in git mode, which itself only renders when
  `REPO_PATH` is set on the backend.
- **Remote Git cache (`backend/git_remote.py`).** A second, independent
  Git workflow that lets the user paste any `https://…` / `git@host:…`
  URL. Clones are cached at `REMOTE_GIT_CACHE_DIR/{sha1(url)[:12]}/`
  with `--depth 1 --filter=blob:none --no-tags --single-branch` for
  speed. All four `/api/git/remote/*` endpoints sit behind
  `auth.require_api_key`; the URL is validated against a host
  allowlist (default: GitHub / GitLab / Bitbucket / Gitea / Gitee /
  Codeberg / SourceHut) with a post-resolution private-IP check as
  defense-in-depth against SSRF. The token is injected into the clone
  URL as `https://oauth2:{token}@…` and never persisted. TTL-based
  refresh + LRU eviction are enforced inside `get_or_create`; a
  background `_remote_sweep_loop` runs every 5 min from the FastAPI
  lifespan to drop stale entries and shrink the on-disk cache. The
  `Review.source` column (added via `ALTER TABLE` migration in
  `init_schema()`) tags each review as `local`, `remote:<name>`, or
  `null` (legacy rows); the frontend `HistoryList` renders a small
  badge per source.

## Conventions / things to know

- **Mock engine output.** No API key → mock engine runs. Findings come from
  pre-compiled regexes in `backend/reviewer/rules.py` (eval, exec, subprocess
  shell=True, pickle, mutable default args, hardcoded secrets, etc.). The
  model field on the persisted row still says the configured
  `claude-sonnet-4-6`; the engine switch is signalled via the `/api/health`
  `ai_provider` field and the UI's "Mock review engine" badge.
- **SSE event contract.** The client treats `done` as "status is final, close
  the EventSource". `_eof` is an internal-only sentinel the SSE generator
  uses to break out of its read loop. Terminal reviews that are fetched
  fresh still emit a synthetic `done` after `status`, so a re-attached
  consumer doesn't sit on `streaming` forever.
- **`Cancellation` plumbing.** `/api/reviews/{id}/cancel` adds the id to
  `main._cancelled` (a `set[str]`) and, if the background task is already
  registered in `main._tasks`, calls `task.cancel()`. Both registries are
  popped in `_run_review`'s outer `finally`. `asyncio.CancelledError` is
  re-raised so it doesn't get logged as a generic failure.
- **CORS default is `http://localhost:5273,http://127.0.0.1:5273`** (the
  Vite dev port, not the more common 5173). Empty
  `CORS_ALLOW_ORIGINS=""` falls back to the default + logs a warning, rather
  than bricking startup.
- **Review IDs are 16 hex chars** (`uuid.uuid4().hex[:16]`), configurable via
  `REVIEW_ID_LENGTH`.
- **Tailwind v4** uses the `@import "tailwindcss"` syntax — no v3
  `@tailwind base;` directives anywhere.
- **No Cursor rules or Copilot instructions** in this repo.
- The user typically writes in Chinese; mirror their language in replies.