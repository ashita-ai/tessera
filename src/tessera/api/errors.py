"""Standardized error handling for Tessera API.

Exception classes and ErrorCode live in ``tessera.exceptions`` (the canonical,
transport-agnostic location).  This module re-exports them so that existing
``from tessera.api.errors import ...`` call-sites continue to work unchanged.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from tessera.exceptions import (
    APIError as APIError,
)
from tessera.exceptions import (
    BadRequestError as BadRequestError,
)
from tessera.exceptions import (
    ConflictError as ConflictError,
)
from tessera.exceptions import (
    DuplicateError as DuplicateError,
)
from tessera.exceptions import (
    ErrorCode as ErrorCode,
)
from tessera.exceptions import (
    ForbiddenError as ForbiddenError,
)
from tessera.exceptions import (
    NotFoundError as NotFoundError,
)
from tessera.exceptions import (
    PreconditionFailedError as PreconditionFailedError,
)
from tessera.exceptions import (
    UnauthorizedError as UnauthorizedError,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to each request."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    Headers added:
    - X-Frame-Options: Prevents clickjacking by denying framing
    - X-Content-Type-Options: Prevents MIME-type sniffing
    - X-XSS-Protection: Legacy XSS filter (defense in depth)
    - Referrer-Policy: Controls referrer information sent
    - Strict-Transport-Security: HSTS (production only)
    - Content-Security-Policy: Restricts resource loading
    - Permissions-Policy: Restricts browser features
    """

    def __init__(self, app: Any, environment: str = "development") -> None:
        super().__init__(app)
        self.environment = environment

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)

        # Always set these headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        # HSTS only in production (requires HTTPS)
        if self.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # CSP: Permissive for SPA pages that load JS/CSS/fonts, strict for everything else.
        # SPA paths: anything NOT under /api/, /health, /metrics, /static/, /assets/.
        path = request.url.path
        _non_spa = ("/api/", "/health", "/metrics", "/static/", "/assets/")
        is_spa = not any(path.startswith(p) for p in _non_spa)
        if is_spa:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data:; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        else:
            # Strict CSP for API endpoints and all other paths
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )

        return response


def get_request_id(request: Request) -> str:
    """Get the request ID from the request state."""
    return getattr(request.state, "request_id", str(uuid4()))


def build_error_response(
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized error response."""
    error_data: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if details:
        error_data["details"] = details
    return {"error": error_data}


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions."""
    request_id = get_request_id(request)
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            status_code=exc.status_code,
            details=exc.details,
        ),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException with standardized format."""
    request_id = get_request_id(request)

    # Try to extract structured error info from detail
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", ErrorCode.BAD_REQUEST)
        message = exc.detail.get("message", str(exc.detail))
        details = exc.detail.get("details")
    else:
        # Map status codes to error codes
        code_map = {
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.DUPLICATE_TEAM,
            422: ErrorCode.VALIDATION_ERROR,
        }
        code = code_map.get(exc.status_code, ErrorCode.BAD_REQUEST)
        message = str(exc.detail)
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            code=code,
            message=message,
            request_id=request_id,
            status_code=exc.status_code,
            details=details,
        ),
    )


async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Handle Pydantic ValidationError with standardized format."""
    request_id = get_request_id(request)

    # Transform Pydantic errors into a more readable format
    field_errors = []
    for error in exc.errors():
        field_path = ".".join(str(loc) for loc in error["loc"])
        field_errors.append(
            {
                "field": field_path,
                "message": error["msg"],
                "type": error["type"],
            }
        )

    return JSONResponse(
        status_code=422,
        content=build_error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            request_id=request_id,
            status_code=422,
            details={"errors": field_errors},
        ),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = get_request_id(request)
    return JSONResponse(
        status_code=500,
        content=build_error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            request_id=request_id,
            status_code=500,
        ),
    )
