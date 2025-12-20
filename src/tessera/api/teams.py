"""Teams API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
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
    await session.flush()
    await session.refresh(db_team)
    return db_team


@router.get("", response_model=list[Team])
async def list_teams(
    session: AsyncSession = Depends(get_session),
) -> list[TeamDB]:
    """List all teams."""
    result = await session.execute(select(TeamDB))
    return list(result.scalars().all())


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
