"""Teams API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
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
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.config import settings
from tessera.db import TeamDB, get_session
from tessera.models import Team, TeamCreate, TeamUpdate
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

    Requires read scope.
    """
    query = select(TeamDB).where(TeamDB.deleted_at.is_(None))
    if name:
        query = query.where(TeamDB.name.ilike(f"%{name}%"))
    query = query.order_by(TeamDB.name)

    return await paginate(session, query, params, response_model=Team)


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
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft delete a team.

    Requires admin scope.
    """
    result = await session.execute(
        select(TeamDB).where(TeamDB.id == team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

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
