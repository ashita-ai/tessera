"""Domain exception hierarchy for Tessera.

These classes are transport-agnostic: they carry an error code, message, and
logical status code but have no dependency on FastAPI, Starlette, or any other
web framework.  The API layer maps them to HTTP responses in ``api/errors.py``.
"""

from enum import StrEnum
from typing import Any


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
    USER_NOT_FOUND = "USER_NOT_FOUND"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    SYNC_PATH_NOT_FOUND = "SYNC_PATH_NOT_FOUND"
    MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"

    # Duplicate errors
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    DUPLICATE_TEAM = "DUPLICATE_TEAM"
    DUPLICATE_CONTRACT_VERSION = "DUPLICATE_CONTRACT_VERSION"
    DUPLICATE_REGISTRATION = "DUPLICATE_REGISTRATION"
    DUPLICATE_ACKNOWLEDGMENT = "DUPLICATE_ACKNOWLEDGMENT"
    DUPLICATE_SERVICE = "DUPLICATE_SERVICE"
    DUPLICATE_DEPENDENCY = "DUPLICATE_DEPENDENCY"
    DUPLICATE_PROPOSAL = "DUPLICATE_PROPOSAL"
    DUPLICATE_REPO = "DUPLICATE_REPO"
    DUPLICATE_USER = "DUPLICATE_USER"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    INVALID_VERSION = "INVALID_VERSION"
    INVALID_FQN = "INVALID_FQN"
    INVALID_MANIFEST = "INVALID_MANIFEST"
    INVALID_OPENAPI_SPEC = "INVALID_OPENAPI_SPEC"
    INVALID_PROTO_SPEC = "INVALID_PROTO_SPEC"

    # Business logic errors
    PROPOSAL_NOT_PENDING = "PROPOSAL_NOT_PENDING"
    BREAKING_CHANGE_REQUIRES_PROPOSAL = "BREAKING_CHANGE_REQUIRES_PROPOSAL"
    INCOMPATIBLE_SCHEMA = "INCOMPATIBLE_SCHEMA"
    SELF_DEPENDENCY = "SELF_DEPENDENCY"
    CONTRACT_REQUIRED = "CONTRACT_REQUIRED"
    CONTRACT_NOT_ACTIVE = "CONTRACT_NOT_ACTIVE"
    UNAUTHORIZED_TEAM = "UNAUTHORIZED_TEAM"
    INVALID_INPUT = "INVALID_INPUT"
    TEAM_HAS_ASSETS = "TEAM_HAS_ASSETS"
    SAME_TEAM = "SAME_TEAM"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    USER_TEAM_MISMATCH = "USER_TEAM_MISMATCH"
    AUDIT_REQUIRED = "AUDIT_REQUIRED"
    AUDIT_FAILED = "AUDIT_FAILED"
    VERSION_EXISTS = "VERSION_EXISTS"
    CONFLICT_MODE_INVALID = "CONFLICT_MODE_INVALID"
    SYNC_CONFLICT = "SYNC_CONFLICT"
    SLACK_CONFIG_NOT_FOUND = "SLACK_CONFIG_NOT_FOUND"
    DUPLICATE_SLACK_CONFIG = "DUPLICATE_SLACK_CONFIG"
    INVALID_SLACK_CONFIG = "INVALID_SLACK_CONFIG"

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


class ConflictError(APIError):
    """Conflict error (409) for non-duplicate conflicts."""

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


class PreconditionFailedError(APIError):
    """Precondition failed error (412)."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, status_code=412, details=details)
