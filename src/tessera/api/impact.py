"""Impact analysis endpoint."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError, NotFoundError
from tessera.api.rate_limit import limit_read
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


@router.post("/{asset_id}/impact")
@limit_read
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

    visited_assets: set[UUID] = set()
    impacted_teams: dict[UUID, dict[str, Any]] = {}
    impacted_assets: list[dict[str, Any]] = []

    async def traverse(current_id: UUID, current_depth: int) -> None:
        if current_depth > depth or current_id in visited_assets:
            return
        visited_assets.add(current_id)

        c_result = await session.execute(
            select(ContractDB.id)
            .where(ContractDB.asset_id == current_id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .limit(1)
        )
        active_contract_id = c_result.scalar()

        if active_contract_id:
            regs_result = await session.execute(
                select(RegistrationDB, TeamDB)
                .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
                .where(RegistrationDB.contract_id == active_contract_id)
                .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
            )
            for reg, team in regs_result.all():
                if team.id not in impacted_teams:
                    impacted_teams[team.id] = {
                        "team_id": str(team.id),
                        "team_name": team.name,
                        "status": str(reg.status),
                        "pinned_version": reg.pinned_version,
                        "depth": current_depth,
                    }

        downstream_result = await session.execute(
            select(AssetDB, AssetDependencyDB.dependency_type)
            .join(AssetDependencyDB, AssetDependencyDB.dependent_asset_id == AssetDB.id)
            .where(AssetDependencyDB.dependency_asset_id == current_id)
        )
        for ds_asset, dep_type in downstream_result.all():
            if ds_asset.id not in visited_assets:
                impacted_assets.append(
                    {
                        "asset_id": str(ds_asset.id),
                        "fqn": ds_asset.fqn,
                        "dependency_type": str(dep_type),
                        "depth": current_depth,
                    }
                )
                await traverse(ds_asset.id, current_depth + 1)

    await traverse(asset_id, 1)
    impacted_assets = [a for a in impacted_assets if a["asset_id"] != str(asset_id)]

    return {
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "impacted_consumers": list(impacted_teams.values()),
        "impacted_assets": impacted_assets,
        "safe_to_publish": len(breaking) == 0,
        "traversal_depth": depth,
    }
