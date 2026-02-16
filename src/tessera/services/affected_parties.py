"""Service for computing affected parties from lineage.

This module provides functions to discover teams and assets that will be affected
by changes to an asset, based on dependency relationships (both explicit and
via metadata.depends_on).
"""

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, AssetDependencyDB, TeamDB, UserDB


async def get_affected_parties(
    session: AsyncSession,
    asset_id: UUID,
    exclude_team_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get teams and assets affected by changes to this asset via lineage.

    Discovers downstream dependencies from:
    1. The dependencies table (explicit asset-to-asset relationships)
    2. The metadata.depends_on field (implicit relationships from dbt sync)

    Args:
        session: Database session
        asset_id: The asset being changed
        exclude_team_id: Optional team ID to exclude (typically the asset owner)

    Returns:
        A tuple of (affected_teams, affected_assets):
        - affected_teams: List of dicts with team_id, team_name, assets
        - affected_assets: List of dicts with asset details
    """
    # Get the asset being changed (exclude soft-deleted assets)
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        return [], []

    # Track affected assets and which teams own them
    affected_assets: list[dict[str, Any]] = []
    team_assets: dict[str, list[str]] = defaultdict(list)  # team_id -> [asset_ids]
    seen_asset_ids: set[str] = set()

    # 1. Query dependencies table for assets that depend on this asset
    dep_asset = AssetDB.__table__.alias("dep_asset")
    dep_team = TeamDB.__table__.alias("dep_team")

    downstream_result = await session.execute(
        select(
            AssetDependencyDB.dependent_asset_id,
            dep_asset.c.fqn,
            dep_asset.c.owner_team_id,
            dep_asset.c.owner_user_id,
            dep_team.c.name.label("team_name"),
        )
        .join(dep_asset, AssetDependencyDB.dependent_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(dep_asset.c.deleted_at.is_(None))
    )

    for row in downstream_result.all():
        dep_asset_id, fqn, owner_team_id, owner_user_id, team_name = row
        asset_id_str = str(dep_asset_id)
        team_id_str = str(owner_team_id)

        # Skip if excluding this team
        if exclude_team_id and owner_team_id == exclude_team_id:
            continue

        if asset_id_str not in seen_asset_ids:
            seen_asset_ids.add(asset_id_str)
            affected_assets.append(
                {
                    "asset_id": asset_id_str,
                    "asset_fqn": fqn,
                    "owner_team_id": team_id_str,
                    "owner_team_name": team_name,
                    "owner_user_id": str(owner_user_id) if owner_user_id else None,
                }
            )
            team_assets[team_id_str].append(asset_id_str)

    # 2. Check metadata.depends_on for assets not in dependencies table.
    # Use a LIKE pre-filter on the JSON metadata column to avoid loading every
    # asset into Python. The LIKE filter is not perfectly precise (it matches
    # substrings) but eliminates the vast majority of rows before the Python
    # check, turning O(N) into O(matches).
    fqn_pattern = f'%"{asset.fqn}"%'
    metadata_query = (
        select(AssetDB, TeamDB)
        .join(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.id != asset_id)
        .where(AssetDB.metadata_.cast(String).like(fqn_pattern))
    )
    if exclude_team_id:
        metadata_query = metadata_query.where(AssetDB.owner_team_id != exclude_team_id)

    metadata_result = await session.execute(metadata_query)

    for downstream_asset, downstream_team in metadata_result.all():
        depends_on = downstream_asset.metadata_.get("depends_on", [])
        if asset.fqn in depends_on:
            asset_id_str = str(downstream_asset.id)
            team_id_str = str(downstream_asset.owner_team_id)

            if asset_id_str not in seen_asset_ids:
                seen_asset_ids.add(asset_id_str)
                affected_assets.append(
                    {
                        "asset_id": asset_id_str,
                        "asset_fqn": downstream_asset.fqn,
                        "owner_team_id": team_id_str,
                        "owner_team_name": downstream_team.name,
                        "owner_user_id": str(downstream_asset.owner_user_id)
                        if downstream_asset.owner_user_id
                        else None,
                    }
                )
                team_assets[team_id_str].append(asset_id_str)

    # 3. Fetch user names for assets with owner_user_id
    user_ids_to_lookup = {
        UUID(a["owner_user_id"]) for a in affected_assets if a.get("owner_user_id")
    }
    users_map: dict[UUID, str] = {}
    if user_ids_to_lookup:
        users_result = await session.execute(
            select(UserDB.id, UserDB.name).where(UserDB.id.in_(user_ids_to_lookup))
        )
        users_map = {uid: name for uid, name in users_result.all()}

    # Add user names to affected assets
    for asset_dict in affected_assets:
        if asset_dict.get("owner_user_id"):
            user_id = UUID(asset_dict["owner_user_id"])
            asset_dict["owner_user_name"] = users_map.get(user_id)

    # 4. Build affected teams list from aggregated data
    affected_teams: list[dict[str, Any]] = []
    for team_id_str, asset_ids in team_assets.items():
        # Get team name from any asset in this team's list
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
