"""Shared utilities for sync endpoints."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import TeamDB, UserDB


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
