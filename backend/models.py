"""Pydantic schemas for the code review service.

`description=` and `examples=` on each Field are surfaced in the OpenAPI
schema at /docs and /openapi.json — they're the only "live" API docs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
ReviewFocus = Literal["bug", "security", "performance", "style", "best_practice", "documentation"]


class CodeFile(BaseModel):
    """A single file submitted for review.

    `content` is the post-change content. When `original_content` is supplied
    the reviewer can reason about the diff. Either may be empty for a brand
    new file or a deletion, respectively.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "path": "src/example.py",
                "content": "def add(a, b):\n    return a + b\n",
                "original_content": "def add(a, b):\n    pass\n",
                "language": "python",
                "line_map": {"2": 2},
            }
        }
    )

    path: str = Field(..., description="File path as it should appear in findings.", examples=["src/example.py"])
    content: str = Field(default="", description="The post-change file content.")
    original_content: str | None = Field(
        default=None,
        description="Pre-change content, if this is part of a diff. Leave null for a brand-new file.",
    )
    language: str | None = Field(
        default=None,
        description="Language identifier (e.g. 'python'). Inferred from `path` extension when omitted.",
        examples=["python"],
    )
    # new-line -> old-line for diff parsing; populated by parse_unified_diff.
    # Empty when there is no original content or no hunk headers.
    line_map: dict[int, int] = Field(
        default_factory=dict,
        description="Maps a new-file line number to its original line number (if any).",
    )


class ReviewRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Tighten auth middleware",
                "description": "Looking for any auth-bypass issues.",
                "files": [
                    {
                        "path": "src/auth.py",
                        "language": "python",
                        "content": "def check(u):\n    return u.role == 'admin'\n",
                    }
                ],
                "focuses": ["security", "bug"],
                "model": "claude-sonnet-4-6",
            }
        }
    )

    files: list[CodeFile] = Field(..., max_length=50, description="Files to include in the review. Capped at 50 per request.")
    title: str | None = Field(default=None, description="Optional human-readable title; defaults to the first file path.")
    description: str | None = Field(default=None, description="Free-form context the reviewer should consider.")
    focuses: list[ReviewFocus] = Field(
        default_factory=lambda: ["bug", "security", "performance", "style"],
        description="Categories the reviewer should prioritize.",
    )
    model: str | None = Field(
        default=None,
        description="Override `REVIEW_MODEL` for this request. Has no effect in the mock engine.",
        examples=["claude-sonnet-4-6"],
    )
    # Tag the source of the diff for the history list. Frontend sets this
    # to "local" (REPO_PATH-backed) or "remote:<owner>/<repo>".
    source: str | None = Field(
        default=None,
        description="Optional origin tag, e.g. 'local' or 'remote:<name>'. Recorded on the persisted review for filtering in the history view.",
    )


class ReviewFinding(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_path": "src/auth.py",
                "line_start": 2,
                "line_end": 2,
                "severity": "high",
                "category": "security",
                "title": "Role check trusts user input",
                "detail": "`u.role` is read from the request without verifying the session.",
                "suggestion": "Pull `role` from the verified session, not the request body.",
                "code_snippet": "    return u.role == 'admin'",
            }
        }
    )

    file_path: str = Field(..., description="Path of the file the finding applies to.")
    line_start: int | None = Field(default=None, description="First line (1-indexed) the finding applies to.")
    line_end: int | None = Field(default=None, description="Last line (1-indexed) the finding applies to. Omit for single-line findings.")
    severity: Severity = Field(..., description="One of: critical, high, medium, low, info.")
    category: ReviewFocus = Field(..., description="One of: bug, security, performance, style, best_practice, documentation.")
    title: str = Field(..., description="One-line summary of the finding.")
    detail: str = Field(..., description="Why this matters, in the same language as the file.")
    suggestion: str | None = Field(default=None, description="Concrete fix. May include a code snippet.")
    code_snippet: str | None = Field(default=None, description="Verbatim line(s) of offending code, if any.")


class ReviewSummary(BaseModel):
    """Top-level summary for a completed review."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_findings": 3,
                "by_severity": {"high": 1, "medium": 1, "low": 1, "critical": 0, "info": 0},
                "by_category": {"security": 1, "bug": 1, "style": 1},
                "overall_assessment": "Two real issues (one security, one bug) and a style nit.",
            }
        }
    )

    total_findings: int = Field(..., description="Total number of findings in the review.")
    by_severity: dict[str, int] = Field(..., description="Finding count per severity bucket.")
    by_category: dict[str, int] = Field(..., description="Finding count per category.")
    overall_assessment: str = Field(..., description="One-paragraph verdict a senior engineer would write.")


class Review(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4e5f67890",
                "created_at": "2026-06-08T10:00:00",
                "title": "Tighten auth middleware",
                "file_count": 1,
                "focuses": ["security", "bug"],
                "model": "claude-sonnet-4-6",
                "status": "completed",
                "duration_ms": 1234,
            }
        }
    )

    id: str = Field(..., description="Hex id of the review (16 chars by default).")
    created_at: datetime = Field(..., description="When the review was submitted.")
    title: str = Field(..., description="Human-readable title.")
    description: str | None = Field(default=None, description="Optional free-form context.")
    file_count: int = Field(..., description="Number of files included in the review.")
    focuses: list[ReviewFocus] = Field(..., description="Categories the reviewer prioritized.")
    model: str = Field(..., description="The model id that produced the findings.")
    findings: list[ReviewFinding] = Field(default_factory=list, description="All findings emitted so far.")
    summary: ReviewSummary | None = Field(default=None, description="Summary populated when the review completes.")
    status: Literal["pending", "streaming", "completed", "failed"] = Field(
        default="pending",
        description="Lifecycle state. `streaming` means findings are still being produced.",
    )
    error: str | None = Field(default=None, description="Error message when status=failed.")
    duration_ms: int | None = Field(default=None, description="Wall-clock time the review took, in milliseconds.")
    # files are stored so historical reviews still have the code context for
    # the diff viewer. Empty for reviews loaded from the list endpoint.
    files: list[CodeFile] = Field(
        default_factory=list,
        description="Files included in this review. Omitted from the list endpoint to keep payloads small.",
    )
    # Identifies where the diff came from. None for legacy rows; the API
    # surfaces "local" (REPO_PATH-backed) or "remote:<owner>/<repo>" so
    # the history list can tag the source.
    source: str | None = Field(
        default=None,
        description="Origin of the diff: 'local' for REPO_PATH-backed reviews, 'remote:<name>' for user-supplied remote repos, null for legacy rows.",
    )


class ReviewListItem(BaseModel):
    """A row in the history list — no findings to keep payloads small."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4e5f67890",
                "created_at": "2026-06-08T10:00:00",
                "title": "Tighten auth middleware",
                "file_count": 1,
                "focuses": ["security"],
                "model": "claude-sonnet-4-6",
                "status": "completed",
                "total_findings": 3,
                "duration_ms": 1234,
            }
        }
    )

    id: str = Field(..., description="Hex id of the review.")
    created_at: datetime = Field(..., description="When the review was submitted.")
    title: str = Field(..., description="Human-readable title.")
    file_count: int = Field(..., description="Number of files included in the review.")
    focuses: list[ReviewFocus] = Field(..., description="Categories the reviewer prioritized.")
    model: str = Field(..., description="Model id used.")
    status: str = Field(..., description="Lifecycle state.")
    total_findings: int = Field(default=0, description="Finding count (denormalized for the list view).")
    duration_ms: int | None = Field(default=None, description="Wall-clock duration, in milliseconds.")
    source: str | None = Field(
        default=None,
        description="Origin of the diff: 'local' for REPO_PATH-backed reviews, 'remote:<name>' for user-supplied remote repos, null for legacy rows.",
    )


class ReviewListResponse(BaseModel):
    items: list[ReviewListItem] = Field(..., description="A page of history items, newest first.")
    total: int = Field(..., description="Total number of reviews in the database.")


class ReviewDiffRequest(BaseModel):
    """Used to parse a raw unified diff into per-file `CodeFile` entries."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "diff": "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
            }
        }
    )

    diff: str = Field(..., description="A unified diff (output of `git diff` or `diff -u`).")


class ReviewDiffResponse(BaseModel):
    files: list[CodeFile] = Field(..., description="Files reconstructed from the diff.")
