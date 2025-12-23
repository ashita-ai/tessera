"""Users API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db import AssetDB, TeamDB, UserDB, get_session
from tessera.models import User, UserCreate, UserUpdate, UserWithTeam

_hasher = PasswordHasher()

router = APIRouter()


@router.post("", response_model=User, status_code=201)
@limit_write
async def create_user(
    request: Request,
    user: UserCreate,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> UserDB:
    """Create a new user.

    Requires admin scope.
    """
    # Verify team exists if provided
    if user.team_id:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == user.team_id).where(TeamDB.deleted_at.is_(None))
        )
        if not team_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Team not found")

    # Hash password if provided
    password_hash = None
    if user.password:
        password_hash = _hasher.hash(user.password)

    db_user = UserDB(
        email=user.email,
        name=user.name,
        team_id=user.team_id,
        password_hash=password_hash,
        role=user.role,
        metadata_=user.metadata,
    )
    session.add(db_user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"User with email '{user.email}' already exists"
        )
    await session.refresh(db_user)
    return db_user


@router.get("")
@limit_read
async def list_users(
    request: Request,
    auth: Auth,
    team_id: UUID | None = Query(None, description="Filter by team ID"),
    email: str | None = Query(None, description="Filter by email pattern (case-insensitive)"),
    name: str | None = Query(None, description="Filter by name pattern (case-insensitive)"),
    include_deactivated: bool = Query(False, description="Include deactivated users"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all users with filtering and pagination.

    Requires read scope. Returns users with asset counts.
    """
    # Build base query with filters
    base_query = select(UserDB)
    if not include_deactivated:
        base_query = base_query.where(UserDB.deactivated_at.is_(None))
    if team_id:
        base_query = base_query.where(UserDB.team_id == team_id)
    if email:
        base_query = base_query.where(UserDB.email.ilike(f"%{email}%"))
    if name:
        base_query = base_query.where(UserDB.name.ilike(f"%{name}%"))

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Main query with pagination
    query = base_query.order_by(UserDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    users = list(result.scalars().all())

    # Batch fetch team names
    team_ids = [u.team_id for u in users if u.team_id]
    team_names: dict[UUID, str] = {}
    if team_ids:
        teams_result = await session.execute(
            select(TeamDB.id, TeamDB.name).where(TeamDB.id.in_(team_ids))
        )
        team_names = {team_id: name for team_id, name in teams_result.all()}

    # Batch fetch asset counts for all users
    user_ids = [u.id for u in users]
    asset_counts: dict[UUID, int] = {}
    if user_ids:
        counts_result = await session.execute(
            select(AssetDB.owner_user_id, func.count(AssetDB.id))
            .where(AssetDB.owner_user_id.in_(user_ids))
            .where(AssetDB.deleted_at.is_(None))
            .group_by(AssetDB.owner_user_id)
        )
        asset_counts = {user_id: count for user_id, count in counts_result.all()}

    results = []
    for user in users:
        user_dict = User.model_validate(user).model_dump()
        user_dict["team_name"] = team_names.get(user.team_id) if user.team_id else None
        user_dict["asset_count"] = asset_counts.get(user.id, 0)
        results.append(user_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get("/{user_id}", response_model=UserWithTeam)
@limit_read
async def get_user(
    request: Request,
    user_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a user by ID.

    Requires read scope.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.id == user_id).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_dict = User.model_validate(user).model_dump()

    # Get team name if user has a team
    if user.team_id:
        team_result = await session.execute(select(TeamDB.name).where(TeamDB.id == user.team_id))
        team_name = team_result.scalar_one_or_none()
        user_dict["team_name"] = team_name

    return user_dict


@router.patch("/{user_id}", response_model=User)
@router.put("/{user_id}", response_model=User)
@limit_write
async def update_user(
    request: Request,
    user_id: UUID,
    update: UserUpdate,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> UserDB:
    """Update a user.

    Requires admin scope.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.id == user_id).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify team exists if being changed
    if update.team_id is not None:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == update.team_id).where(TeamDB.deleted_at.is_(None))
        )
        if not team_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Team not found")

    if update.email is not None:
        user.email = update.email
    if update.name is not None:
        user.name = update.name
    if update.team_id is not None:
        user.team_id = update.team_id
    if update.password is not None:
        user.password_hash = _hasher.hash(update.password)
    if update.role is not None:
        user.role = update.role
    if update.notification_preferences is not None:
        user.notification_preferences = update.notification_preferences
    if update.metadata is not None:
        user.metadata_ = update.metadata

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"User with email '{update.email}' already exists"
        )
    await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
@limit_write
async def deactivate_user(
    request: Request,
    user_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Deactivate a user (soft delete).

    Requires admin scope.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.id == user_id).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.deactivated_at = datetime.now(UTC)
    await session.flush()


@router.post("/{user_id}/reactivate", response_model=User)
@limit_write
async def reactivate_user(
    request: Request,
    user_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> UserDB:
    """Reactivate a deactivated user.

    Requires admin scope.
    """
    result = await session.execute(select(UserDB).where(UserDB.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.deactivated_at is None:
        return user

    user.deactivated_at = None
    await session.flush()
    await session.refresh(user)
    return user
