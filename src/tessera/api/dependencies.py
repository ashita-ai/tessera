"""Asset dependency and lineage endpoints."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db import (
    AssetDB,
    AssetDependencyDB,
    ContractDB,
    RegistrationDB,
    TeamDB,
    get_session,
)
from tessera.models import Dependency, DependencyCreate
from tessera.models.enums import APIKeyScope
from tessera.services.cache import asset_cache

router = APIRouter()


@router.post("/{asset_id}/dependencies", response_model=Dependency, status_code=201)
@limit_write
async def create_dependency(
    request: Request,
    asset_id: UUID,
    dependency: DependencyCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> AssetDependencyDB:
    """Register an upstream dependency for an asset."""
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only add dependencies to assets belonging to your team",
            },
        )

    result = await session.execute(
        select(AssetDB).where(AssetDB.id == dependency.depends_on_asset_id)
    )
    if not result.scalar_one_or_none():
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Dependency asset not found")

    if asset_id == dependency.depends_on_asset_id:
        raise BadRequestError("Asset cannot depend on itself", code=ErrorCode.SELF_DEPENDENCY)

    result = await session.execute(
        select(AssetDependencyDB)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
        .where(AssetDependencyDB.dependency_asset_id == dependency.depends_on_asset_id)
    )
    if result.scalar_one_or_none():
        raise DuplicateError(ErrorCode.DUPLICATE_DEPENDENCY, "Dependency already exists")

    db_dependency = AssetDependencyDB(
        dependent_asset_id=asset_id,
        dependency_asset_id=dependency.depends_on_asset_id,
        dependency_type=dependency.dependency_type,
    )
    session.add(db_dependency)
    await session.flush()
    await session.refresh(db_dependency)
    return db_dependency


@router.get("/{asset_id}/dependencies")
@limit_read
async def list_dependencies(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all upstream dependencies for an asset."""
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    if not asset_result.scalar_one_or_none():
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    query = select(AssetDependencyDB).where(AssetDependencyDB.dependent_asset_id == asset_id)
    return await paginate(session, query, params, response_model=Dependency)


@router.delete("/{asset_id}/dependencies/{dependency_id}", status_code=204)
@limit_write
async def delete_dependency(
    request: Request,
    asset_id: UUID,
    dependency_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an upstream dependency."""
    # First fetch the asset to check ownership
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot delete dependencies for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    result = await session.execute(
        select(AssetDependencyDB)
        .where(AssetDependencyDB.id == dependency_id)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    dependency = result.scalar_one_or_none()
    if not dependency:
        raise NotFoundError(ErrorCode.DEPENDENCY_NOT_FOUND, "Dependency not found")

    await session.delete(dependency)
    await session.flush()


@router.get("/{asset_id}/lineage")
@limit_read
async def get_lineage(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the complete dependency lineage for an asset."""
    cache_key = f"lineage:{asset_id}"
    cached = await asset_cache.get(cache_key)
    if cached:
        return dict(cached)

    result = await session.execute(
        select(AssetDB, TeamDB)
        .join(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .where(AssetDB.id == asset_id)
    )
    row = result.first()
    if not row:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")
    asset, owner_team = row

    dep_asset = AssetDB.__table__.alias("dep_asset")
    dep_team = TeamDB.__table__.alias("dep_team")

    upstream_result = await session.execute(
        select(
            AssetDependencyDB.dependency_asset_id,
            AssetDependencyDB.dependency_type,
            dep_asset.c.fqn,
            dep_team.c.name,
        )
        .join(dep_asset, AssetDependencyDB.dependency_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    upstream = [
        {
            "asset_id": str(dep_asset_id),
            "asset_fqn": fqn,
            "dependency_type": str(dep_type),
            "owner_team": team_name,
        }
        for dep_asset_id, dep_type, fqn, team_name in upstream_result.all()
    ]

    contracts_result = await session.execute(
        select(ContractDB.id).where(ContractDB.asset_id == asset_id)
    )
    contract_ids = [c for (c,) in contracts_result.all()]

    downstream: list[dict[str, Any]] = []
    if contract_ids:
        regs_result = await session.execute(
            select(RegistrationDB, TeamDB)
            .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
            .where(RegistrationDB.contract_id.in_(contract_ids))
        )
        rows = regs_result.all()

        team_regs: dict[UUID, list[tuple[RegistrationDB, TeamDB]]] = defaultdict(list)
        for reg, team in rows:
            team_regs[team.id].append((reg, team))

        for team_id, regs in team_regs.items():
            team_name = regs[0][1].name
            downstream.append(
                {
                    "team_id": str(team_id),
                    "team_name": team_name,
                    "registrations": [
                        {
                            "contract_id": str(r.contract_id),
                            "status": str(r.status),
                            "pinned_version": r.pinned_version,
                        }
                        for r, _ in regs
                    ],
                }
            )

    downstream_assets_result = await session.execute(
        select(
            AssetDependencyDB.dependent_asset_id,
            AssetDependencyDB.dependency_type,
            dep_asset.c.fqn,
            dep_team.c.name,
        )
        .join(dep_asset, AssetDependencyDB.dependent_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
    )
    downstream_assets = [
        {
            "asset_id": str(dep_asset_id),
            "asset_fqn": fqn,
            "dependency_type": str(dep_type),
            "owner_team": team_name,
        }
        for dep_asset_id, dep_type, fqn, team_name in downstream_assets_result.all()
    ]

    res = {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "owner_team_id": str(asset.owner_team_id),
        "owner_team_name": owner_team.name,
        "upstream": upstream,
        "downstream": downstream,
        "downstream_assets": downstream_assets,
    }

    await asset_cache.set(f"lineage:{asset_id}", res, ttl=300)
    return res
