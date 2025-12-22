"""Tests for caching logic."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4
from fastapi import Request

from tessera.services.cache import CacheService, asset_cache
from tessera.api.assets import get_asset
from tessera.db.models import AssetDB, TeamDB

@pytest.fixture
def mock_redis():
    with patch("tessera.services.cache.get_redis_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client

class TestCaching:
    """Tests for cache service and integration."""

    @pytest.mark.asyncio
    async def test_cache_service_get_set(self, mock_redis):
        cache = CacheService(prefix="test", ttl=60)

        # Test set
        await cache.set("key", {"foo": "bar"})
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert "tessera:test:key" in args[0]
        assert "bar" in args[1]

        # Test get
        mock_redis.get.return_value = '{"foo": "bar"}'
        val = await cache.get("key")
        assert val == {"foo": "bar"}
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_asset_uses_cache(self, mock_redis):
        asset_id = uuid4()
        mock_request = MagicMock(spec=Request)
        mock_session = AsyncMock()
        mock_auth = MagicMock()

        # 1. Cache hit
        mock_redis.get.return_value = '{"id": "' + str(asset_id) + '", "fqn": "cached.asset", "owner_team_id": "' + str(uuid4()) + '", "metadata": {}, "created_at": "2023-01-01T00:00:00"}'

        res = await get_asset(
            request=mock_request,
            asset_id=asset_id,
            auth=mock_auth,
            session=mock_session
        )

        assert res["fqn"] == "cached.asset"
        mock_session.execute.assert_not_called()

        # 2. Cache miss
        mock_redis.get.return_value = None
        from datetime import datetime
        mock_asset = AssetDB(
            id=asset_id,
            fqn="db.asset",
            owner_team_id=uuid4(),
            environment="production",
            metadata_={},
            created_at=datetime.utcnow()
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_asset
        mock_session.execute.return_value = mock_result

        res = await get_asset(
            request=mock_request,
            asset_id=asset_id,
            auth=mock_auth,
            session=mock_session
        )

        assert res.fqn == "db.asset"
        mock_session.execute.assert_called_once()
        mock_redis.set.assert_called()

