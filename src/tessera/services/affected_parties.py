"""Service for computing affected parties from lineage.

This module discovers teams and assets that will be affected by changes to an
asset, based on dependency relationships in AssetDependencyDB.
"""

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, AssetDependencyDB, TeamDB, UserDB


async def get_affected_parties(
    session: AsyncSession,
    asset_id: UUID,
    exclude_team_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get teams and assets affected by changes to this asset via lineage.

    Queries AssetDependencyDB for all downstream edges where
    dependency_asset_id == asset_id. No metadata fallback.

    Args:
        session: Database session
        asset_id: The asset being changed
        exclude_team_id: Optional team ID to exclude (typically the asset owner)

    Returns:
        A tuple of (affected_teams, affected_assets):
        - affected_teams: List of dicts with team_id, team_name, assets
        - affected_assets: List of dicts with asset details
    """
    dep_asset = AssetDB.__table__.alias("dep_asset")
    dep_team = TeamDB.__table__.alias("dep_team")

    query = (
        select(
            AssetDependencyDB.dependent_asset_id,
            dep_asset.c.fqn,
            dep_asset.c.owner_team_id,
            dep_asset.c.owner_user_id,
            dep_team.c.name.label("team_name"),
            AssetDependencyDB.dependency_type,
        )
        .distinct()
        .join(dep_asset, AssetDependencyDB.dependent_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(dep_asset.c.deleted_at.is_(None))
    )
    if exclude_team_id:
        query = query.where(dep_asset.c.owner_team_id != exclude_team_id)

    downstream_result = await session.execute(query)

    affected_assets: list[dict[str, Any]] = []
    team_assets: dict[str, list[str]] = defaultdict(list)

    for row in downstream_result.all():
        dep_asset_id, fqn, owner_team_id, owner_user_id, team_name, dep_type = row
        asset_id_str = str(dep_asset_id)
        team_id_str = str(owner_team_id)

        affected_assets.append(
            {
                "asset_id": asset_id_str,
                "asset_fqn": fqn,
                "owner_team_id": team_id_str,
                "owner_team_name": team_name,
                "owner_user_id": str(owner_user_id) if owner_user_id else None,
                "dependency_type": str(dep_type) if dep_type else "CONSUMES",
            }
        )
        team_assets[team_id_str].append(asset_id_str)

    # Fetch user names for assets with owner_user_id
    user_ids_to_lookup = {
        UUID(a["owner_user_id"]) for a in affected_assets if a.get("owner_user_id")
    }
    users_map: dict[UUID, str] = {}
    if user_ids_to_lookup:
        users_result = await session.execute(
            select(UserDB.id, UserDB.name).where(UserDB.id.in_(user_ids_to_lookup))
        )
        users_map = {uid: name for uid, name in users_result.all()}

    for asset_dict in affected_assets:
        if asset_dict.get("owner_user_id"):
            user_id = UUID(asset_dict["owner_user_id"])
            asset_dict["owner_user_name"] = users_map.get(user_id)

    # Build affected teams list
    affected_teams: list[dict[str, Any]] = []
    for team_id_str, asset_ids in team_assets.items():
        team_name = next(
            (a["owner_team_name"] for a in affected_assets if a["owner_team_id"] == team_id_str),
            "Unknown",
        )
        affected_teams.append(
            {
                "team_id": team_id_str,
                "team_name": team_name,
                "assets": asset_ids,
            }
        )

    return affected_teams, affected_assets
