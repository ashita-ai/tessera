"""Tests for cache service."""

import pytest

from tessera.services.cache import (
    CacheService,
    _hash_dict,
    _make_key,
    cache_asset,
    cache_asset_search,
    cache_contract,
    cache_schema_diff,
    get_cached_asset,
    get_cached_asset_search,
    get_cached_contract,
    get_cached_schema_diff,
    invalidate_asset,
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
