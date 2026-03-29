"""Shared utilities for sync endpoints."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import TeamDB, UserDB


def deep_merge_metadata(
    base: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Recursively merge *updates* into *base*, preserving nested keys.

    Rules:
    - When both values for a key are dicts, merge recursively.
    - Otherwise the value from *updates* wins (scalars, lists, type changes).
    - Keys present in *base* but absent from *updates* are preserved.

    Neither input dict is mutated; a new dict is returned.
    """
    merged: dict[str, Any] = {**base}
    for key, new_value in updates.items():
        existing_value = merged.get(key)
        if isinstance(existing_value, dict) and isinstance(new_value, dict):
            merged[key] = deep_merge_metadata(existing_value, new_value)
        else:
            merged[key] = new_value
    return merged


async def resolve_team_by_name(
    session: AsyncSession,
    team_name: str,
) -> TeamDB | None:
    """Look up a team by name (case-insensitive)."""
    result = await session.execute(
        select(TeamDB).where(TeamDB.name.ilike(team_name)).where(TeamDB.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def resolve_user_by_email(
    session: AsyncSession,
    email: str,
) -> UserDB | None:
    """Look up a user by email (case-insensitive)."""
    result = await session.execute(
        select(UserDB).where(UserDB.email.ilike(email)).where(UserDB.deactivated_at.is_(None))
    )
    return result.scalar_one_or_none()
