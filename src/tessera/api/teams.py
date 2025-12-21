"""Teams API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.config import settings
from tessera.db import TeamDB, get_session
from tessera.models import Team, TeamCreate, TeamUpdate

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
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_API_KEY", "message": "Authorization required"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_AUTH_HEADER", "message": "Use 'Bearer <key>' format"},
        )

    key = authorization[7:]

    # Check bootstrap key
    if settings.bootstrap_api_key and key == settings.bootstrap_api_key:
        return

    # Check regular API key with admin scope
    from tessera.models.enums import APIKeyScope
    from tessera.services.auth import validate_api_key

    result = await validate_api_key(session, key)
    if not result:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "Invalid or expired API key"},
        )

    api_key_db, _ = result
    scopes = [APIKeyScope(s) for s in api_key_db.scopes]
    if APIKeyScope.ADMIN not in scopes:
        raise HTTPException(
            status_code=403,
            detail={"code": "INSUFFICIENT_SCOPE", "message": "Admin scope required"},
        )


@router.post("", response_model=Team, status_code=201)
async def create_team(
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
        raise HTTPException(status_code=409, detail=f"Team with name '{team.name}' already exists")
    await session.refresh(db_team)
    return db_team


@router.get("")
async def list_teams(
    name: str | None = Query(None, description="Filter by name pattern (case-insensitive)"),
    params: PaginationParams = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all teams with filtering and pagination."""
    query = select(TeamDB)
    if name:
        query = query.where(TeamDB.name.ilike(f"%{name}%"))
    query = query.order_by(TeamDB.name)

    return await paginate(session, query, params, response_model=Team)


@router.get("/{team_id}", response_model=Team)
async def get_team(
    team_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Get a team by ID."""
    result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.patch("/{team_id}", response_model=Team)
async def update_team(
    team_id: UUID,
    update: TeamUpdate,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Update a team."""
    result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if update.name is not None:
        team.name = update.name
    if update.metadata is not None:
        team.metadata_ = update.metadata

    await session.flush()
    await session.refresh(team)
    return team
