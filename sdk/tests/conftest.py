"""Pytest fixtures for SDK tests."""

import pytest

from tessera_sdk import AsyncTesseraClient, TesseraClient


@pytest.fixture
def client() -> TesseraClient:
    """Create a sync client for testing."""
    return TesseraClient(base_url="http://test.local")


@pytest.fixture
def async_client() -> AsyncTesseraClient:
    """Create an async client for testing."""
    return AsyncTesseraClient(base_url="http://test.local")
