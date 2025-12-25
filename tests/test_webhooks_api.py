"""Tests for /api/v1/webhooks API endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestWebhookDeliveriesList:
    """Tests for GET /api/v1/webhooks/deliveries."""

    async def test_list_deliveries_empty(self, client: AsyncClient):
        """List deliveries returns empty list when none exist."""
        resp = await client.get("/api/v1/webhooks/deliveries")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data
        assert data["total"] >= 0

    async def test_list_deliveries_with_filters(self, client: AsyncClient):
        """List deliveries accepts filter parameters."""
        # Test filtering by status
        resp = await client.get("/api/v1/webhooks/deliveries?status=pending")
        assert resp.status_code == 200

        # Test filtering by event type
        resp = await client.get("/api/v1/webhooks/deliveries?event_type=proposal.created")
        assert resp.status_code == 200

    async def test_list_deliveries_pagination(self, client: AsyncClient):
        """List deliveries supports pagination."""
        resp = await client.get("/api/v1/webhooks/deliveries?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    async def test_list_deliveries_limit_validation(self, client: AsyncClient):
        """List deliveries validates limit parameter."""
        # Limit too high
        resp = await client.get("/api/v1/webhooks/deliveries?limit=200")
        assert resp.status_code == 422  # Validation error

        # Limit too low
        resp = await client.get("/api/v1/webhooks/deliveries?limit=0")
        assert resp.status_code == 422


class TestWebhookDeliveryGet:
    """Tests for GET /api/v1/webhooks/deliveries/{delivery_id}."""

    async def test_get_delivery_not_found(self, client: AsyncClient):
        """Get delivery returns 404 for nonexistent ID."""
        resp = await client.get("/api/v1/webhooks/deliveries/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_get_delivery_invalid_uuid(self, client: AsyncClient):
        """Get delivery returns 422 for invalid UUID."""
        resp = await client.get("/api/v1/webhooks/deliveries/not-a-uuid")
        assert resp.status_code == 422
