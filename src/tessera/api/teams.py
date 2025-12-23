"""Teams API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead
from tessera.api.errors import (
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.config import settings
from tessera.db import AssetDB, TeamDB, UserDB, get_session
from tessera.models import Team, TeamCreate, TeamUpdate, User
from tessera.models.enums import APIKeyScope
from tessera.services.cache import team_cache

router = APIRouter()

# API key header for bootstrap check
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def _verify_can_create_team(
    authorization: str | None = Security(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Verify the request is authorized to create a team.

    Team creation is allowed if:
    1. Auth is disabled (development mode)
    2. Using the bootstrap API key
    3. Using a valid API key with admin scope

    Raises HTTPException if not authorized.
    """
    # Auth disabled = always allowed
    if settings.auth_disabled:
        return

    if not authorization:
        raise UnauthorizedError("Authorization required", code=ErrorCode.UNAUTHORIZED)

    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Use 'Bearer <key>' format", code=ErrorCode.UNAUTHORIZED)

    key = authorization[7:]

    # Check bootstrap key
    if settings.bootstrap_api_key and key == settings.bootstrap_api_key:
        return

    # Check regular API key with admin scope
    from tessera.services.auth import validate_api_key

    result = await validate_api_key(session, key)
    if not result:
        raise UnauthorizedError("Invalid or expired API key", code=ErrorCode.INVALID_API_KEY)

    api_key_db, _ = result
    scopes = [APIKeyScope(s) for s in api_key_db.scopes]
    if APIKeyScope.ADMIN not in scopes:
        raise ForbiddenError("Admin scope required", code=ErrorCode.INSUFFICIENT_SCOPE)


@router.post("", response_model=Team, status_code=201)
@limit_write
async def create_team(
    request: Request,
    team: TeamCreate,
    _: None = Depends(_verify_can_create_team),
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Create a new team.

    Requires admin scope or bootstrap API key.
    """
    db_team = TeamDB(name=team.name, metadata_=team.metadata)
    session.add(db_team)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_TEAM,
            f"Team with name '{team.name}' already exists",
        )
    await session.refresh(db_team)
    return db_team


@router.get("")
@limit_read
async def list_teams(
    request: Request,
    auth: Auth,
    name: str | None = Query(None, description="Filter by name pattern (case-insensitive)"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all teams with filtering and pagination.

    Requires read scope. Returns teams with asset counts.
    """
    # Build base query with filters
    base_query = select(TeamDB).where(TeamDB.deleted_at.is_(None))
    if name:
        base_query = base_query.where(TeamDB.name.ilike(f"%{name}%"))

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Main query with pagination
    query = base_query.order_by(TeamDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    teams = list(result.scalars().all())

    # Batch fetch asset counts for all teams
    team_ids = [t.id for t in teams]
    asset_counts: dict[UUID, int] = {}
    if team_ids:
        counts_result = await session.execute(
            select(AssetDB.owner_team_id, func.count(AssetDB.id))
            .where(AssetDB.owner_team_id.in_(team_ids))
            .where(AssetDB.deleted_at.is_(None))
            .group_by(AssetDB.owner_team_id)
        )
        asset_counts = {team_id: count for team_id, count in counts_result.all()}

    results = []
    for team in teams:
        team_dict = Team.model_validate(team).model_dump()
        team_dict["asset_count"] = asset_counts.get(team.id, 0)
        results.append(team_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get("/{team_id}", response_model=Team)
@limit_read
async def get_team(
    request: Request,
    team_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Get a team by ID.

    Requires read scope.
    """
    result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")
    return team


@router.patch("/{team_id}", response_model=Team)
@router.put("/{team_id}", response_model=Team)
@limit_write
async def update_team(
    request: Request,
    team_id: UUID,
    update: TeamUpdate,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Update a team.

    Requires admin scope.
    """
    result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    if update.name is not None:
        team.name = update.name
    if update.metadata is not None:
        team.metadata_ = update.metadata

    await session.flush()
    await session.refresh(team)
    # Invalidate cache
    await team_cache.delete(str(team_id))
    return team


@router.delete("/{team_id}", status_code=204)
@limit_write
async def delete_team(
    request: Request,
    team_id: UUID,
    auth: Auth,
    force: bool = Query(False, description="Force delete even if team has assets"),
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft delete a team.

    Requires admin scope. Will fail if team owns assets unless force=true.
    Use /teams/{team_id}/reassign-assets to reassign assets first.
    """
    result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    # Check if team has assets
    asset_count_result = await session.execute(
        select(func.count(AssetDB.id))
        .where(AssetDB.owner_team_id == team_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    asset_count = asset_count_result.scalar() or 0

    if asset_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TEAM_HAS_ASSETS",
                "message": f"Team owns {asset_count} asset(s). Reassign or use force=true.",
                "asset_count": asset_count,
            },
        )

    team.deleted_at = datetime.now(UTC)
    await session.flush()

    # Invalidate cache
    await team_cache.delete(str(team_id))


@router.post("/{team_id}/restore", response_model=Team)
@limit_write
async def restore_team(
    request: Request,
    team_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Restore a soft-deleted team.

    Requires admin scope.
    """
    result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    if team.deleted_at is None:
        return team

    team.deleted_at = None
    await session.flush()
    await session.refresh(team)

    # Invalidate cache
    await team_cache.delete(str(team_id))

    return team


@router.get("/{team_id}/members")
@limit_read
async def list_team_members(
    request: Request,
    team_id: UUID,
    auth: Auth,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all members of a team.

    Requires read scope.
    """
    # Verify team exists
    result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Build query for team members
    base_query = (
        select(UserDB).where(UserDB.team_id == team_id).where(UserDB.deactivated_at.is_(None))
    )

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = base_query.order_by(UserDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    users = list(result.scalars().all())

    results = [User.model_validate(u).model_dump() for u in users]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


class ReassignAssetsRequest(BaseModel):
    """Request body for reassigning assets."""

    target_team_id: UUID
    asset_ids: list[UUID] | None = None  # If None, reassign all assets


@router.post("/{team_id}/reassign-assets")
@limit_write
async def reassign_team_assets(
    request: Request,
    team_id: UUID,
    reassign: ReassignAssetsRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Reassign assets from this team to another team.

    Requires admin scope. Can reassign all assets or specific ones by ID.
    """
    # Verify source team exists
    source_result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    source_team = source_result.scalar_one_or_none()
    if not source_team:
        raise HTTPException(status_code=404, detail="Source team not found")

    # Verify target team exists
    target_result = await session.execute(
        select(TeamDB)
        .where(TeamDB.id == reassign.target_team_id)
        .where(TeamDB.deleted_at.is_(None))
    )
    target_team = target_result.scalar_one_or_none()
    if not target_team:
        raise HTTPException(status_code=404, detail="Target team not found")

    if team_id == reassign.target_team_id:
        raise HTTPException(status_code=400, detail="Source and target team cannot be the same")

    # Build query for assets to reassign
    query = (
        select(AssetDB).where(AssetDB.owner_team_id == team_id).where(AssetDB.deleted_at.is_(None))
    )

    if reassign.asset_ids:
        query = query.where(AssetDB.id.in_(reassign.asset_ids))

    assets_result = await session.execute(query)
    assets = list(assets_result.scalars().all())

    if not assets:
        return {
            "reassigned": 0,
            "source_team": {"id": str(team_id), "name": source_team.name},
            "target_team": {"id": str(reassign.target_team_id), "name": target_team.name},
        }

    # Reassign assets
    for asset in assets:
        asset.owner_team_id = reassign.target_team_id

    await session.flush()

    return {
        "reassigned": len(assets),
        "source_team": {"id": str(team_id), "name": source_team.name},
        "target_team": {"id": str(reassign.target_team_id), "name": target_team.name},
        "asset_ids": [str(a.id) for a in assets],
    }
