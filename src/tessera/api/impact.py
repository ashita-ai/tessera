"""Impact analysis endpoint."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError, NotFoundError
from tessera.api.rate_limit import limit_expensive, limit_read
from tessera.config import settings
from tessera.db import (
    AssetDB,
    AssetDependencyDB,
    ContractDB,
    RegistrationDB,
    TeamDB,
    get_session,
)
from tessera.models.enums import APIKeyScope, ContractStatus, RegistrationStatus
from tessera.services import diff_schemas, validate_json_schema

router = APIRouter()


# Maximum number of downstream assets to return from lineage traversal.
# Prevents unbounded memory usage on wide graphs. If the cap is reached,
# the response includes a `truncated` flag so callers know the result is partial.
MAX_LINEAGE_RESULTS = 500


async def get_downstream_assets_recursive(
    session: AsyncSession,
    root_asset_id: UUID,
    max_depth: int,
    max_results: int = MAX_LINEAGE_RESULTS,
) -> tuple[list[tuple[AssetDB, str, int]], bool]:
    """Fetch all downstream assets using iterative batch fetching.

    Uses breadth-first traversal with cycle detection. Returns early if the
    result set exceeds max_results to prevent unbounded memory usage.

    Args:
        session: Database session.
        root_asset_id: Starting asset ID.
        max_depth: Maximum traversal depth.
        max_results: Maximum results to return before truncating.

    Returns:
        Tuple of (results, truncated) where results is a list of
        (asset, dependency_type, depth) tuples and truncated indicates
        whether the traversal was cut short.
    """
    # For SQLite compatibility (used in tests), we use iterative batch fetching
    # PostgreSQL could use a true recursive CTE, but this approach works everywhere
    visited: set[UUID] = {root_asset_id}
    results: list[tuple[AssetDB, str, int]] = []
    current_ids = [root_asset_id]
    truncated = False

    for current_depth in range(1, max_depth + 1):
        if not current_ids:
            break

        # Batch fetch all downstream assets for current level
        deps_query = (
            select(AssetDB, AssetDependencyDB.dependency_type)
            .join(AssetDependencyDB, AssetDependencyDB.dependent_asset_id == AssetDB.id)
            .where(AssetDependencyDB.dependency_asset_id.in_(current_ids))
            .where(AssetDependencyDB.deleted_at.is_(None))
            .where(AssetDB.deleted_at.is_(None))
        )
        deps_result = await session.execute(deps_query)
        downstream = deps_result.all()

        next_ids = []
        for asset, dep_type in downstream:
            if asset.id not in visited:
                visited.add(asset.id)
                results.append((asset, str(dep_type), current_depth))
                next_ids.append(asset.id)

                if len(results) >= max_results:
                    truncated = True
                    break

        if truncated:
            break
        current_ids = next_ids

    return results, truncated


async def get_impacted_consumers_batch(
    session: AsyncSession,
    asset_ids: list[UUID],
) -> dict[UUID, list[tuple[RegistrationDB, TeamDB]]]:
    """Batch fetch all active registrations for multiple assets.

    Args:
        session: Database session.
        asset_ids: List of asset IDs to check.

    Returns:
        Dict mapping asset_id to list of (registration, team) tuples.
    """
    if not asset_ids:
        return {}

    # Get all active contracts for the assets
    contracts_query = (
        select(ContractDB)
        .where(ContractDB.asset_id.in_(asset_ids))
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    contracts_result = await session.execute(contracts_query)
    contracts = contracts_result.scalars().all()

    if not contracts:
        return {}

    contract_to_asset = {c.id: c.asset_id for c in contracts}
    contract_ids = list(contract_to_asset.keys())

    # Batch fetch all registrations with team info
    regs_query = (
        select(RegistrationDB, TeamDB)
        .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
        .where(RegistrationDB.contract_id.in_(contract_ids))
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        .where(TeamDB.deleted_at.is_(None))
    )
    regs_result = await session.execute(regs_query)

    result: dict[UUID, list[tuple[RegistrationDB, TeamDB]]] = {aid: [] for aid in asset_ids}
    for reg, team in regs_result.all():
        asset_id = contract_to_asset.get(reg.contract_id)
        if asset_id:
            result[asset_id].append((reg, team))

    return result


@router.post("/{asset_id}/impact")
@limit_read
@limit_expensive  # Per-team rate limit for expensive lineage analysis
async def analyze_impact(
    request: Request,
    asset_id: UUID,
    proposed_schema: dict[str, Any],
    auth: Auth,
    depth: int = Query(
        settings.impact_depth_default,
        ge=1,
        le=settings.impact_depth_max,
    ),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyze the impact of a proposed schema change."""
    is_valid, errors = validate_json_schema(proposed_schema)
    if not is_valid:
        raise BadRequestError(
            f"Invalid JSON Schema: {'; '.join(errors) if errors else 'Schema validation failed'}"
        )

    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot analyze impact for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    if not current_contract:
        return {
            "change_type": "minor",
            "breaking_changes": [],
            "impacted_consumers": [],
            "impacted_assets": [],
            "safe_to_publish": True,
        }

    diff_result = diff_schemas(current_contract.schema_def, proposed_schema)
    breaking = diff_result.breaking_for_mode(current_contract.compatibility_mode)

    # Use optimized batch fetching instead of N individual queries
    downstream_assets, lineage_truncated = await get_downstream_assets_recursive(
        session, asset_id, depth
    )

    # Build list of impacted assets
    impacted_assets: list[dict[str, Any]] = [
        {
            "asset_id": str(ds_asset.id),
            "fqn": ds_asset.fqn,
            "dependency_type": dep_type,
            "depth": ds_depth,
        }
        for ds_asset, dep_type, ds_depth in downstream_assets
    ]

    # Batch fetch all impacted consumers
    all_asset_ids = [asset_id] + [ds_asset.id for ds_asset, _, _ in downstream_assets]
    consumers_by_asset = await get_impacted_consumers_batch(session, all_asset_ids)

    # Collect unique impacted teams
    impacted_teams: dict[UUID, dict[str, Any]] = {}
    for check_asset_id in all_asset_ids:
        asset_depth = (
            0
            if check_asset_id == asset_id
            else next((d for a, _, d in downstream_assets if a.id == check_asset_id), 1)
        )
        for reg, team in consumers_by_asset.get(check_asset_id, []):
            if team.id not in impacted_teams:
                impacted_teams[team.id] = {
                    "team_id": str(team.id),
                    "team_name": team.name,
                    "status": str(reg.status),
                    "pinned_version": reg.pinned_version,
                    "depth": asset_depth,
                }

    result: dict[str, Any] = {
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "impacted_consumers": list(impacted_teams.values()),
        "impacted_assets": impacted_assets,
        "safe_to_publish": len(breaking) == 0,
        "traversal_depth": depth,
    }
    if lineage_truncated:
        result["truncated"] = True
        result["truncated_message"] = (
            f"Lineage traversal returned the maximum {MAX_LINEAGE_RESULTS} assets. "
            "The full downstream graph may be larger."
        )
    return result
