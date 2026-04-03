"""Users API endpoints."""

from datetime import UTC, datetime
from uuid import UUID

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from tessera.api.auth import Auth, RequireAdmin, RequireRead
from tessera.api.errors import DuplicateError, ErrorCode, NotFoundError
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import PaginatedResponse
from tessera.db import TeamDB, UserDB, get_session
from tessera.models import User, UserCreate, UserUpdate, UserWithTeam
from tessera.models.enums import UserType
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.batch import fetch_asset_counts_by_user, fetch_team_names


class UserWithTeamAndAssets(TypedDict, total=False):
    """User with team name and asset count for list responses."""

    id: UUID
    username: str
    email: str | None
    name: str
    user_type: str
    team_id: UUID | None
    role: str
    created_at: datetime
    metadata: dict[str, object]
    notification_preferences: dict[str, object]
    team_name: str | None
    asset_count: int


_hasher = PasswordHasher()

router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    422: {"description": "Validation error — invalid request body"},
}


@router.post(
    "",
    response_model=User,
    status_code=201,
    responses={k: _E[k] for k in (400, 401, 403, 404, 409)},
)
@limit_write
async def create_user(
    request: Request,
    user: UserCreate,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> UserDB:
    """Create a new user (human or bot).

    Requires admin scope. Bot users cannot have passwords.
    """
    # Verify team exists if provided
    if user.team_id:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == user.team_id).where(TeamDB.deleted_at.is_(None))
        )
        if not team_result.scalar_one_or_none():
            raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    normalized_email = user.email.lower().strip() if user.email else None

    # Hash password if provided
    password_hash = None
    if user.password:
        password_hash = _hasher.hash(user.password)

    db_user = UserDB(
        username=user.username,
        email=normalized_email,
        name=user.name,
        user_type=user.user_type,
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
        raise DuplicateError(
            ErrorCode.DUPLICATE_USER,
            f"User with username '{user.username}' already exists",
        )
    await session.refresh(db_user)

    # Audit log user creation
    await audit.log_event(
        session=session,
        entity_type="user",
        entity_id=db_user.id,
        action=AuditAction.USER_CREATED,
        payload={
            "username": user.username,
            "user_type": user.user_type.value,
            "name": user.name,
            "team_id": str(user.team_id) if user.team_id else None,
        },
    )

    return db_user


@router.get("", responses={k: _E[k] for k in (401, 403)})
@limit_read
async def list_users(
    request: Request,
    auth: Auth,
    team_id: UUID | None = Query(None, description="Filter by team ID"),
    username: str | None = Query(None, description="Filter by username pattern (case-insensitive)"),
    email: str | None = Query(None, description="Filter by email pattern (case-insensitive)"),
    name: str | None = Query(None, description="Filter by name pattern (case-insensitive)"),
    user_type: UserType | None = Query(None, description="Filter by user type (human or bot)"),
    include_deactivated: bool = Query(False, description="Include deactivated users"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[UserWithTeamAndAssets]:
    """List all users with filtering and pagination.

    Requires read scope. Returns users with asset counts.
    """
    # Build base query with filters
    base_query = select(UserDB)
    if not include_deactivated:
        base_query = base_query.where(UserDB.deactivated_at.is_(None))
    if team_id:
        base_query = base_query.where(UserDB.team_id == team_id)
    if username:
        base_query = base_query.where(UserDB.username.ilike(f"%{username}%"))
    if email:
        base_query = base_query.where(UserDB.email.ilike(f"%{email}%"))
    if name:
        base_query = base_query.where(UserDB.name.ilike(f"%{name}%"))
    if user_type:
        base_query = base_query.where(UserDB.user_type == user_type)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Main query with pagination
    query = base_query.order_by(UserDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    users = list(result.scalars().all())

    # Batch fetch team names
    user_team_ids = [u.team_id for u in users if u.team_id]
    team_names = await fetch_team_names(session, user_team_ids)

    # Batch fetch asset counts for all users
    user_ids = [u.id for u in users]
    asset_counts = await fetch_asset_counts_by_user(session, user_ids)

    results: list[UserWithTeamAndAssets] = []
    for user in users:
        user_dict: UserWithTeamAndAssets = User.model_validate(user).model_dump()  # type: ignore[assignment]
        user_dict["team_name"] = team_names.get(user.team_id) if user.team_id else None
        user_dict["asset_count"] = asset_counts.get(user.id, 0)
        results.append(user_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/{user_id}",
    response_model=UserWithTeam,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_user(
    request: Request,
    user_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Get a user by ID.

    Requires read scope.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.id == user_id).where(UserDB.deactivated_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found")

    user_dict: dict[str, object] = User.model_validate(user).model_dump()

    # Get team name if user has a team
    if user.team_id:
        team_result = await session.execute(select(TeamDB.name).where(TeamDB.id == user.team_id))
        team_name = team_result.scalar_one_or_none()
        user_dict["team_name"] = team_name

    return user_dict


@router.patch(
    "/{user_id}",
    response_model=User,
    responses={k: _E[k] for k in (401, 403, 404, 409)},
)
@router.put(
    "/{user_id}",
    response_model=User,
    responses={k: _E[k] for k in (401, 403, 404, 409)},
)
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
        raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found")

    # Verify team exists if being changed
    if update.team_id is not None:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == update.team_id).where(TeamDB.deleted_at.is_(None))
        )
        if not team_result.scalar_one_or_none():
            raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    if update.username is not None:
        user.username = update.username  # already normalized by validator
    if update.email is not None:
        user.email = update.email.lower().strip()
    if update.name is not None:
        user.name = update.name
    if update.user_type is not None:
        # Enforce bot invariant: clear password_hash when switching to bot
        if update.user_type == UserType.BOT and user.password_hash is not None:
            user.password_hash = None
        user.user_type = update.user_type
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

    # Capture before flush — ORM object expires after rollback
    effective_username = update.username if update.username is not None else user.username
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_USER,
            f"User with username '{effective_username}' already exists",
        )
    await session.refresh(user)

    # Audit log user update
    await audit.log_event(
        session=session,
        entity_type="user",
        entity_id=user_id,
        action=AuditAction.USER_UPDATED,
        payload={
            "username_changed": update.username is not None,
            "email_changed": update.email is not None,
            "name_changed": update.name is not None,
            "team_changed": update.team_id is not None,
            "role_changed": update.role is not None,
            "user_type_changed": update.user_type is not None,
        },
    )

    return user


@router.delete(
    "/{user_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
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
        raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found")

    user.deactivated_at = datetime.now(UTC)
    await session.flush()

    # Audit log user deletion (deactivation)
    await audit.log_event(
        session=session,
        entity_type="user",
        entity_id=user_id,
        action=AuditAction.USER_DELETED,
        payload={"username": user.username, "name": user.name},
    )


@router.post(
    "/{user_id}/reactivate",
    response_model=User,
    responses={k: _E[k] for k in (401, 403, 404)},
)
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
        raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found")

    if user.deactivated_at is None:
        return user

    user.deactivated_at = None
    await session.flush()
    await session.refresh(user)

    # Audit log user reactivation
    await audit.log_event(
        session=session,
        entity_type="user",
        entity_id=user_id,
        action=AuditAction.USER_REACTIVATED,
        actor_id=auth.team_id,
        payload={"username": user.username, "name": user.name},
    )

    return user
