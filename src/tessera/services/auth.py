"""Authentication service for API key management."""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import APIKeyDB, TeamDB
from tessera.models.api_key import APIKey, APIKeyCreate, APIKeyCreated
from tessera.models.enums import APIKeyScope

# Use argon2id with secure defaults
_hasher = PasswordHasher()


def generate_api_key(environment: str = "live") -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash, key_prefix)
    """
    # Generate 32 random bytes = 64 hex characters
    random_part = secrets.token_hex(32)
    full_key = f"tess_{environment}_{random_part}"
    key_hash = _hasher.hash(full_key)
    key_prefix = f"tess_{environment}_{random_part[:4]}"
    return full_key, key_hash, key_prefix


def hash_api_key(key: str) -> str:
    """Hash an API key for storage."""
    return _hasher.hash(key)


def verify_api_key(key: str, key_hash: str) -> bool:
    """Verify an API key against its hash."""
    try:
        _hasher.verify(key_hash, key)
        return True
    except VerifyMismatchError:
        return False


async def create_api_key(
    session: AsyncSession,
    key_data: APIKeyCreate,
    environment: str = "live",
) -> APIKeyCreated:
    """Create a new API key.

    Args:
        session: Database session
        key_data: API key creation data
        environment: Environment prefix (live, test)

    Returns:
        Created API key with the raw key (only time it's available)
    """
    # Verify team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == key_data.team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise ValueError(f"Team {key_data.team_id} not found")

    # Generate the key
    full_key, key_hash, key_prefix = generate_api_key(environment)

    # Create database record
    api_key_db = APIKeyDB(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=key_data.name,
        team_id=key_data.team_id,
        scopes=[scope.value for scope in key_data.scopes],
        expires_at=key_data.expires_at,
    )
    session.add(api_key_db)
    await session.flush()

    return APIKeyCreated(
        id=api_key_db.id,
        key=full_key,
        key_prefix=key_prefix,
        name=api_key_db.name,
        team_id=api_key_db.team_id,
        scopes=[APIKeyScope(s) for s in api_key_db.scopes],
        created_at=api_key_db.created_at,
        expires_at=api_key_db.expires_at,
    )


async def validate_api_key(
    session: AsyncSession,
    key: str,
) -> tuple[APIKeyDB, TeamDB] | None:
    """Validate an API key and return the key record and team.

    With argon2, we can't do direct hash lookups (hashes are salted).
    Instead, we extract the prefix from the key to narrow candidates,
    then verify each one using argon2.

    Args:
        session: Database session
        key: The raw API key

    Returns:
        Tuple of (APIKeyDB, TeamDB) if valid, None otherwise
    """
    now = datetime.now(UTC)

    # Extract prefix from the key (e.g., "tess_live_abcd" from "tess_live_abcd...")
    # Format: tess_{env}_{first 4 chars of random}
    parts = key.split("_")
    if len(parts) < 3:
        return None
    key_prefix = f"{parts[0]}_{parts[1]}_{parts[2][:4]}"

    # Fetch candidate keys by prefix
    result = await session.execute(
        select(APIKeyDB, TeamDB)
        .join(TeamDB, APIKeyDB.team_id == TeamDB.id)
        .where(
            APIKeyDB.key_prefix == key_prefix,
            APIKeyDB.revoked_at.is_(None),
            or_(
                APIKeyDB.expires_at.is_(None),
                APIKeyDB.expires_at > now,
            ),
        )
    )
    candidates = result.all()

    # Verify each candidate with argon2
    for api_key_db, team_db in candidates:
        if verify_api_key(key, api_key_db.key_hash):
            # Update last_used_at
            await session.execute(
                update(APIKeyDB).where(APIKeyDB.id == api_key_db.id).values(last_used_at=now)
            )
            return api_key_db, team_db

    return None


async def get_api_key(
    session: AsyncSession,
    key_id: UUID,
) -> APIKey | None:
    """Get an API key by ID.

    Args:
        session: Database session
        key_id: API key ID

    Returns:
        API key if found, None otherwise
    """
    result = await session.execute(select(APIKeyDB).where(APIKeyDB.id == key_id))
    api_key_db = result.scalar_one_or_none()
    if not api_key_db:
        return None

    return APIKey(
        id=api_key_db.id,
        key_prefix=api_key_db.key_prefix,
        name=api_key_db.name,
        team_id=api_key_db.team_id,
        scopes=[APIKeyScope(s) for s in api_key_db.scopes],
        created_at=api_key_db.created_at,
        expires_at=api_key_db.expires_at,
        last_used_at=api_key_db.last_used_at,
        revoked_at=api_key_db.revoked_at,
    )


async def list_api_keys(
    session: AsyncSession,
    team_id: UUID | None = None,
    include_revoked: bool = False,
) -> list[APIKey]:
    """List API keys.

    Args:
        session: Database session
        team_id: Optional team ID to filter by
        include_revoked: Whether to include revoked keys

    Returns:
        List of API keys
    """
    query = select(APIKeyDB)

    if team_id:
        query = query.where(APIKeyDB.team_id == team_id)

    if not include_revoked:
        query = query.where(APIKeyDB.revoked_at.is_(None))

    query = query.order_by(APIKeyDB.created_at.desc())

    result = await session.execute(query)
    api_keys_db = result.scalars().all()

    return [
        APIKey(
            id=k.id,
            key_prefix=k.key_prefix,
            name=k.name,
            team_id=k.team_id,
            scopes=[APIKeyScope(s) for s in k.scopes],
            created_at=k.created_at,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
            revoked_at=k.revoked_at,
        )
        for k in api_keys_db
    ]


async def revoke_api_key(
    session: AsyncSession,
    key_id: UUID,
) -> APIKey | None:
    """Revoke an API key.

    Args:
        session: Database session
        key_id: API key ID to revoke

    Returns:
        Revoked API key if found, None otherwise
    """
    result = await session.execute(select(APIKeyDB).where(APIKeyDB.id == key_id))
    api_key_db = result.scalar_one_or_none()
    if not api_key_db:
        return None

    if api_key_db.revoked_at is not None:
        # Already revoked
        return APIKey(
            id=api_key_db.id,
            key_prefix=api_key_db.key_prefix,
            name=api_key_db.name,
            team_id=api_key_db.team_id,
            scopes=[APIKeyScope(s) for s in api_key_db.scopes],
            created_at=api_key_db.created_at,
            expires_at=api_key_db.expires_at,
            last_used_at=api_key_db.last_used_at,
            revoked_at=api_key_db.revoked_at,
        )

    api_key_db.revoked_at = datetime.now(UTC)
    await session.flush()

    return APIKey(
        id=api_key_db.id,
        key_prefix=api_key_db.key_prefix,
        name=api_key_db.name,
        team_id=api_key_db.team_id,
        scopes=[APIKeyScope(s) for s in api_key_db.scopes],
        created_at=api_key_db.created_at,
        expires_at=api_key_db.expires_at,
        last_used_at=api_key_db.last_used_at,
        revoked_at=api_key_db.revoked_at,
    )
