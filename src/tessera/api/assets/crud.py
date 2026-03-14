"""Asset CRUD endpoints: create, get, update, delete, restore."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import AssetWithOwnerInfo
from tessera.db import AssetDB, TeamDB, UserDB, get_session
from tessera.models import Asset, AssetCreate, AssetUpdate
from tessera.models.enums import APIKeyScope
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.cache import (
    asset_cache,
    cache_asset,
    get_cached_asset,
    invalidate_asset,
)

from .helpers import _E, _get_team_name

router = APIRouter()


@router.post(
    "",
    response_model=Asset,
    status_code=201,
    responses={k: _E[k] for k in (400, 401, 403, 404, 409)},
)
@limit_write
async def create_asset(
    request: Request,
    asset: AssetCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Create a new asset.

    Requires write scope.
    """
    # Validate owner team exists first (needed for better error messages)
    result = await session.execute(select(TeamDB).where(TeamDB.id == asset.owner_team_id))
    target_team = result.scalar_one_or_none()
    if not target_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

    # Resource-level auth: must own the team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        raise ForbiddenError(
            f"Cannot create asset for team '{target_team.name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to create assets for other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Validate owner user exists and belongs to owner team if provided
    if asset.owner_user_id:
        user_result = await session.execute(
            select(UserDB)
            .where(UserDB.id == asset.owner_user_id)
            .where(UserDB.deactivated_at.is_(None))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "Owner user not found")
        if user.team_id != asset.owner_team_id:
            raise BadRequestError(
                "Owner user must belong to the owner team",
                code=ErrorCode.USER_TEAM_MISMATCH,
            )

    # Check for duplicate FQN
    existing = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == asset.fqn)
        .where(AssetDB.environment == asset.environment)
        .where(AssetDB.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise DuplicateError(
            ErrorCode.DUPLICATE_ASSET,
            f"Asset '{asset.fqn}' already exists in environment '{asset.environment}'",
        )

    db_asset = AssetDB(
        fqn=asset.fqn,
        owner_team_id=asset.owner_team_id,
        owner_user_id=asset.owner_user_id,
        environment=asset.environment,
        resource_type=asset.resource_type,
        guarantee_mode=asset.guarantee_mode,
        semver_mode=asset.semver_mode,
        metadata_=asset.metadata,
        tags=asset.tags,
    )
    session.add(db_asset)
    try:
        await session.flush()
    except IntegrityError:
        raise DuplicateError(
            ErrorCode.DUPLICATE_ASSET, f"Asset with FQN '{asset.fqn}' already exists"
        )
    await session.refresh(db_asset)

    # Audit log asset creation
    await audit.log_event(
        session=session,
        entity_type="asset",
        entity_id=db_asset.id,
        action=AuditAction.ASSET_CREATED,
        actor_id=asset.owner_team_id,
        payload={"fqn": asset.fqn, "environment": asset.environment},
    )

    return db_asset


@router.get("/{asset_id}", responses={k: _E[k] for k in (401, 403, 404)})
@limit_read
async def get_asset(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> AssetWithOwnerInfo:
    """Get an asset by ID.

    Requires read scope. Returns asset with owner team and user names.
    """
    # Try cache first
    cached = await get_cached_asset(str(asset_id))
    if cached:
        return cached  # type: ignore[return-value]

    # Query with joins to get team and user names
    result = await session.execute(
        select(
            AssetDB,
            TeamDB.name.label("team_name"),
            UserDB.name.label("user_name"),
            UserDB.email.label("user_email"),
        )
        .outerjoin(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .outerjoin(UserDB, AssetDB.owner_user_id == UserDB.id)
        .where(AssetDB.id == asset_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    asset, team_name, user_name, user_email = row
    asset_dict: AssetWithOwnerInfo = Asset.model_validate(asset).model_dump()  # type: ignore[assignment]
    asset_dict["owner_team_name"] = team_name
    asset_dict["owner_user_name"] = user_name
    asset_dict["owner_user_email"] = user_email

    # Cache result
    await cache_asset(str(asset_id), asset_dict)  # type: ignore[arg-type]

    return asset_dict


@router.patch(
    "/{asset_id}",
    response_model=Asset,
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_write
async def update_asset(
    request: Request,
    asset_id: UUID,
    update: AssetUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Update an asset.

    Requires write scope.
    """
    result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        asset_team_name = await _get_team_name(session, asset.owner_team_id)
        raise ForbiddenError(
            f"Cannot update asset '{asset.fqn}' owned by team '{asset_team_name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to update assets for other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    if update.fqn is not None:
        asset.fqn = update.fqn
    if update.environment is not None:
        asset.environment = update.environment
    if update.resource_type is not None:
        asset.resource_type = update.resource_type
    if update.guarantee_mode is not None:
        asset.guarantee_mode = update.guarantee_mode
    if update.semver_mode is not None:
        asset.semver_mode = update.semver_mode
    if update.metadata is not None:
        asset.metadata_ = update.metadata
    if update.tags is not None:
        asset.tags = update.tags

    # Handle owner_team_id and owner_user_id together for validation
    new_team_id = update.owner_team_id if update.owner_team_id is not None else asset.owner_team_id
    new_user_id = update.owner_user_id if update.owner_user_id is not None else asset.owner_user_id

    # If user is being set/changed, validate they belong to the (new) team
    if new_user_id is not None:
        user_result = await session.execute(
            select(UserDB).where(UserDB.id == new_user_id).where(UserDB.deactivated_at.is_(None))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "Owner user not found")
        if user.team_id != new_team_id:
            raise BadRequestError(
                "Owner user must belong to the owner team",
                code=ErrorCode.USER_TEAM_MISMATCH,
            )

    if update.owner_team_id is not None:
        asset.owner_team_id = update.owner_team_id
    if update.owner_user_id is not None:
        asset.owner_user_id = update.owner_user_id

    await session.flush()
    await session.refresh(asset)

    # Audit log asset update
    await audit.log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_id,
        action=AuditAction.ASSET_UPDATED,
        actor_id=auth.team_id,
        payload={
            "fqn_changed": update.fqn is not None,
            "owner_changed": update.owner_team_id is not None or update.owner_user_id is not None,
        },
    )

    # Invalidate asset and contract caches
    await invalidate_asset(str(asset_id))

    return asset


@router.delete(
    "/{asset_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def delete_asset(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft delete an asset.

    Requires write scope. Resource-level auth: must own the asset's team or be admin.
    """
    result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resource-level auth
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        asset_team_name = await _get_team_name(session, asset.owner_team_id)
        raise ForbiddenError(
            f"Cannot delete asset '{asset.fqn}' owned by team '{asset_team_name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to delete assets for other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    asset.deleted_at = datetime.now(UTC)
    await session.flush()

    # Audit log asset deletion
    await audit.log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_id,
        action=AuditAction.ASSET_DELETED,
        actor_id=auth.team_id,
        payload={"fqn": asset.fqn},
    )

    # Invalidate cache
    await asset_cache.delete(str(asset_id))


@router.post(
    "/{asset_id}/restore",
    response_model=Asset,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def restore_asset(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Restore a soft-deleted asset.

    Requires admin scope.
    """
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    if asset.deleted_at is None:
        return asset

    asset.deleted_at = None
    await session.flush()
    await session.refresh(asset)

    # Audit log asset restoration
    await audit.log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_id,
        action=AuditAction.ASSET_RESTORED,
        actor_id=auth.team_id,
        payload={"fqn": asset.fqn},
    )

    # Invalidate cache
    await asset_cache.delete(str(asset_id))

    return asset
