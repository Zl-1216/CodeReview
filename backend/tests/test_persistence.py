"""Tests for persistence.py — schema migrations, PRAGMAs, and the
denormalized `total_findings` column that powers the history list."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import persistence
from models import CodeFile, Review, ReviewFinding, ReviewSummary


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "r.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    # Force any thread-local connection to reopen against the new path.
    persistence._close_thread_conn()
    persistence.init_schema()
    return db


def _review(
    rid: str = "abc123",
    *,
    findings: list[ReviewFinding] | None = None,
    status: str = "completed",
    summary: ReviewSummary | None = None,
) -> Review:
    return Review(
        id=rid,
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        title="t",
        description=None,
        file_count=1,
        focuses=["bug"],
        model="claude-sonnet-4-6",
        status=status,
        findings=findings or [],
        summary=summary,
        files=[CodeFile(path="a.py", content="pass")],
    )


# --- Schema & PRAGMAs ------------------------------------------------------

def test_init_schema_creates_total_findings_column(fresh_db):
    with persistence._conn() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    assert "total_findings" in cols


def test_init_schema_sets_wal_journal_mode(fresh_db):
    with persistence._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_init_schema_idempotent(fresh_db):
    # Running init_schema twice should not raise. CREATE TABLE IF NOT EXISTS
    # and the ALTER guards make this safe.
    persistence.init_schema()
    persistence.init_schema()
    with persistence._conn() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    assert "total_findings" in cols


def test_init_schema_migrates_existing_db_without_total_findings(fresh_db):
    """An older DB created before this column existed should pick it up on
    next `init_schema` and backfill from the existing findings JSON."""
    with persistence._conn() as conn:
        # Simulate an older DB: drop the column (it has a default 0 anyway) and
        # insert a row whose findings JSON length is non-zero so we can check
        # the backfill runs.
        conn.execute("ALTER TABLE reviews DROP COLUMN total_findings")
        conn.execute(
            "INSERT INTO reviews (id, created_at, title, file_count, focuses, model, status, findings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "old1",
                "2026-06-08T10:00:00",
                "old",
                1,
                "[]",
                "m",
                "completed",
                json.dumps([{"file_path": "a.py", "severity": "high", "category": "bug",
                             "title": "t", "detail": "d"},
                            {"file_path": "b.py", "severity": "low", "category": "style",
                             "title": "t2", "detail": "d2"}]),
            ),
        )

    persistence._close_thread_conn()
    persistence.init_schema()

    with persistence._conn() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        assert "total_findings" in cols
        row = conn.execute("SELECT total_findings FROM reviews WHERE id = 'old1'").fetchone()
    assert row["total_findings"] == 2


# --- total_findings denormalization ---------------------------------------

def test_upsert_writes_total_findings(fresh_db):
    findings = [
        ReviewFinding(
            file_path="a.py", line_start=1, line_end=1,
            severity="high", category="bug", title="t1", detail="d",
        ),
        ReviewFinding(
            file_path="a.py", line_start=2, line_end=2,
            severity="low", category="style", title="t2", detail="d2",
        ),
    ]
    persistence.upsert(_review("r1", findings=findings))

    with persistence._conn() as conn:
        row = conn.execute("SELECT total_findings FROM reviews WHERE id = 'r1'").fetchone()
    assert row["total_findings"] == 2


def test_list_recent_uses_total_findings_column(fresh_db, monkeypatch):
    """`list_recent` should read `total_findings` from the column, not parse
    the findings JSON every time."""
    findings = [
        ReviewFinding(
            file_path="a.py", severity="high", category="bug", title="t1", detail="d",
        )
    ]
    persistence.upsert(_review("r1", findings=findings))

    # Replace the findings column with non-JSON garbage. If list_recent
    # parses findings, this will raise. Reading from the column will not.
    with persistence._conn() as conn:
        conn.execute("UPDATE reviews SET findings = ? WHERE id = 'r1'", ("not-json",))

    items, total = persistence.list_recent()
    assert total == 1
    assert items[0].id == "r1"
    assert items[0].total_findings == 1


def test_list_recent_zero_findings(fresh_db):
    persistence.upsert(_review("r1", findings=[]))
    items, total = persistence.list_recent()
    assert total == 1
    assert items[0].total_findings == 0


def test_upsert_updates_total_findings_on_resubmit(fresh_db):
    """Re-upserting with more findings should bump the count."""
    r = _review("r1", findings=[])
    persistence.upsert(r)
    r.findings = [
        ReviewFinding(
            file_path="a.py", severity="high", category="bug", title="t1", detail="d",
        )
    ]
    persistence.upsert(r)

    with persistence._conn() as conn:
        row = conn.execute("SELECT total_findings FROM reviews WHERE id = 'r1'").fetchone()
    assert row["total_findings"] == 1


# --- Connection management ------------------------------------------------

def test_thread_local_connection_reopens_on_path_change(tmp_path, monkeypatch):
    """When config.DB_PATH changes (e.g. between tests), the next _conn call
    must reopen against the new path."""
    db_a = tmp_path / "a.db"
    monkeypatch.setattr(config, "DB_PATH", db_a)
    persistence._close_thread_conn()
    persistence.init_schema()

    with persistence._conn() as c:
        # `PRAGMA database_list` returns rows of (seq, name, file). The
        # third column is the file path.
        row = c.execute("PRAGMA database_list").fetchone()
        assert row[2] == str(db_a)

    db_b = tmp_path / "b.db"
    monkeypatch.setattr(config, "DB_PATH", db_b)
    with persistence._conn() as c:
        row = c.execute("PRAGMA database_list").fetchone()
        assert row[2] == str(db_b)
