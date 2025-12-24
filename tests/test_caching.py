"""Tests for caching logic."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request

from tessera.api.assets import get_asset
from tessera.db.models import AssetDB
from tessera.models.enums import GuaranteeMode, ResourceType
from tessera.services.cache import (
    CacheService,
    cache_asset,
    cache_contract,
    cache_schema_diff,
    get_cached_asset,
    get_cached_contract,
    get_cached_schema_diff,
    invalidate_asset,
)


@pytest.fixture
def mock_redis():
    """Mock Redis client that's available."""
    with patch("tessera.services.cache.get_redis_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
def no_redis():
    """Mock Redis client that's unavailable (returns None)."""
    with patch("tessera.services.cache.get_redis_client") as mock:
        mock.return_value = None
        yield


class TestCaching:
    """Tests for cache service and integration."""

    @pytest.mark.asyncio
    async def test_cache_service_get_set(self, mock_redis):
        """Test cache get/set operations when Redis is available."""
        cache = CacheService(prefix="test", ttl=60)

        # Test set
        result = await cache.set("key", {"foo": "bar"})
        assert result is True
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert "tessera:test:key" in args[0]
        assert "bar" in args[1]

        # Test get
        mock_redis.get.return_value = b'{"foo": "bar"}'
        val = await cache.get("key")
        assert val == {"foo": "bar"}
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_service_redis_absent_get(self, no_redis):
        """Test cache get gracefully degrades when Redis is unavailable."""
        cache = CacheService(prefix="test", ttl=60)

        # Should return None without raising exception
        val = await cache.get("key")
        assert val is None

    @pytest.mark.asyncio
    async def test_cache_service_redis_absent_set(self, no_redis):
        """Test cache set gracefully degrades when Redis is unavailable."""
        cache = CacheService(prefix="test", ttl=60)

        # Should return False without raising exception
        result = await cache.set("key", {"foo": "bar"})
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_service_redis_absent_delete(self, no_redis):
        """Test cache delete gracefully degrades when Redis is unavailable."""
        cache = CacheService(prefix="test", ttl=60)

        # Should return False without raising exception
        result = await cache.delete("key")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_asset_uses_cache(self, mock_redis):
        """Test asset endpoint uses cache when available."""
        asset_id = uuid4()
        mock_request = MagicMock(spec=Request)
        mock_session = AsyncMock()
        mock_auth = MagicMock()

        # 1. Cache hit
        team_id = str(uuid4())
        mock_redis.get.return_value = (
            b'{"id": "'
            + str(asset_id).encode()
            + b'", "fqn": "cached.asset", "owner_team_id": "'
            + team_id.encode()
            + b'", "metadata": {}, "created_at": "2023-01-01T00:00:00Z", '
            + b'"environment": "production", "guarantee_mode": "notify", "resource_type": "model"}'
        )

        res = await get_asset(
            request=mock_request, asset_id=asset_id, auth=mock_auth, session=mock_session
        )

        assert res["fqn"] == "cached.asset"
        mock_session.execute.assert_not_called()

        # 2. Cache miss
        mock_redis.get.return_value = None
        mock_asset = AssetDB(
            id=asset_id,
            fqn="db.asset",
            owner_team_id=uuid4(),
            environment="production",
            metadata_={},
            created_at=datetime.now(UTC),
            guarantee_mode=GuaranteeMode.NOTIFY,
            resource_type=ResourceType.MODEL,
        )
        # The query returns a 4-tuple: (asset, team_name, user_name, user_email)
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_asset, "Test Team", None, None)
        mock_session.execute.return_value = mock_result

        res = await get_asset(
            request=mock_request, asset_id=asset_id, auth=mock_auth, session=mock_session
        )

        assert res["fqn"] == "db.asset"
        mock_session.execute.assert_called_once()
        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_get_asset_redis_absent(self, no_redis):
        """Test asset endpoint works correctly when Redis is unavailable."""
        asset_id = uuid4()
        mock_request = MagicMock(spec=Request)
        mock_session = AsyncMock()
        mock_auth = MagicMock()

        # Should fall back to DB query
        mock_asset = AssetDB(
            id=asset_id,
            fqn="db.asset",
            owner_team_id=uuid4(),
            environment="production",
            metadata_={},
            created_at=datetime.now(UTC),
            guarantee_mode=GuaranteeMode.NOTIFY,
            resource_type=ResourceType.MODEL,
        )
        # The query returns a 4-tuple: (asset, team_name, user_name, user_email)
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_asset, "Test Team", None, None)
        mock_session.execute.return_value = mock_result

        res = await get_asset(
            request=mock_request, asset_id=asset_id, auth=mock_auth, session=mock_session
        )

        # Should still work, just without caching
        assert res["fqn"] == "db.asset"
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_helpers_redis_absent(self, no_redis):
        """Test cache helper functions gracefully degrade when Redis is unavailable."""
        # All should return None/False without raising exceptions
        assert await get_cached_asset("test-id") is None
        assert await cache_asset("test-id", {"foo": "bar"}) is False
        assert await get_cached_contract("test-id") is None
        assert await cache_contract("test-id", {"foo": "bar"}) is False
        assert await get_cached_schema_diff({"a": 1}, {"b": 2}) is None
        assert await cache_schema_diff({"a": 1}, {"b": 2}, {"diff": "result"}) is False
        assert await invalidate_asset("test-id") is False

    @pytest.mark.asyncio
    async def test_cache_redis_connection_error(self):
        """Test cache handles Redis connection errors gracefully."""
        cache = CacheService(prefix="test", ttl=60)

        with patch("tessera.services.cache.get_redis_client") as mock_get:
            # Simulate connection error
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Connection failed")
            mock_get.return_value = mock_client

            # Should return None without raising exception
            val = await cache.get("key")
            assert val is None

    @pytest.mark.asyncio
    async def test_cache_redis_set_error(self):
        """Test cache handles Redis set errors gracefully."""
        cache = CacheService(prefix="test", ttl=60)

        with patch("tessera.services.cache.get_redis_client") as mock_get:
            # Simulate set error
            mock_client = AsyncMock()
            mock_client.set.side_effect = Exception("Set failed")
            mock_get.return_value = mock_client

            # Should return False without raising exception
            result = await cache.set("key", {"foo": "bar"})
            assert result is False


class TestCachingIntegration:
    """Integration tests for caching with real endpoints."""

    @pytest.mark.asyncio
    async def test_asset_endpoint_works_without_redis(self, client, no_redis):
        """Test asset endpoint works correctly when Redis is unavailable."""
        # Create a team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "cache-test-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "cache.test.asset", "owner_team_id": team_id},
        )
        assert asset_resp.status_code == 201
        asset_id = asset_resp.json()["id"]

        # Should still be able to get the asset (falls back to DB)
        get_resp = await client.get(f"/api/v1/assets/{asset_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["fqn"] == "cache.test.asset"

    @pytest.mark.asyncio
    async def test_contract_endpoint_works_without_redis(self, client, no_redis):
        """Test contract endpoint works correctly when Redis is unavailable."""
        # Create team, asset, and contract
        team_resp = await client.post("/api/v1/teams", json={"name": "contract-cache-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "contract.cache.test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"foo": {"type": "string"}}},
            },
        )
        assert contract_resp.status_code == 201
        contract_id = contract_resp.json()["contract"]["id"]

        # Should still be able to get the contract (falls back to DB)
        get_resp = await client.get(f"/api/v1/contracts/{contract_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_contract_compare_works_without_redis(self, client, no_redis):
        """Test contract comparison works correctly when Redis is unavailable."""
        # Create team, asset, and two contracts
        team_resp = await client.post("/api/v1/teams", json={"name": "compare-cache-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "compare.cache.test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish first contract
        contract1_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"foo": {"type": "string"}}},
            },
        )
        contract1_id = contract1_resp.json()["contract"]["id"]

        # Publish second contract (compatible change - adds optional field)
        contract2_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"foo": {"type": "string"}, "bar": {"type": "string"}},
                },
            },
        )
        assert contract2_resp.status_code == 201
        contract2_data = contract2_resp.json()
        # Response should have "contract" key for published contracts
        assert "contract" in contract2_data, f"Expected 'contract' key, got: {contract2_data}"
        contract2_id = contract2_data["contract"]["id"]

        # Should still be able to compare contracts (falls back to direct diff)
        compare_resp = await client.post(
            "/api/v1/contracts/compare",
            json={"contract_id_1": contract1_id, "contract_id_2": contract2_id},
        )
        assert compare_resp.status_code == 200
        assert "change_type" in compare_resp.json()
        assert "is_compatible" in compare_resp.json()
