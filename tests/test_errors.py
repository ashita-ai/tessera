"""Tests for error handling module."""

from unittest.mock import MagicMock

import pytest
from fastapi import Request
from starlette.exceptions import HTTPException

from tessera.api.errors import (
    APIError,
    BadRequestError,
    ConflictError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    UnauthorizedError,
    api_error_handler,
    build_error_response,
    get_request_id,
    http_exception_handler,
)


class TestErrorCode:
    """Tests for ErrorCode enum values and categories."""

    @pytest.mark.parametrize(
        "code",
        [
            ErrorCode.ASSET_NOT_FOUND,
            ErrorCode.TEAM_NOT_FOUND,
            ErrorCode.CONTRACT_NOT_FOUND,
            ErrorCode.PROPOSAL_NOT_FOUND,
            ErrorCode.REGISTRATION_NOT_FOUND,
            ErrorCode.DEPENDENCY_NOT_FOUND,
            ErrorCode.API_KEY_NOT_FOUND,
            ErrorCode.USER_NOT_FOUND,
            ErrorCode.SYNC_PATH_NOT_FOUND,
            ErrorCode.MANIFEST_NOT_FOUND,
        ],
    )
    def test_not_found_codes_end_with_suffix(self, code: ErrorCode) -> None:
        """All NOT_FOUND error codes end with _NOT_FOUND."""
        assert code.value.endswith("_NOT_FOUND")

    @pytest.mark.parametrize(
        "code",
        [
            ErrorCode.DUPLICATE_ASSET,
            ErrorCode.DUPLICATE_TEAM,
            ErrorCode.DUPLICATE_CONTRACT_VERSION,
            ErrorCode.DUPLICATE_REGISTRATION,
            ErrorCode.DUPLICATE_ACKNOWLEDGMENT,
            ErrorCode.DUPLICATE_DEPENDENCY,
            ErrorCode.DUPLICATE_PROPOSAL,
            ErrorCode.DUPLICATE_USER,
        ],
    )
    def test_duplicate_codes_start_with_prefix(self, code: ErrorCode) -> None:
        """All DUPLICATE error codes start with DUPLICATE_."""
        assert code.value.startswith("DUPLICATE_")

    def test_error_code_is_str_enum(self) -> None:
        """ErrorCode values are strings usable as-is in responses."""
        assert str(ErrorCode.ASSET_NOT_FOUND) == "ASSET_NOT_FOUND"
        assert ErrorCode.BAD_REQUEST == "BAD_REQUEST"


class TestAPIErrorHierarchy:
    """Tests for API error class hierarchy and default status codes."""

    @pytest.mark.parametrize(
        ("error_cls", "expected_status", "constructor_args"),
        [
            (NotFoundError, 404, {"code": ErrorCode.ASSET_NOT_FOUND, "message": "not found"}),
            (DuplicateError, 409, {"code": ErrorCode.DUPLICATE_ASSET, "message": "duplicate"}),
            (ConflictError, 409, {"code": ErrorCode.SYNC_CONFLICT, "message": "conflict"}),
            (BadRequestError, 400, {"message": "bad request"}),
            (UnauthorizedError, 401, {}),
            (ForbiddenError, 403, {}),
            (
                PreconditionFailedError,
                412,
                {"code": ErrorCode.PROPOSAL_NOT_PENDING, "message": "precondition failed"},
            ),
        ],
        ids=[
            "not_found",
            "duplicate",
            "conflict",
            "bad_request",
            "unauthorized",
            "forbidden",
            "precondition_failed",
        ],
    )
    def test_error_status_codes(
        self,
        error_cls: type[APIError],
        expected_status: int,
        constructor_args: dict,
    ) -> None:
        """Each error subclass maps to the correct HTTP status code."""
        error = error_cls(**constructor_args)
        assert error.status_code == expected_status
        assert isinstance(error, APIError)

    def test_api_error_stores_details(self) -> None:
        """APIError stores arbitrary detail dicts."""
        details = {"field": "fqn", "constraint": "unique"}
        error = APIError(ErrorCode.VALIDATION_ERROR, "failed", details=details)
        assert error.details == details
        assert error.code == ErrorCode.VALIDATION_ERROR
        assert error.message == "failed"

    def test_api_error_defaults_empty_details(self) -> None:
        """APIError defaults to empty dict when no details provided."""
        error = APIError(ErrorCode.BAD_REQUEST, "oops")
        assert error.details == {}

    def test_unauthorized_error_defaults(self) -> None:
        """UnauthorizedError has sensible defaults."""
        error = UnauthorizedError()
        assert error.message == "Authentication required"
        assert error.code == ErrorCode.UNAUTHORIZED
        assert error.status_code == 401

    def test_unauthorized_error_stores_headers(self) -> None:
        """UnauthorizedError can store WWW-Authenticate headers."""
        error = UnauthorizedError(headers={"WWW-Authenticate": "Bearer"})
        assert error.headers == {"WWW-Authenticate": "Bearer"}

    def test_forbidden_error_merges_extra(self) -> None:
        """ForbiddenError merges extra dict into details."""
        error = ForbiddenError(
            details={"resource": "asset"},
            extra={"required_scope": "admin"},
        )
        assert error.details["resource"] == "asset"
        assert error.details["required_scope"] == "admin"

    def test_bad_request_error_custom_code(self) -> None:
        """BadRequestError accepts a custom error code."""
        error = BadRequestError("invalid schema", code=ErrorCode.INVALID_SCHEMA)
        assert error.code == ErrorCode.INVALID_SCHEMA


class TestBuildErrorResponse:
    """Tests for the build_error_response helper."""

    def test_basic_structure(self) -> None:
        """Error response has required fields."""
        resp = build_error_response(
            code="TEST_ERROR",
            message="something broke",
            request_id="req-123",
            status_code=400,
        )
        assert resp["error"]["code"] == "TEST_ERROR"
        assert resp["error"]["message"] == "something broke"
        assert resp["error"]["request_id"] == "req-123"
        assert "timestamp" in resp["error"]

    def test_includes_details_when_provided(self) -> None:
        """Error response includes details dict when provided."""
        resp = build_error_response(
            code="VAL",
            message="invalid",
            request_id="r",
            status_code=422,
            details={"field": "name"},
        )
        assert resp["error"]["details"] == {"field": "name"}

    def test_omits_details_when_none(self) -> None:
        """Error response omits details key when not provided."""
        resp = build_error_response(code="ERR", message="msg", request_id="r", status_code=500)
        assert "details" not in resp["error"]


class TestGetRequestId:
    """Tests for get_request_id helper."""

    def test_returns_existing_request_id(self) -> None:
        """Returns request_id from request.state when present."""
        request = MagicMock(spec=Request)
        request.state.request_id = "existing-id"
        assert get_request_id(request) == "existing-id"

    def test_generates_uuid_when_missing(self) -> None:
        """Generates a UUID when request.state has no request_id."""
        from uuid import UUID

        request = MagicMock(spec=Request)
        del request.state.request_id  # Ensure attribute doesn't exist
        result = get_request_id(request)
        UUID(result)  # Will raise if not valid


class TestErrorHandlers:
    """Tests for exception handler functions."""

    @pytest.mark.asyncio
    async def test_api_error_handler(self) -> None:
        """api_error_handler returns correct status and body."""
        request = MagicMock(spec=Request)
        request.state.request_id = "test-req"

        error = NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")
        response = await api_error_handler(request, error)

        assert response.status_code == 404
        body = response.body.decode()
        assert "ASSET_NOT_FOUND" in body
        assert "Asset not found" in body

    @pytest.mark.asyncio
    async def test_api_error_handler_with_headers(self) -> None:
        """api_error_handler forwards headers from UnauthorizedError."""
        request = MagicMock(spec=Request)
        request.state.request_id = "test-req"

        error = UnauthorizedError(headers={"WWW-Authenticate": "Bearer"})
        response = await api_error_handler(request, error)

        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_http_exception_handler_with_string_detail(self) -> None:
        """http_exception_handler handles plain string detail."""
        request = MagicMock(spec=Request)
        request.state.request_id = "test-req"

        exc = HTTPException(status_code=404, detail="Not found")
        response = await http_exception_handler(request, exc)

        assert response.status_code == 404
        body = response.body.decode()
        assert "NOT_FOUND" in body

    @pytest.mark.asyncio
    async def test_http_exception_handler_with_dict_detail(self) -> None:
        """http_exception_handler handles structured dict detail."""
        request = MagicMock(spec=Request)
        request.state.request_id = "test-req"

        exc = HTTPException(
            status_code=409,
            detail={
                "code": "DUPLICATE_ASSET",
                "message": "Asset already exists",
                "details": {"fqn": "db.schema.table"},
            },
        )
        response = await http_exception_handler(request, exc)

        assert response.status_code == 409
        body = response.body.decode()
        assert "DUPLICATE_ASSET" in body

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "expected_code"),
        [
            (404, "NOT_FOUND"),
            (409, "DUPLICATE_TEAM"),
            (422, "VALIDATION_ERROR"),
            (400, "BAD_REQUEST"),
        ],
        ids=["404", "409", "422", "400_default"],
    )
    async def test_http_exception_handler_status_code_mapping(
        self, status_code: int, expected_code: str
    ) -> None:
        """http_exception_handler maps status codes to correct error codes."""
        request = MagicMock(spec=Request)
        request.state.request_id = "test-req"

        exc = HTTPException(status_code=status_code, detail="error")
        response = await http_exception_handler(request, exc)

        assert response.status_code == status_code
        assert expected_code in response.body.decode()
