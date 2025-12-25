"""Tests for cache service."""

from unittest.mock import AsyncMock, patch

import pytest

from tessera.services.cache import (
    CacheService,
    _hash_dict,
    _make_key,
    cache_asset,
    cache_asset_contracts_list,
    cache_asset_search,
    cache_contract,
    cache_schema_diff,
    close_redis,
    get_cached_asset,
    get_cached_asset_contracts_list,
    get_cached_asset_search,
    get_cached_contract,
    get_cached_schema_diff,
    get_redis_client,
    invalidate_asset,
    invalidate_asset_contracts,
)

pytestmark = pytest.mark.asyncio


class TestCacheKeyHelpers:
    """Tests for cache key helper functions."""

    def test_make_key_simple(self):
        """Make key combines prefix and parts."""
        key = _make_key("contracts", "abc123")
        assert key == "tessera:contracts:abc123"

    def test_make_key_multiple_parts(self):
        """Make key joins multiple parts with colons."""
        key = _make_key("assets", "team1", "asset1")
        assert key == "tessera:assets:team1:asset1"

    def test_hash_dict_consistent(self):
        """Same dict produces same hash."""
        data = {"a": 1, "b": "two"}
        hash1 = _hash_dict(data)
        hash2 = _hash_dict(data)
        assert hash1 == hash2

    def test_hash_dict_order_independent(self):
        """Dict key order doesn't affect hash."""
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}
        assert _hash_dict(data1) == _hash_dict(data2)

    def test_hash_dict_different_data(self):
        """Different dicts produce different hashes."""
        hash1 = _hash_dict({"x": 1})
        hash2 = _hash_dict({"x": 2})
        assert hash1 != hash2

    def test_hash_dict_truncated(self):
        """Hash is truncated to 16 characters."""
        result = _hash_dict({"data": "value"})
        assert len(result) == 16


class TestCacheService:
    """Tests for CacheService class."""

    async def test_get_returns_none_without_redis(self):
        """Get returns None when Redis is unavailable."""
        cache = CacheService(prefix="test")
        result = await cache.get("nonexistent-key")
        assert result is None

    async def test_set_returns_false_without_redis(self):
        """Set returns False when Redis is unavailable."""
        cache = CacheService(prefix="test")
        result = await cache.set("key", {"data": "value"})
        assert result is False

    async def test_delete_returns_false_without_redis(self):
        """Delete returns False when Redis is unavailable."""
        cache = CacheService(prefix="test")
        result = await cache.delete("key")
        assert result is False

    async def test_invalidate_pattern_returns_zero_without_redis(self):
        """Invalidate pattern returns 0 when Redis is unavailable."""
        cache = CacheService(prefix="test")
        result = await cache.invalidate_pattern("*")
        assert result == 0

    async def test_custom_ttl(self):
        """CacheService uses custom TTL."""
        cache = CacheService(prefix="test", ttl=3600)
        assert cache.ttl == 3600


class TestCacheConvenienceFunctions:
    """Tests for cache convenience functions."""

    async def test_cache_contract_without_redis(self):
        """Cache contract gracefully handles no Redis."""
        result = await cache_contract("contract-1", {"version": "1.0"})
        assert result is False

    async def test_get_cached_contract_without_redis(self):
        """Get cached contract returns None without Redis."""
        result = await get_cached_contract("contract-1")
        assert result is None

    async def test_cache_asset_without_redis(self):
        """Cache asset gracefully handles no Redis."""
        result = await cache_asset("asset-1", {"fqn": "test.asset"})
        assert result is False

    async def test_get_cached_asset_without_redis(self):
        """Get cached asset returns None without Redis."""
        result = await get_cached_asset("asset-1")
        assert result is None

    async def test_invalidate_asset_without_redis(self):
        """Invalidate asset gracefully handles no Redis."""
        result = await invalidate_asset("asset-1")
        assert result is False

    async def test_cache_schema_diff_without_redis(self):
        """Cache schema diff gracefully handles no Redis."""
        from_schema = {"type": "object"}
        to_schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        diff_result = {"has_changes": True}
        result = await cache_schema_diff(from_schema, to_schema, diff_result)
        assert result is False

    async def test_get_cached_schema_diff_without_redis(self):
        """Get cached schema diff returns None without Redis."""
        from_schema = {"type": "object"}
        to_schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = await get_cached_schema_diff(from_schema, to_schema)
        assert result is None

    async def test_cache_asset_search_without_redis(self):
        """Cache asset search gracefully handles no Redis."""
        result = await cache_asset_search("query", {"status": "active"}, {"results": []})
        assert result is False

    async def test_get_cached_asset_search_without_redis(self):
        """Get cached asset search returns None without Redis."""
        result = await get_cached_asset_search("query", {"status": "active"})
        assert result is None


class TestGetRedisClient:
    """Tests for get_redis_client function."""

    async def test_no_redis_url_returns_none(self):
        """Returns None when redis_url is not configured."""
        with patch("tessera.services.cache.settings") as mock_settings:
            mock_settings.redis_url = None
            result = await get_redis_client()
            assert result is None

    async def test_empty_redis_url_returns_none(self):
        """Returns None when redis_url is empty."""
        with patch("tessera.services.cache.settings") as mock_settings:
            mock_settings.redis_url = ""
            result = await get_redis_client()
            assert result is None

    async def test_whitespace_redis_url_returns_none(self):
        """Returns None when redis_url is whitespace only."""
        with patch("tessera.services.cache.settings") as mock_settings:
            mock_settings.redis_url = "   "
            result = await get_redis_client()
            assert result is None


class TestCloseRedis:
    """Tests for close_redis function."""

    async def test_close_with_no_client(self):
        """close_redis handles no client gracefully."""
        import tessera.services.cache as cache_module

        cache_module._redis_client = None
        cache_module._redis_pool = None

        # Should not raise
        await close_redis()
        assert cache_module._redis_client is None
        assert cache_module._redis_pool is None

    async def test_close_with_client(self):
        """close_redis closes client and pool."""
        import tessera.services.cache as cache_module

        mock_client = AsyncMock()
        mock_pool = AsyncMock()

        cache_module._redis_client = mock_client
        cache_module._redis_pool = mock_pool

        await close_redis()

        mock_client.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()
        assert cache_module._redis_client is None
        assert cache_module._redis_pool is None


class TestCacheServiceWithMock:
    """Tests for CacheService with mocked Redis client."""

    async def test_get_cache_hit(self):
        """get returns cached value on hit."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=b'{"foo": "bar"}')

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.get("key")
            assert result == {"foo": "bar"}

    async def test_get_exception_returns_none(self):
        """get returns None on exception."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Redis error"))

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.get("key")
            assert result is None

    async def test_set_success(self):
        """set returns True on success."""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test", ttl=300)
            result = await cache.set("key", {"value": 1})
            assert result is True
            mock_client.set.assert_called_once()

    async def test_set_custom_ttl(self):
        """set uses custom TTL when provided."""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test", ttl=300)
            await cache.set("key", {"value": 1}, ttl=60)
            call_args = mock_client.set.call_args
            assert call_args.kwargs["ex"] == 60

    async def test_set_exception_returns_false(self):
        """set returns False on exception."""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(side_effect=Exception("Redis error"))

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.set("key", {"value": 1})
            assert result is False

    async def test_delete_success(self):
        """delete returns True on success."""
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=1)

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.delete("key")
            assert result is True

    async def test_delete_exception_returns_false(self):
        """delete returns False on exception."""
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(side_effect=Exception("Redis error"))

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.delete("key")
            assert result is False

    async def test_invalidate_pattern_success(self):
        """invalidate_pattern returns count of deleted keys."""
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(side_effect=[(0, [b"key1", b"key2"])])
        mock_client.delete = AsyncMock(return_value=2)

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.invalidate_pattern("*")
            assert result == 2

    async def test_invalidate_pattern_multiple_scans(self):
        """invalidate_pattern handles multiple SCAN iterations."""
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(
            side_effect=[
                (1, [b"key1"]),
                (0, [b"key2", b"key3"]),
            ]
        )
        mock_client.delete = AsyncMock(side_effect=[1, 2])

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.invalidate_pattern("*")
            assert result == 3

    async def test_invalidate_pattern_exception_returns_zero(self):
        """invalidate_pattern returns 0 on exception."""
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(side_effect=Exception("Redis error"))

        with patch("tessera.services.cache.get_redis_client", return_value=mock_client):
            cache = CacheService(prefix="test")
            result = await cache.invalidate_pattern("*")
            assert result == 0


class TestCacheFunctionsWithMock:
    """Tests for cache convenience functions with mocked Redis."""

    async def test_cache_contract_success(self):
        """cache_contract returns True on success."""
        with patch("tessera.services.cache.contract_cache") as mock_cache:
            mock_cache.set = AsyncMock(return_value=True)
            result = await cache_contract("contract-id", {"version": "1.0.0"})
            assert result is True
            mock_cache.set.assert_called_once_with("contract-id", {"version": "1.0.0"})

    async def test_get_cached_contract_hit(self):
        """get_cached_contract returns dict on cache hit."""
        with patch("tessera.services.cache.contract_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value={"version": "1.0.0"})
            result = await get_cached_contract("contract-id")
            assert result == {"version": "1.0.0"}

    async def test_get_cached_contract_non_dict_returns_none(self):
        """get_cached_contract returns None for non-dict result."""
        with patch("tessera.services.cache.contract_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="not a dict")
            result = await get_cached_contract("contract-id")
            assert result is None

    async def test_cache_asset_contracts_list(self):
        """cache_asset_contracts_list stores in asset_cache with proper key."""
        with patch("tessera.services.cache.asset_cache") as mock_cache:
            mock_cache.set = AsyncMock(return_value=True)
            result = await cache_asset_contracts_list("asset-id", {"results": []})
            assert result is True
            mock_cache.set.assert_called_once_with("contracts:asset-id", {"results": []})

    async def test_get_cached_asset_contracts_list(self):
        """get_cached_asset_contracts_list retrieves from asset_cache."""
        with patch("tessera.services.cache.asset_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value={"results": []})
            result = await get_cached_asset_contracts_list("asset-id")
            assert result == {"results": []}
            mock_cache.get.assert_called_once_with("contracts:asset-id")

    async def test_get_cached_asset_contracts_list_non_dict(self):
        """get_cached_asset_contracts_list returns None for non-dict."""
        with patch("tessera.services.cache.asset_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="not-a-dict")
            result = await get_cached_asset_contracts_list("asset-id")
            assert result is None

    async def test_invalidate_asset_contracts(self):
        """invalidate_asset_contracts invalidates pattern."""
        with patch("tessera.services.cache.contract_cache") as mock_cache:
            mock_cache.invalidate_pattern = AsyncMock(return_value=5)
            result = await invalidate_asset_contracts("asset-id")
            assert result == 5
            mock_cache.invalidate_pattern.assert_called_once_with("asset:asset-id:*")

    async def test_get_cached_asset_non_dict_returns_none(self):
        """get_cached_asset returns None for non-dict result."""
        with patch("tessera.services.cache.asset_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=123)
            result = await get_cached_asset("asset-id")
            assert result is None

    async def test_get_cached_schema_diff_non_dict_returns_none(self):
        """get_cached_schema_diff returns None for non-dict result."""
        with patch("tessera.services.cache.schema_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="not-a-dict")
            result = await get_cached_schema_diff({}, {})
            assert result is None

    async def test_get_cached_asset_search_non_dict_returns_none(self):
        """get_cached_asset_search returns None for non-dict result."""
        with patch("tessera.services.cache.asset_cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="not-a-dict")
            result = await get_cached_asset_search("query", {})
            assert result is None
