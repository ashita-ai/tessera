"""Redis caching service for Tessera.

Provides optional caching layer that gracefully degrades when Redis is unavailable.
"""

import asyncio
import hashlib
import json
import logging
from typing import Any

import redis.asyncio as redis

from tessera.config import settings

logger = logging.getLogger(__name__)

# Hash key length for cache key generation
# Using first 16 characters of SHA256 hex digest provides sufficient uniqueness
# while keeping keys compact (collision probability < 2^-64)
HASH_KEY_LENGTH = 16

# Global Redis connection pool
_redis_pool: "redis.ConnectionPool[Any] | None" = None
_redis_client: "redis.Redis[Any] | None" = None


async def get_redis_client() -> "redis.Redis[Any] | None":
    """Get or create Redis client connection."""
    global _redis_pool, _redis_client

    # Fast path: if redis_url is None or empty string, skip connection attempt
    if not settings.redis_url or settings.redis_url.strip() == "":
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=False,
            max_connections=10,
            socket_connect_timeout=0.05,  # 50ms timeout for fast failure in tests
            socket_timeout=0.05,  # 50ms timeout for operations
        )
        _redis_client = redis.Redis(connection_pool=_redis_pool)
        # Test connection with very short timeout
        await asyncio.wait_for(_redis_client.ping(), timeout=0.05)
        logger.info("Connected to Redis cache")
        return _redis_client
    except (TimeoutError, Exception) as e:
        logger.debug(f"Redis connection failed, caching disabled: {e}")
        _redis_client = None
        _redis_pool = None
        return None


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_pool, _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


def _make_key(prefix: str, *parts: str) -> str:
    """Creates a namespaced cache key from a prefix and variable parts.

    This function standardizes key generation across the application by
    prepending the application namespace ('tessera') and joining components
    with a consistent separator.

    Args:
        prefix (str): The category or section for the key.
        *parts (str): Variable number of string arguments to form the unique
            identifier.

    Returns:
        str: The fully formatted cache key (e.g., "tessera:user:12345").
    """
    key_data = ":".join(str(p) for p in parts)
    return f"tessera:{prefix}:{key_data}"


def _type_aware_serializer(obj: Any) -> str:
    """Serializes objects with explicit type information to prevent hash collisions.

    This helper is used as the `default` argument for JSON serialization. It
    ensures that values which might look identical in standard JSON (e.g., the
    integer 123 vs the string "123") result in different serialized strings.

    Args:
        obj (Any): The object to be serialized.

    Returns:
        str: A string representation combining the type name and the object's
            representation (e.g., "int:123" or "str:'123'").
    """
    return f"{type(obj).__name__}:{obj!r}"


def _hash_dict(data: dict[str, Any]) -> str:
    """Generates a deterministic hash of a dictionary for use in cache keys.

    This function is essential for creating cache keys based on complex input
    parameters (like query filters or configuration objects). It sorts keys
    and uses type-aware serialization to ensure that functionally identical
    dictionaries produce the same hash, while avoiding collisions between
    different types (e.g., int 123 vs string "123").

    Args:
        data (dict[str, Any]): The dictionary to hash. Keys are sorted before
            hashing to ensure determinism.

    Returns:
        str: The first HASH_KEY_LENGTH characters of the SHA256 hex digest of the
            serialized dictionary.
    """
    serialized = json.dumps(data, sort_keys=True, default=_type_aware_serializer)
    return hashlib.sha256(serialized.encode()).hexdigest()[:HASH_KEY_LENGTH]


class CacheService:
    """Async caching service with automatic fallback when Redis is unavailable."""

    def __init__(self, prefix: str = "default", ttl: int | None = None):
        """Initialize cache service.

        Args:
            prefix: Namespace prefix for all keys
            ttl: Default TTL in seconds (uses settings.cache_ttl if not specified)
        """
        self.prefix = prefix
        self.ttl = ttl or settings.cache_ttl

    async def get(self, key: str) -> Any | None:
        """Get a value from cache.

        Returns None if cache miss or Redis unavailable.
        """
        client = await get_redis_client()
        if not client:
            return None

        try:
            full_key = _make_key(self.prefix, key)
            data = await client.get(full_key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.debug(f"Cache get failed for {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in cache.

        Returns True if successful, False otherwise.
        """
        client = await get_redis_client()
        if not client:
            return False

        try:
            full_key = _make_key(self.prefix, key)
            serialized = json.dumps(value, default=str)
            await client.set(full_key, serialized, ex=ttl or self.ttl)
            return True
        except Exception as e:
            logger.debug(f"Cache set failed for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a value from cache."""
        client = await get_redis_client()
        if not client:
            return False

        try:
            full_key = _make_key(self.prefix, key)
            await client.delete(full_key)
            return True
        except Exception as e:
            logger.debug(f"Cache delete failed for {key}: {e}")
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a pattern.

        Returns count of deleted keys.
        """
        client = await get_redis_client()
        if not client:
            return 0

        try:
            full_pattern = _make_key(self.prefix, pattern)
            # Use SCAN to find matching keys
            cursor: int = 0
            deleted = 0
            while True:
                cursor, keys = await client.scan(cursor, match=full_pattern)
                if keys:
                    deleted += await client.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.debug(f"Cache invalidate failed for {pattern}: {e}")
            return 0


# Pre-configured cache instances for different domains
contract_cache = CacheService(prefix="contracts", ttl=settings.cache_ttl_contract)
asset_cache = CacheService(prefix="assets", ttl=settings.cache_ttl_asset)
team_cache = CacheService(prefix="teams", ttl=settings.cache_ttl_team)
schema_cache = CacheService(prefix="schemas", ttl=settings.cache_ttl_schema)
search_cache = CacheService(prefix="search", ttl=settings.cache_ttl)


async def cache_contract(contract_id: str, contract_data: dict[str, Any]) -> bool:
    """Cache a contract by ID."""
    return await contract_cache.set(contract_id, contract_data)


async def get_cached_contract(contract_id: str) -> dict[str, Any] | None:
    """Get a contract from cache."""
    result = await contract_cache.get(contract_id)
    if isinstance(result, dict):
        return result
    return None


async def invalidate_asset_contracts(asset_id: str) -> int:
    """Invalidate all cached contracts for an asset."""
    return await contract_cache.invalidate_pattern(f"asset:{asset_id}:*")


async def cache_asset_contracts_list(asset_id: str, contracts_data: dict[str, Any]) -> bool:
    """Cache the contracts list for an asset."""
    return await asset_cache.set(f"contracts:{asset_id}", contracts_data)


async def get_cached_asset_contracts_list(asset_id: str) -> dict[str, Any] | None:
    """Get cached contracts list for an asset."""
    result = await asset_cache.get(f"contracts:{asset_id}")
    if isinstance(result, dict):
        return result
    return None


async def cache_schema_diff(
    from_schema: dict[str, Any],
    to_schema: dict[str, Any],
    diff_result: dict[str, Any],
) -> bool:
    """Cache a schema diff result."""
    key = f"{_hash_dict(from_schema)}:{_hash_dict(to_schema)}"
    return await schema_cache.set(key, diff_result)


async def get_cached_schema_diff(
    from_schema: dict[str, Any],
    to_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Get a cached schema diff result."""
    key = f"{_hash_dict(from_schema)}:{_hash_dict(to_schema)}"
    result = await schema_cache.get(key)
    if isinstance(result, dict):
        return result
    return None


async def cache_asset(asset_id: str, asset_data: dict[str, Any]) -> bool:
    """Cache an asset by ID."""
    return await asset_cache.set(asset_id, asset_data)


async def get_cached_asset(asset_id: str) -> dict[str, Any] | None:
    """Get an asset from cache."""
    result = await asset_cache.get(asset_id)
    if isinstance(result, dict):
        return result
    return None


async def invalidate_asset(asset_id: str) -> bool:
    """Invalidate cached asset and its contracts.

    Invalidates the specific asset entry and its contracts list. Does NOT
    invalidate search caches — those have short TTLs (default 5 minutes)
    and will expire naturally. This avoids an O(N) SCAN over all keys on
    every asset change, which was causing unnecessary cache churn.
    """
    # Invalidate the specific asset entry
    asset_deleted = await asset_cache.delete(asset_id)
    # Invalidate the asset's contracts list
    contracts_list_deleted = await asset_cache.delete(f"contracts:{asset_id}")
    # Invalidate individual contract caches for this asset
    contracts_deleted = await invalidate_asset_contracts(asset_id)
    return asset_deleted or contracts_list_deleted or contracts_deleted > 0


async def cache_asset_search(query: str, filters: dict[str, Any], results: dict[str, Any]) -> bool:
    """Cache asset search results."""
    # Create cache key from query and filters
    filter_str = ":".join(f"{k}={v}" for k, v in sorted(filters.items()))
    cache_key = f"search:{_hash_dict({'q': query, 'filters': filter_str})}"
    return await asset_cache.set(cache_key, results)


async def get_cached_asset_search(query: str, filters: dict[str, Any]) -> dict[str, Any] | None:
    """Get cached asset search results."""
    filter_str = ":".join(f"{k}={v}" for k, v in sorted(filters.items()))
    cache_key = f"search:{_hash_dict({'q': query, 'filters': filter_str})}"
    result = await asset_cache.get(cache_key)
    if isinstance(result, dict):
        return result
    return None


async def cache_global_search(query: str, limit: int, results: dict[str, Any]) -> bool:
    """Cache global search results."""
    cache_key = f"global:{_hash_dict({'q': query, 'limit': limit})}"
    return await search_cache.set(cache_key, results)


async def get_cached_global_search(query: str, limit: int) -> dict[str, Any] | None:
    """Get cached global search results."""
    cache_key = f"global:{_hash_dict({'q': query, 'limit': limit})}"
    result = await search_cache.get(cache_key)
    if isinstance(result, dict):
        return result
    return None
