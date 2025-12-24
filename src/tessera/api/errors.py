"""Standardized error handling for Tessera API."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class ErrorCode(StrEnum):
    """Standard error codes for API responses."""

    # Resource errors
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    CONTRACT_NOT_FOUND = "CONTRACT_NOT_FOUND"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    REGISTRATION_NOT_FOUND = "REGISTRATION_NOT_FOUND"
    DEPENDENCY_NOT_FOUND = "DEPENDENCY_NOT_FOUND"
    API_KEY_NOT_FOUND = "API_KEY_NOT_FOUND"
    SYNC_PATH_NOT_FOUND = "SYNC_PATH_NOT_FOUND"
    MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"

    # Duplicate errors
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    DUPLICATE_TEAM = "DUPLICATE_TEAM"
    DUPLICATE_CONTRACT_VERSION = "DUPLICATE_CONTRACT_VERSION"
    DUPLICATE_REGISTRATION = "DUPLICATE_REGISTRATION"
    DUPLICATE_ACKNOWLEDGMENT = "DUPLICATE_ACKNOWLEDGMENT"
    DUPLICATE_DEPENDENCY = "DUPLICATE_DEPENDENCY"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    INVALID_VERSION = "INVALID_VERSION"
    INVALID_FQN = "INVALID_FQN"
    INVALID_MANIFEST = "INVALID_MANIFEST"
    INVALID_OPENAPI_SPEC = "INVALID_OPENAPI_SPEC"

    # Business logic errors
    PROPOSAL_NOT_PENDING = "PROPOSAL_NOT_PENDING"
    BREAKING_CHANGE_REQUIRES_PROPOSAL = "BREAKING_CHANGE_REQUIRES_PROPOSAL"
    INCOMPATIBLE_SCHEMA = "INCOMPATIBLE_SCHEMA"
    SELF_DEPENDENCY = "SELF_DEPENDENCY"
    CONTRACT_REQUIRED = "CONTRACT_REQUIRED"
    UNAUTHORIZED_TEAM = "UNAUTHORIZED_TEAM"

    # Auth errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    MISSING_API_KEY = "MISSING_API_KEY"
    INVALID_AUTH_HEADER = "INVALID_AUTH_HEADER"
    INVALID_API_KEY = "INVALID_API_KEY"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"

    # Generic errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"


class APIError(Exception):
    """Base exception for API errors with structured responses."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(APIError):
    """Resource not found error."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, status_code=404, details=details)


class DuplicateError(APIError):
    """Duplicate resource error."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, status_code=409, details=details)


class BadRequestError(APIError):
    """Bad request error."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, status_code=400, details=details)


class UnauthorizedError(APIError):
    """Unauthorized error."""

    def __init__(
        self,
        message: str = "Authentication required",
        code: ErrorCode = ErrorCode.UNAUTHORIZED,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(code, message, status_code=401, details=details)
        self.headers = headers


class ForbiddenError(APIError):
    """Forbidden error."""

    def __init__(
        self,
        message: str = "Access denied",
        code: ErrorCode = ErrorCode.FORBIDDEN,
        details: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, status_code=403, details=details)
        if extra:
            self.details.update(extra)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to each request."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
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
