"""Batch fetch utilities to prevent N+1 queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, TeamDB


async def fetch_asset_counts_by_team(
    session: AsyncSession,
    team_ids: list[UUID],
) -> dict[UUID, int]:
    """Fetch asset counts for multiple teams in a single query.

    Args:
        session: Database session
        team_ids: List of team IDs to fetch counts for

    Returns:
        Dictionary mapping team ID to asset count
    """
    if not team_ids:
        return {}
    result = await session.execute(
        select(AssetDB.owner_team_id, func.count(AssetDB.id))
        .where(AssetDB.owner_team_id.in_(team_ids))
        .where(AssetDB.deleted_at.is_(None))
        .group_by(AssetDB.owner_team_id)
    )
    return {team_id: count for team_id, count in result.all()}


async def fetch_asset_counts_by_user(
    session: AsyncSession,
    user_ids: list[UUID],
) -> dict[UUID, int]:
    """Fetch asset counts for multiple users in a single query.

    Args:
        session: Database session
        user_ids: List of user IDs to fetch counts for

    Returns:
        Dictionary mapping user ID to asset count
    """
    if not user_ids:
        return {}
    result = await session.execute(
        select(AssetDB.owner_user_id, func.count(AssetDB.id))
        .where(AssetDB.owner_user_id.in_(user_ids))
        .where(AssetDB.deleted_at.is_(None))
        .group_by(AssetDB.owner_user_id)
    )
    return {user_id: count for user_id, count in result.all()}


async def fetch_team_names(
    session: AsyncSession,
    team_ids: list[UUID],
) -> dict[UUID, str]:
    """Fetch team names for multiple teams in a single query.

    Args:
        session: Database session
        team_ids: List of team IDs to fetch names for

    Returns:
        Dictionary mapping team ID to team name
    """
    if not team_ids:
        return {}
    result = await session.execute(select(TeamDB.id, TeamDB.name).where(TeamDB.id.in_(team_ids)))
    return {tid: name for tid, name in result.all()}
