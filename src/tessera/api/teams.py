"""Teams API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.db import TeamDB, get_session
from tessera.models import Team, TeamCreate, TeamUpdate

router = APIRouter()


@router.post("", response_model=Team, status_code=201)
async def create_team(
    team: TeamCreate,
    session: AsyncSession = Depends(get_session),
) -> TeamDB:
    """Create a new team."""
    db_team = TeamDB(name=team.name, metadata_=team.metadata)
    session.add(db_team)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail=f"Team with name '{team.name}' already exists")
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
