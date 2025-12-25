"""Tests for health endpoint."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestHealth:
    """Tests for health endpoint."""

    async def test_health_check(self, client: AsyncClient):
        """Health endpoint should return healthy."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
