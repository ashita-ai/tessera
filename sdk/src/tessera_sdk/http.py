"""HTTP client implementation with sync and async support."""

from __future__ import annotations

import os
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class TesseraError(Exception):
    """Base exception for Tessera SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body


class NotFoundError(TesseraError):
    """Resource not found (404)."""

    pass


class ValidationError(TesseraError):
    """Validation error (422)."""

    pass


class ConflictError(TesseraError):
    """Conflict error (409)."""

    pass


class ServerError(TesseraError):
    """Server error (5xx)."""

    pass


def _handle_error(response: httpx.Response) -> None:
    """Raise appropriate exception based on response status code."""
    if response.is_success:
        return

    try:
        body = response.json()
    except Exception:
        body = {"detail": response.text}

    message = body.get("detail", str(body))
    status = response.status_code

    if status == 404:
        raise NotFoundError(message, status, body)
    elif status == 422:
        raise ValidationError(message, status, body)
    elif status == 409:
        raise ConflictError(message, status, body)
    elif status >= 500:
        raise ServerError(message, status, body)
    else:
        raise TesseraError(message, status, body)


class HttpClient:
    """Synchronous HTTP client for Tessera API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.getenv("TESSERA_URL") or "http://localhost:8000"
        self.base_url = url.rstrip("/")
        self._timeout = timeout
        self._headers = headers or {}
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._headers,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request."""
        response = self.client.get(path, params=params)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        response = self.client.post(path, json=json, params=params)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    def patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PATCH request."""
        response = self.client.patch(path, json=json)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    def delete(
        self,
        path: str,
    ) -> None:
        """Make a DELETE request."""
        response = self.client.delete(path)
        _handle_error(response)


class AsyncHttpClient:
    """Asynchronous HTTP client for Tessera API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.getenv("TESSERA_URL") or "http://localhost:8000"
        self.base_url = url.rstrip("/")
        self._timeout = timeout
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> AsyncHttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request."""
        response = await self.client.get(path, params=params)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        response = await self.client.post(path, json=json, params=params)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PATCH request."""
        response = await self.client.patch(path, json=json)
        _handle_error(response)
        return response.json()  # type: ignore[no-any-return]

    async def delete(
        self,
        path: str,
    ) -> None:
        """Make a DELETE request."""
        response = await self.client.delete(path)
        _handle_error(response)
