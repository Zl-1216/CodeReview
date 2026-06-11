"""SQLite persistence for review history.

The synchronous functions are the implementation; the async wrappers run
them in a worker thread so they do not block the event loop when called
from async routes. The sync versions are still used at startup
(`init_schema`) and from tests.

Connections are thread-local and reused: opening a SQLite connection is
cheap-ish but not free, and the per-thread `connect/close` we used to do
on every call adds up. A connection is reopened automatically if the
configured `DB_PATH` changes (e.g. between tests).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime

import config
from models import CodeFile, Review, ReviewFinding, ReviewListItem, ReviewSummary

logger = logging.getLogger(__name__)

# PRAGMAs applied to every connection. WAL allows concurrent readers +
# a single writer; synchronous=NORMAL is the recommended trade-off for
# WAL mode (the WAL file is fsync'd, not the main DB on every commit);
# temp_store=MEMORY keeps intermediate aggregates out of the on-disk
# temp file. These are safe to set per-connection.
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA foreign_keys=ON",
)

_tls = threading.local()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Yield a thread-local SQLite connection, reopening on path change.

    `sqlite3.connect` defaults to `check_same_thread=True`, but a connection
    is only ever used by the thread that opened it. We hand the same
    connection to every call on the same thread, so callers see a stable
    in-process handle.
    """
    conn = getattr(_tls, "conn", None)
    path = str(getattr(config, "DB_PATH", "") or "")
    if conn is None or getattr(_tls, "path", None) != path:
        if conn is not None:
            with suppress(Exception):
                conn.close()
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        _tls.conn = conn
        _tls.path = path
    try:
        yield conn
        conn.commit()
    except Exception:
        with suppress(Exception):
            conn.rollback()
        raise


def _close_thread_conn() -> None:
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        with suppress(Exception):
            conn.close()
    _tls.conn = None
    _tls.path = None


def init_schema() -> None:
    """Create tables. Idempotent."""
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                file_count INTEGER NOT NULL,
                focuses TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                findings TEXT NOT NULL DEFAULT '[]',
                total_findings INTEGER NOT NULL DEFAULT 0,
                summary TEXT,
                error TEXT,
                duration_ms INTEGER,
                files TEXT NOT NULL DEFAULT '[]',
                source TEXT
            )
            """
        )
        # Older installs may not have the files / total_findings / source
        # columns. Add them if missing so historical DBs stay
        # forward-compatible.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        if "files" not in cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN files TEXT NOT NULL DEFAULT '[]'")
        if "total_findings" not in cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN total_findings INTEGER NOT NULL DEFAULT 0")
            # Backfill from existing rows so the column is immediately useful.
            conn.execute(
                """
                UPDATE reviews
                SET total_findings = (
                    SELECT COALESCE(json_array_length(findings), 0) FROM reviews r2 WHERE r2.id = reviews.id
                )
                """
            )
        if "source" not in cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN source TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at DESC)"
        )


def upsert(review: Review) -> None:
    """Insert or update a review. Always rewrites findings + summary to keep
    the row authoritative for its current state. `total_findings` is
    denormalized into its own column so the history list can show the
    count without parsing the findings JSON."""
    findings_dump = [f.model_dump() for f in review.findings]
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO reviews (id, created_at, title, description, file_count,
                focuses, model, status, findings, total_findings, summary, error,
                duration_ms, files, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                findings = excluded.findings,
                total_findings = excluded.total_findings,
                summary = excluded.summary,
                error = excluded.error,
                duration_ms = excluded.duration_ms,
                files = excluded.files,
                source = excluded.source
            """,
            (
                review.id,
                review.created_at.isoformat(),
                review.title,
                review.description,
                review.file_count,
                json.dumps(review.focuses),
                review.model,
                review.status,
                json.dumps(findings_dump),
                len(findings_dump),
                json.dumps(review.summary.model_dump()) if review.summary else None,
                review.error,
                review.duration_ms,
                json.dumps([f.model_dump() for f in review.files]),
                review.source,
            ),
        )


def get(review_id: str) -> Review | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        return None
    return _row_to_review(row)


def list_recent(limit: int = 50, offset: int = 0) -> tuple[list[ReviewListItem], int]:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]
        rows = conn.execute(
            """
            SELECT id, created_at, title, file_count, focuses, model, status,
                   total_findings, duration_ms, source
            FROM reviews
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    items = [_row_to_list_item(r) for r in rows]
    return items, total


def delete(review_id: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    return cur.rowcount > 0


def _row_to_review(row: sqlite3.Row) -> Review:
    findings_raw = json.loads(row["findings"] or "[]")
    findings = [ReviewFinding(**f) for f in findings_raw]
    summary = None
    if row["summary"]:
        summary = ReviewSummary(**json.loads(row["summary"]))
    focuses = json.loads(row["focuses"] or "[]")
    files_raw = json.loads(row["files"] or "[]")
    files = [CodeFile(**f) for f in files_raw]
    # `source` is nullable: legacy rows have it as None, REPO_PATH-backed
    # reviews set it to "local", remote ones to "remote:<name>".
    try:
        source = row["source"]
    except (IndexError, KeyError):
        source = None
    return Review(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        title=row["title"],
        description=row["description"],
        file_count=row["file_count"],
        focuses=focuses,
        model=row["model"],
        findings=findings,
        summary=summary,
        status=row["status"],
        error=row["error"],
        duration_ms=row["duration_ms"],
        files=files,
        source=source,
    )


def _row_to_list_item(row: sqlite3.Row) -> ReviewListItem:
    focuses = json.loads(row["focuses"] or "[]")
    # `source` was added in a later schema revision; older SELECTs (and
    # older in-memory rows) won't have the key.
    try:
        source = row["source"]
    except (IndexError, KeyError):
        source = None
    return ReviewListItem(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        title=row["title"],
        file_count=row["file_count"],
        focuses=focuses,
        model=row["model"],
        status=row["status"],
        total_findings=row["total_findings"] or 0,
        duration_ms=row["duration_ms"],
        source=source,
    )


# --- Async wrappers ---------------------------------------------------------
# These are what async routes / background tasks should call. Each delegates
# to the corresponding sync function in the default thread pool so the
# SQLite call does not block the event loop.

async def aupsert(review: Review) -> None:
    await asyncio.to_thread(upsert, review)


async def aget(review_id: str) -> Review | None:
    return await asyncio.to_thread(get, review_id)


async def alist_recent(limit: int = 50, offset: int = 0) -> tuple[list[ReviewListItem], int]:
    return await asyncio.to_thread(list_recent, limit, offset)


async def adelete(review_id: str) -> bool:
    return await asyncio.to_thread(delete, review_id)
