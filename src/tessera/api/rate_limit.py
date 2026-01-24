"""Rate limiting configuration and dependencies.

Provides two levels of rate limiting:
1. Per-API-key rate limiting (default): Each API key has its own bucket
2. Per-team rate limiting: Aggregated limits across all keys for a team

Per-team rate limiting is used for expensive operations like schema diff
and lineage analysis to prevent a team from monopolizing resources.
"""

import hashlib
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from tessera.config import settings

P = ParamSpec("P")
T = TypeVar("T")


def get_rate_limit_key(request: Request) -> str:
    """Get a unique key for rate limiting.

    Uses a hash of the full API key if present in the Authorization header,
    otherwise falls back to remote IP address.

    Note: We hash the full key to ensure each API key gets its own rate limit
    bucket, preventing one noisy client from affecting others.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
        # Hash the full API key to create a unique, stable bucket per key
        # Using SHA256 and taking first 16 chars for a compact but unique key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"key:{key_hash}"

    # Fallback to IP address
    return get_remote_address(request)


def get_team_rate_limit_key(request: Request) -> str:
    """Get a rate limit key based on the authenticated team.

    This groups all API keys belonging to the same team into one bucket,
    preventing a team from bypassing rate limits by creating multiple keys.

    Falls back to API key hash if team_id is not available in request state.
    """
    # Check if team_id was set during request processing
    team_id = getattr(request.state, "team_id", None)
    if team_id:
        return f"team:{team_id}"

    # Fallback to API key-based limiting
    return get_rate_limit_key(request)


# Initialize limiter for per-API-key rate limiting
# Rate limiting can be disabled via settings.rate_limit_enabled
# Note: enabled must be a boolean, not a callable. We'll control it via middleware.
limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=True,  # Always enabled at limiter level, controlled via middleware
    default_limits=[lambda: settings.rate_limit_global],
)

# Initialize a separate limiter for per-team rate limiting
# Used for expensive operations that should be limited per team, not per key
team_limiter = Limiter(
    key_func=get_team_rate_limit_key,
    enabled=True,
    default_limits=[],  # No default, only used explicitly
)


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """Custom handler for rate limit exceeded errors.

    Adds the 'Retry-After' header as required by the spec.
    """
    detail = str(getattr(exc, "detail", str(exc)))
    response = JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too Many Requests",
                "detail": detail,
            }
        },
    )
    # Extract retry-after if available
    # slowapi doesn't always provide it in the exception,
    # but we can try to estimate or just set a default if missing.
    # For now, we'll set a reasonable default if slowapi doesn't provide it.
    retry_after = "60"  # Default 1 minute
    response.headers["Retry-After"] = retry_after
    return response


# Helper decorators for common scopes using callables for dynamic settings
# When rate limiting is disabled, use empty string to disable limits
def _get_rate_limit(limit_str: str) -> str:
    """Get rate limit string, or empty string if rate limiting is disabled."""
    return limit_str if settings.rate_limit_enabled else ""


# Per-API-key rate limit decorators
limit_read = limiter.limit(lambda: _get_rate_limit(settings.rate_limit_read))
limit_write = limiter.limit(lambda: _get_rate_limit(settings.rate_limit_write))
limit_admin = limiter.limit(lambda: _get_rate_limit(settings.rate_limit_admin))

# Per-team rate limit decorators for expensive operations
limit_expensive = team_limiter.limit(lambda: _get_rate_limit(settings.rate_limit_expensive))
limit_bulk = team_limiter.limit(lambda: _get_rate_limit(settings.rate_limit_bulk))


def set_team_id_in_request(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]:
    """Decorator that sets team_id in request state after auth resolves.

    This must be applied AFTER the auth dependency resolves. It extracts
    the team_id from the auth context and stores it in request.state for
    use by per-team rate limiting.

    Usage:
        @router.get("/expensive")
        @limit_expensive  # Per-team rate limit
        @set_team_id_in_request
        async def expensive_operation(request: Request, auth: Auth, ...):
            ...
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # Find auth and request in kwargs
        request = kwargs.get("request")
        auth = kwargs.get("auth")

        if request is not None and auth is not None:
            # Set team_id in request state for rate limiting
            # request is a FastAPI Request object with state attribute
            if hasattr(request, "state") and hasattr(auth, "team_id"):
                request.state.team_id = str(auth.team_id)  # type: ignore[union-attr]

        return await func(*args, **kwargs)

    return wrapper


def combined_rate_limit(
    per_key_limit: str | None = None,
    per_team_limit: str | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Apply both per-key and per-team rate limits to an endpoint.

    This is useful for expensive operations that need both types of limiting:
    - Per-key prevents a single API key from making too many requests
    - Per-team prevents a team from bypassing limits with multiple keys

    Args:
        per_key_limit: Limit per API key (e.g., "100/minute")
        per_team_limit: Limit per team (e.g., "20/minute")

    Usage:
        @router.get("/diff")
        @combined_rate_limit(per_key_limit="100/minute", per_team_limit="20/minute")
        async def diff_schemas(request: Request, auth: Auth, ...):
            ...
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        wrapped = func

        # Apply per-team limit if specified
        if per_team_limit:
            team_limit_decorator = team_limiter.limit(lambda: _get_rate_limit(per_team_limit))
            wrapped = team_limit_decorator(set_team_id_in_request(wrapped))

        # Apply per-key limit if specified
        if per_key_limit:
            key_limit_decorator = limiter.limit(lambda: _get_rate_limit(per_key_limit))
            wrapped = key_limit_decorator(wrapped)

        return wrapped

    return decorator
