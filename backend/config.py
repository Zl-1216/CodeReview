"""Configuration for the CodeReview service."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# --- Server -----------------------------------------------------------------
HOST = os.environ.get("REVIEW_HOST", "0.0.0.0")
PORT = int(os.environ.get("REVIEW_PORT", "8770"))

# --- Storage ----------------------------------------------------------------
DATA_DIR = Path(os.environ.get("REVIEW_DATA_DIR", Path(__file__).parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "reviews.db"

# --- AI provider ------------------------------------------------------------
# When ANTHROPIC_API_KEY is set the backend will call the Anthropic API.
# Otherwise it falls back to a deterministic rule-based mock so the UI is
# fully functional during development.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_VERSION = os.environ.get("ANTHROPIC_API_VERSION", "2023-06-01")
AI_TIMEOUT = float(os.environ.get("REVIEW_AI_TIMEOUT", "45"))

# --- Review limits ----------------------------------------------------------
MAX_FILE_BYTES = 200 * 1024  # 200 KB per file
MAX_FILES_PER_REVIEW = 50
MAX_DIFF_LINES = 4000  # truncated sentinels in the prompt
MAX_GIT_DIFF_BYTES = 5 * 1024 * 1024  # 5 MB cap on a `git diff` payload

# --- Auth & rate limit ------------------------------------------------------
# When REVIEW_API_KEY is set, write endpoints (/api/review, /cancel,
# /rerun, /api/git/remote/*) require a matching `Authorization: Bearer <key>`
# header. Reads are public. Leave empty to disable auth entirely.
REVIEW_API_KEY = os.environ.get("REVIEW_API_KEY", "").strip()
# Per-key (or per-IP when no key) cap on review submissions per minute.
# Set to 0 to disable rate limiting.
REVIEW_RATE_LIMIT_PER_MIN = int(os.environ.get("REVIEW_RATE_LIMIT_PER_MIN", "20"))
REVIEW_ID_LENGTH = int(os.environ.get("REVIEW_ID_LENGTH", "16"))

# --- Remote git integration -----------------------------------------------
# Lets users paste any https://... (or git@host:owner/repo.git) URL, clone it
# server-side into a managed cache, and pick branches to review. This is the
# only git workflow the UI exposes — the previous REPO_PATH-backed local
# mode was removed, leaving just the remote URL flow.
REVIEW_GIT_REMOTE_ENABLED = os.environ.get("REVIEW_GIT_REMOTE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
# Comma-separated host allowlist. git@ SSH URLs are mapped to their host
# (everything between `git@` and the first `:`); only listed hosts are
# accepted. Use a leading dot to allow a whole suffix (e.g. ".github.com").
_DEFAULT_REMOTE_HOSTS = (
    "github.com,gitlab.com,bitbucket.org,bitbucket.com,"
    "gitea.com,gitee.com,codeberg.org,sourcehut.org"
)
REMOTE_GIT_ALLOWED_HOSTS = tuple(
    h.strip().lower() for h in os.environ.get("REMOTE_GIT_ALLOWED_HOSTS", _DEFAULT_REMOTE_HOSTS).split(",")
    if h.strip()
)
REMOTE_GIT_CLONE_TIMEOUT = float(os.environ.get("REMOTE_GIT_CLONE_TIMEOUT", "300"))
REMOTE_GIT_CACHE_MAX = int(os.environ.get("REMOTE_GIT_CACHE_MAX", "10"))
REMOTE_GIT_CACHE_TTL = int(os.environ.get("REMOTE_GIT_CACHE_TTL", "3600"))
REMOTE_GIT_MAX_SIZE_MB = int(os.environ.get("REMOTE_GIT_MAX_SIZE_MB", "500"))
# Where to put cloned repos. Lives under DATA_DIR by default so a single
# backup / clean-up rule covers everything.
REMOTE_GIT_CACHE_DIR = Path(
    os.environ.get("REMOTE_GIT_CACHE_DIR", str(DATA_DIR / "remotes"))
)
REMOTE_GIT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- CORS -------------------------------------------------------------------
# When the env var is set we trust the operator. If they set it to a
# value that strips to nothing (e.g. `CORS_ALLOW_ORIGINS=""` — a common
# shell-quoting mistake) fall back to the default localhost allowlist
# and log a warning, so a typo in the deploy env doesn't brick startup.
_DEFAULT_CORS = ["http://localhost:5273", "http://127.0.0.1:5273"]
_cors_env = os.environ.get("CORS_ALLOW_ORIGINS")
if _cors_env is None:
    CORS_ALLOW_ORIGINS = list(_DEFAULT_CORS)
else:
    CORS_ALLOW_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]
    if not CORS_ALLOW_ORIGINS:
        logging.getLogger("codereview.config").warning(
            "CORS_ALLOW_ORIGINS is set but produced no entries; using default localhost allowlist"
        )
        print(
            "WARNING: CORS_ALLOW_ORIGINS produced no entries; using default localhost allowlist",
            file=sys.stderr,
        )
        CORS_ALLOW_ORIGINS = list(_DEFAULT_CORS)

# --- Supported review focuses -----------------------------------------------
REVIEW_FOCUSES = [
    "bug",
    "security",
    "performance",
    "style",
    "best_practice",
    "documentation",
]

SEVERITY_LEVELS = ["critical", "high", "medium", "low", "info"]
