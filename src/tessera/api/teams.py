"""Teams API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all teams with filtering and pagination."""
    query = select(TeamDB)
    if name:
        query = query.where(TeamDB.name.ilike(f"%{name}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(TeamDB.name)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    teams = result.scalars().all()

    return {
        "results": [Team.model_validate(t).model_dump() for t in teams],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
