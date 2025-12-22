"""Rate limiting configuration and dependencies."""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from tessera.config import settings

def get_rate_limit_key(request: Request) -> str:
    """Get a unique key for rate limiting.

    Uses the API key if present in the Authorization header,
    otherwise falls back to remote IP address.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
        # Use prefix if possible (first 10 chars)
        if len(api_key) > 10:
            return f"key:{api_key[:10]}"
        return f"key:{api_key}"

    # Fallback to IP address
    return get_remote_address(request)

# Initialize limiter
# Rate limiting can be disabled via settings.rate_limit_enabled
limiter = Limiter(
    key_func=get_rate_limit_key,
    enabled=lambda: settings.rate_limit_enabled,
    default_limits=[lambda: settings.rate_limit_global if settings.rate_limit_enabled else ""],
)

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Custom handler for rate limit exceeded errors.

    Adds the 'Retry-After' header as required by the spec.
    """
    response = JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too Many Requests",
                "detail": str(exc.detail),
            }
        },
    )
    # Extract retry-after if available
    # slowapi doesn't always provide it in the exception,
    # but we can try to estimate or just set a default if missing.
    # For now, we'll set a reasonable default if slowapi doesn't provide it.
    retry_after = "60" # Default 1 minute
    response.headers["Retry-After"] = retry_after
    return response

# Helper decorators for common scopes using callables for dynamic settings
limit_read = limiter.limit(lambda: settings.rate_limit_read)
limit_write = limiter.limit(lambda: settings.rate_limit_write)
limit_admin = limiter.limit(lambda: settings.rate_limit_admin)
