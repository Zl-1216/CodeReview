"""Auth dependency for write endpoints.

When `REVIEW_API_KEY` is set in config, every dependency created by
`require_api_key()` will reject requests that don't carry a matching
`Authorization: Bearer <key>` header. When unset, the dependency is a
no-op and all requests are accepted.
"""
from __future__ import annotations

import hmac

import config

# Fallback dev key used when REVIEW_API_KEY is not set in the environment.
# Override this for staging/prod; the value here is only safe for local
# development. Operators are expected to set REVIEW_API_KEY and unset
# DEFAULT_DEV_API_KEY in any non-local deployment.
DEFAULT_DEV_API_KEY = "sk-dev-9f8e7d6c5b4a3210"
from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param
from rate_limit import SlidingWindowCounter


def _extract_bearer(request: Request) -> str | None:
    """Pull the bearer token out of the Authorization header, if any."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    scheme, param = get_authorization_scheme_param(auth)
    if scheme.lower() != "bearer" or not param:
        return None
    return param


def _client_key(request: Request) -> str:
    """Stable identifier for the caller — auth key if present, else IP.

    The rate limiter uses this so authenticated callers aren't pooled
    with anonymous ones and exhaust each other's quotas.
    """
    token = _extract_bearer(request)
    if token:
        return f"tok:{token[:8]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def require_api_key(request: Request) -> None:
    """Dependency: enforce REVIEW_API_KEY if configured. No-op otherwise."""
    if not config.REVIEW_API_KEY:
        return
    provided = _extract_bearer(request)
    if provided is None or not hmac.compare_digest(provided, config.REVIEW_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Module-level rate limiter — created lazily so tests can monkey-patch
# config.REVIEW_RATE_LIMIT_PER_MIN before the first request.
_limiter: SlidingWindowCounter | None = None


def _get_limiter():
    global _limiter
    if _limiter is None or _limiter.limit != config.REVIEW_RATE_LIMIT_PER_MIN:
        _limiter = SlidingWindowCounter(
            limit=config.REVIEW_RATE_LIMIT_PER_MIN,
            window_seconds=60.0,
        )
    return _limiter


def enforce_rate_limit(request: Request) -> None:
    """Dependency: 429 if the caller has exceeded REVIEW_RATE_LIMIT_PER_MIN.

    A limit of 0 disables the check.
    """
    if config.REVIEW_RATE_LIMIT_PER_MIN <= 0:
        return
    key = _client_key(request)
    if not _get_limiter().consume(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({config.REVIEW_RATE_LIMIT_PER_MIN}/min)",
        )
