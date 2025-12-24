"""Assets API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
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
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.config import settings
from tessera.db import (
    AssetDB,
    AuditRunDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
    UserDB,
    get_session,
)
from tessera.models import (
    Asset,
    AssetCreate,
    AssetUpdate,
    BulkAssignRequest,
    Contract,
    ContractCreate,
    Proposal,
)
from tessera.models.enums import (
    APIKeyScope,
    AuditRunStatus,
    ContractStatus,
    RegistrationStatus,
    ResourceType,
)
from tessera.services import (
    check_compatibility,
    diff_schemas,
    log_contract_published,
    log_proposal_created,
    validate_json_schema,
)
from tessera.services.cache import (
    asset_cache,
    cache_asset,
    cache_asset_contracts_list,
    cache_asset_search,
    cache_contract,
    cache_schema_diff,
    get_cached_asset,
    get_cached_asset_contracts_list,
    get_cached_asset_search,
    get_cached_schema_diff,
    invalidate_asset,
)
from tessera.services.slack import notify_proposal_created
from tessera.services.webhooks import send_proposal_created

router = APIRouter()


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string into (major, minor, patch)."""
    # Strip any prerelease/build metadata
    base = version.split("-")[0].split("+")[0]
    parts = base.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def bump_version(current: str, bump_type: str) -> str:
    """Bump a semantic version based on change type.

    bump_type: 'major' or 'minor'
    """
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"{major + 1}.0.0"
    else:  # minor
        return f"{major}.{minor + 1}.0"


async def _get_team_name(session: AsyncSession, team_id: UUID) -> str:
    """Get team name by ID, returns 'unknown' if not found."""
    result = await session.execute(select(TeamDB.name).where(TeamDB.id == team_id))
    name = result.scalar_one_or_none()
    return name if name else "unknown"


@router.post("", response_model=Asset, status_code=201)
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
            raise HTTPException(status_code=404, detail="Owner user not found")
        if user.team_id != asset.owner_team_id:
            raise HTTPException(
                status_code=400,
                detail="Owner user must belong to the owner team",
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
        metadata_=asset.metadata,
    )
    session.add(db_asset)
    try:
        await session.flush()
    except IntegrityError:
        raise DuplicateError(
            ErrorCode.DUPLICATE_ASSET, f"Asset with FQN '{asset.fqn}' already exists"
        )
    await session.refresh(db_asset)
    return db_asset


@router.get("")
@limit_read
async def list_assets(
    request: Request,
    auth: Auth,
    owner: UUID | None = Query(None, description="Filter by owner team ID"),
    owner_user: UUID | None = Query(None, description="Filter by owner user ID"),
    unowned: bool = Query(False, description="Filter to assets without a user owner"),
    fqn: str | None = Query(None, description="Filter by FQN pattern (case-insensitive)"),
    environment: str | None = Query(None, description="Filter by environment"),
    resource_type: ResourceType | None = Query(None, description="Filter by resource type"),
    sort_by: str | None = Query(None, description="Sort by field (fqn, owner, created_at)"),
    sort_order: str = Query("asc", description="Sort order (asc, desc)"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all assets with filtering, sorting, and pagination.

    Requires read scope. Returns assets with owner team/user names and active contract version.

    Filters:
    - owner: Filter by owner team ID
    - owner_user: Filter by owner user ID
    - unowned: If true, only return assets without a user owner
    """
    # Query with joins to get team and user names
    query = (
        select(
            AssetDB,
            TeamDB.name.label("team_name"),
            UserDB.name.label("user_name"),
            UserDB.email.label("user_email"),
        )
        .outerjoin(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .outerjoin(UserDB, AssetDB.owner_user_id == UserDB.id)
        .where(AssetDB.deleted_at.is_(None))
    )

    # Build count query base
    count_base = select(AssetDB).where(AssetDB.deleted_at.is_(None))

    if owner:
        query = query.where(AssetDB.owner_team_id == owner)
        count_base = count_base.where(AssetDB.owner_team_id == owner)
    if owner_user:
        query = query.where(AssetDB.owner_user_id == owner_user)
        count_base = count_base.where(AssetDB.owner_user_id == owner_user)
    if unowned:
        query = query.where(AssetDB.owner_user_id.is_(None))
        count_base = count_base.where(AssetDB.owner_user_id.is_(None))
    if fqn:
        query = query.where(AssetDB.fqn.ilike(f"%{fqn}%"))
        count_base = count_base.where(AssetDB.fqn.ilike(f"%{fqn}%"))
    if environment:
        query = query.where(AssetDB.environment == environment)
        count_base = count_base.where(AssetDB.environment == environment)
    if resource_type:
        query = query.where(AssetDB.resource_type == resource_type)
        count_base = count_base.where(AssetDB.resource_type == resource_type)

    # Apply sorting
    sort_column: Any = AssetDB.fqn  # default
    if sort_by == "owner":
        sort_column = TeamDB.name
    elif sort_by == "owner_user":
        sort_column = UserDB.name
    elif sort_by == "created_at":
        sort_column = AssetDB.created_at
    elif sort_by == "fqn":
        sort_column = AssetDB.fqn

    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # Get total count
    count_query = select(func.count()).select_from(count_base.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    rows = result.all()

    # Collect asset IDs to batch fetch active contracts
    asset_ids = [asset_db.id for asset_db, _, _, _ in rows]

    # Batch fetch active contracts for all assets (fixes N+1)
    active_contracts_map: dict[UUID, str] = {}
    if asset_ids:
        # Get all active contracts for these assets, ordered by published_at desc
        contracts_result = await session.execute(
            select(ContractDB.asset_id, ContractDB.version, ContractDB.published_at)
            .where(ContractDB.asset_id.in_(asset_ids))
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .order_by(ContractDB.published_at.desc())
        )
        # Keep only the most recent active contract per asset
        for asset_id, version, _ in contracts_result.all():
            if asset_id not in active_contracts_map:
                active_contracts_map[asset_id] = version

    results = []
    for asset_db, team_name, user_name, user_email in rows:
        asset_dict = Asset.model_validate(asset_db).model_dump()
        asset_dict["owner_team_name"] = team_name
        asset_dict["owner_user_name"] = user_name
        asset_dict["owner_user_email"] = user_email
        asset_dict["active_contract_version"] = active_contracts_map.get(asset_db.id)
        results.append(asset_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get("/search")
@limit_read
async def search_assets(
    request: Request,
    auth: Auth,
    q: str = Query(..., min_length=1, description="Search query"),
    owner: UUID | None = Query(None, description="Filter by owner team ID"),
    environment: str | None = Query(None, description="Filter by environment"),
    limit: int = Query(
        settings.pagination_limit_default,
        ge=1,
        le=settings.pagination_limit_max,
        description="Results per page",
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search assets by FQN pattern.

    Searches for assets whose FQN contains the search query (case-insensitive).
    Requires read scope.
    """
    # Build filters dict for cache key
    filters = {}
    if owner:
        filters["owner"] = str(owner)
    if environment:
        filters["environment"] = environment

    # Try cache first (only for default pagination to keep cache simple)
    if limit == settings.pagination_limit_default and offset == 0:
        cached = await get_cached_asset_search(q, filters)
        if cached:
            return cached

    base_query = (
        select(AssetDB).where(AssetDB.fqn.ilike(f"%{q}%")).where(AssetDB.deleted_at.is_(None))
    )
    if owner:
        base_query = base_query.where(AssetDB.owner_team_id == owner)
    if environment:
        base_query = base_query.where(AssetDB.environment == environment)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # JOIN with teams to get names in a single query (fixes N+1)
    query = (
        select(AssetDB, TeamDB)
        .join(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .where(AssetDB.fqn.ilike(f"%{q}%"))
        .where(AssetDB.deleted_at.is_(None))
    )
    if owner:
        query = query.where(AssetDB.owner_team_id == owner)
    if environment:
        query = query.where(AssetDB.environment == environment)
    query = query.order_by(AssetDB.fqn).limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    # Build response with owner team names from join
    results = [
        {
            "id": str(asset.id),
            "fqn": asset.fqn,
            "owner_team_id": str(asset.owner_team_id),
            "owner_team_name": team.name,
            "environment": asset.environment,
        }
        for asset, team in rows
    ]

    response = {
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

    # Cache result if default pagination
    if limit == settings.pagination_limit_default and offset == 0:
        await cache_asset_search(q, filters, response)

    return response


@router.get("/{asset_id}")
@limit_read
async def get_asset(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get an asset by ID.

    Requires read scope. Returns asset with owner team and user names.
    """
    # Try cache first
    cached = await get_cached_asset(str(asset_id))
    if cached:
        return cached

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
    asset_dict = Asset.model_validate(asset).model_dump()
    asset_dict["owner_team_name"] = team_name
    asset_dict["owner_user_name"] = user_name
    asset_dict["owner_user_email"] = user_email

    # Cache result
    await cache_asset(str(asset_id), asset_dict)

    return asset_dict


@router.patch("/{asset_id}", response_model=Asset)
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
    if update.metadata is not None:
        asset.metadata_ = update.metadata

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
            raise HTTPException(status_code=404, detail="Owner user not found")
        if user.team_id != new_team_id:
            raise HTTPException(
                status_code=400,
                detail="Owner user must belong to the owner team",
            )

    if update.owner_team_id is not None:
        asset.owner_team_id = update.owner_team_id
    if update.owner_user_id is not None:
        asset.owner_user_id = update.owner_user_id

    await session.flush()
    await session.refresh(asset)

    # Invalidate asset and contract caches
    await invalidate_asset(str(asset_id))

    return asset


@router.delete("/{asset_id}", status_code=204)
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

    # Invalidate cache
    await asset_cache.delete(str(asset_id))


@router.post("/{asset_id}/restore", response_model=Asset)
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

    # Invalidate cache
    await asset_cache.delete(str(asset_id))

    return asset


async def _get_last_audit_status(
    session: AsyncSession, asset_id: UUID
) -> tuple[AuditRunStatus | None, int, datetime | None]:
    """Get the most recent audit run status for an asset.

    Returns (status, failed_count, run_at) or (None, 0, None) if no audits exist.
    """
    from sqlalchemy import desc

    result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .order_by(desc(AuditRunDB.run_at))
        .limit(1)
    )
    audit_run = result.scalar_one_or_none()
    if not audit_run:
        return None, 0, None
    return audit_run.status, audit_run.guarantees_failed, audit_run.run_at


@router.post("/{asset_id}/contracts", status_code=201)
@limit_write
async def create_contract(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    contract: ContractCreate,
    published_by: UUID = Query(..., description="Team ID of the publisher"),
    published_by_user_id: UUID | None = Query(None, description="User ID who published"),
    force: bool = Query(False, description="Force publish even if breaking (creates audit trail)"),
    require_audit_pass: bool = Query(
        False, description="Require most recent audit to pass before publishing"
    ),
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Publish a new contract for an asset.

    Requires write scope.

    Behavior:
    - If no active contract exists: auto-publish (first contract)
    - If change is compatible: auto-publish, deprecate old contract
    - If change is breaking: create a Proposal for consumer acknowledgment
    - If force=True: publish anyway but log the override
    - If require_audit_pass=True: reject if most recent audit failed

    WAP (Write-Audit-Publish) enforcement:
    - Set require_audit_pass=True to gate publishing on passing audits
    - Returns 412 Precondition Failed if no audits exist or last audit failed
    - Without this flag, audit failures add a warning to the response

    Returns either a Contract (if published) or a Proposal (if breaking).
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Check audit status for WAP enforcement
    audit_status, audit_failed, audit_run_at = await _get_last_audit_status(session, asset_id)
    audit_warning: str | None = None

    if require_audit_pass:
        if audit_status is None:
            raise HTTPException(
                status_code=412,
                detail={
                    "code": "AUDIT_REQUIRED",
                    "message": (
                        "No audit runs found. Run audits before publishing "
                        "with require_audit_pass=True."
                    ),
                },
            )
        if audit_status != AuditRunStatus.PASSED:
            raise HTTPException(
                status_code=412,
                detail={
                    "code": "AUDIT_FAILED",
                    "message": (
                        f"Most recent audit {audit_status.value}. "
                        "Cannot publish with require_audit_pass=True."
                    ),
                    "audit_status": audit_status.value,
                    "guarantees_failed": audit_failed,
                    "audit_run_at": audit_run_at.isoformat() if audit_run_at else None,
                },
            )
    elif audit_status and audit_status != AuditRunStatus.PASSED:
        # Not enforcing, but add a warning to the response
        audit_warning = (
            f"Warning: Most recent audit {audit_status.value} "
            f"with {audit_failed} guarantee(s) failing"
        )

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        asset_team_name = await _get_team_name(session, asset.owner_team_id)
        raise ForbiddenError(
            f"Cannot publish contract for asset '{asset.fqn}' owned by '{asset_team_name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to publish contracts for other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Verify publisher team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == published_by))
    publisher_team = team_result.scalar_one_or_none()
    if not publisher_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Publisher team not found")

    # Resource-level auth: published_by must match auth.team_id or be admin
    if published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        raise ForbiddenError(
            f"Cannot publish contract on behalf of team '{publisher_team.name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to publish on behalf of other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Validate schema is valid JSON Schema
    is_valid, errors = validate_json_schema(contract.schema_def)
    if not is_valid:
        raise BadRequestError(
            "Invalid JSON Schema",
            code=ErrorCode.INVALID_SCHEMA,
            details={"errors": errors},
        )

    # Get current active contract first (needed for version auto-generation)
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # Auto-generate version if not provided
    version_auto_generated = False
    if contract.version is None:
        version_auto_generated = True
        if not current_contract:
            # First contract for this asset
            version = "1.0.0"
        else:
            # Determine bump type based on compatibility
            is_compatible, _unused = check_compatibility(
                current_contract.schema_def,
                contract.schema_def,
                current_contract.compatibility_mode,
            )
            bump_type = "minor" if is_compatible else "major"
            version = bump_version(current_contract.version, bump_type)
    else:
        version = contract.version

    # Check if version already exists for this asset
    existing_version_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == version)
    )
    existing_version = existing_version_result.scalar_one_or_none()
    if existing_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_EXISTS",
                "message": f"Contract version {version} already exists for this asset",
                "existing_contract_id": str(existing_version.id),
            },
        )

    # Helper to create and return the new contract
    # Uses nested transaction (savepoint) to ensure atomicity of multi-step publish
    async def publish_contract() -> ContractDB:
        async with session.begin_nested():
            db_contract = ContractDB(
                asset_id=asset_id,
                version=version,
                schema_def=contract.schema_def,
                compatibility_mode=contract.compatibility_mode,
                guarantees=contract.guarantees.model_dump() if contract.guarantees else None,
                published_by=published_by,
                published_by_user_id=published_by_user_id,
            )
            session.add(db_contract)

            # Deprecate old contract if exists
            if current_contract:
                current_contract.status = ContractStatus.DEPRECATED

            await session.flush()
            await session.refresh(db_contract)
        return db_contract

    # No existing contract = first publish, auto-approve
    if not current_contract:
        new_contract = await publish_contract()
        await log_contract_published(
            session=session,
            contract_id=new_contract.id,
            publisher_id=published_by,
            version=new_contract.version,
        )
        # Invalidate asset and contract caches, cache new contract
        await invalidate_asset(str(asset_id))
        contract_data = Contract.model_validate(new_contract).model_dump()
        await cache_contract(str(new_contract.id), contract_data)
        response: dict[str, Any] = {
            "action": "published",
            "contract": contract_data,
        }
        if version_auto_generated:
            response["version_auto_generated"] = True
        if audit_warning:
            response["audit_warning"] = audit_warning
        return response

    # Diff schemas and check compatibility
    is_compatible, breaking_changes = check_compatibility(
        current_contract.schema_def,
        contract.schema_def,
        current_contract.compatibility_mode,
    )
    diff_result = diff_schemas(current_contract.schema_def, contract.schema_def)

    # Compatible change = auto-publish
    if is_compatible:
        new_contract = await publish_contract()
        await log_contract_published(
            session=session,
            contract_id=new_contract.id,
            publisher_id=published_by,
            version=new_contract.version,
            change_type=str(diff_result.change_type),
        )
        # Invalidate asset and contract caches, cache new contract
        await invalidate_asset(str(asset_id))
        contract_data = Contract.model_validate(new_contract).model_dump()
        await cache_contract(str(new_contract.id), contract_data)
        response = {
            "action": "published",
            "change_type": str(diff_result.change_type),
            "contract": contract_data,
        }
        if version_auto_generated:
            response["version_auto_generated"] = True
        if audit_warning:
            response["audit_warning"] = audit_warning
        return response

    # Breaking change with force flag = publish anyway (logged)
    if force:
        new_contract = await publish_contract()
        await log_contract_published(
            session=session,
            contract_id=new_contract.id,
            publisher_id=published_by,
            version=new_contract.version,
            change_type=str(diff_result.change_type),
            force=True,
        )
        # Invalidate asset and contract caches, cache new contract
        await invalidate_asset(str(asset_id))
        contract_data = Contract.model_validate(new_contract).model_dump()
        await cache_contract(str(new_contract.id), contract_data)
        response = {
            "action": "force_published",
            "change_type": str(diff_result.change_type),
            "breaking_changes": [bc.to_dict() for bc in breaking_changes],
            "contract": contract_data,
            "warning": "Breaking change was force-published. Consumers may be affected.",
        }
        if version_auto_generated:
            response["version_auto_generated"] = True
        if audit_warning:
            response["audit_warning"] = audit_warning
        return response

    # Breaking change without force = create proposal
    db_proposal = ProposalDB(
        asset_id=asset_id,
        proposed_schema=contract.schema_def,
        change_type=diff_result.change_type,
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
        proposed_by=published_by,
        proposed_by_user_id=published_by_user_id,
    )
    session.add(db_proposal)
    await session.flush()
    await session.refresh(db_proposal)

    await log_proposal_created(
        session=session,
        proposal_id=db_proposal.id,
        asset_id=asset_id,
        proposer_id=published_by,
        change_type=str(diff_result.change_type),
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
    )

    # Get impacted consumers (active registrations for current contract)
    impacted_consumers: list[dict[str, Any]] = []
    if current_contract:
        reg_result = await session.execute(
            select(RegistrationDB, TeamDB)
            .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
            .where(RegistrationDB.contract_id == current_contract.id)
            .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        )
        for reg, team in reg_result.all():
            impacted_consumers.append(
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "pinned_version": reg.pinned_version,
                }
            )

    # Notify consumers via webhook
    await send_proposal_created(
        proposal_id=db_proposal.id,
        asset_id=asset_id,
        asset_fqn=asset.fqn,
        producer_team_id=publisher_team.id,
        producer_team_name=publisher_team.name,
        proposed_version=version,
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
        impacted_consumers=impacted_consumers,
    )

    # Send Slack notification
    await notify_proposal_created(
        asset_fqn=asset.fqn,
        version=version,
        producer_team=publisher_team.name,
        affected_consumers=[c["team_name"] for c in impacted_consumers],
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
    )

    return {
        "action": "proposal_created",
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking_changes],
        "proposal": Proposal.model_validate(db_proposal).model_dump(),
        "message": "Breaking change detected. Proposal created for consumer acknowledgment.",
    }


@router.get("/{asset_id}/contracts")
@limit_read
async def list_asset_contracts(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all contracts for an asset.

    Requires read scope. Returns contracts with publisher team and user names.
    """
    # Try cache first (only for default pagination to keep cache simple)
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        cached = await get_cached_asset_contracts_list(str(asset_id))
        if cached:
            return cached

    # Query with join to get publisher team and user names
    query = (
        select(
            ContractDB,
            TeamDB.name.label("publisher_team_name"),
            UserDB.name.label("publisher_user_name"),
        )
        .outerjoin(TeamDB, ContractDB.published_by == TeamDB.id)
        .outerjoin(UserDB, ContractDB.published_by_user_id == UserDB.id)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )

    # Get total count
    count_query = select(func.count()).select_from(
        select(ContractDB).where(ContractDB.asset_id == asset_id).subquery()
    )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    rows = result.all()

    results = []
    for contract_db, publisher_team_name, publisher_user_name in rows:
        contract_dict = Contract.model_validate(contract_db).model_dump()
        contract_dict["published_by_team_name"] = publisher_team_name
        contract_dict["published_by_user_name"] = publisher_user_name
        results.append(contract_dict)

    response = {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }

    # Cache result if default pagination
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        await cache_asset_contracts_list(str(asset_id), response)

    return response


@router.get("/{asset_id}/contracts/history")
@limit_read
async def get_contract_history(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the complete contract history for an asset with change summaries.

    Returns all versions ordered by publication date with change type annotations.
    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Get all contracts ordered by published_at
    contracts_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )
    contracts = list(contracts_result.scalars().all())

    # Build history with change analysis
    history: list[dict[str, Any]] = []
    for i, contract in enumerate(contracts):
        entry: dict[str, Any] = {
            "id": str(contract.id),
            "version": contract.version,
            "status": str(contract.status.value),
            "published_at": contract.published_at.isoformat(),
            "published_by": str(contract.published_by),
            "compatibility_mode": str(contract.compatibility_mode.value),
        }

        # Compare with next (older) contract if exists
        if i < len(contracts) - 1:
            older_contract = contracts[i + 1]
            diff_result = diff_schemas(older_contract.schema_def, contract.schema_def)
            breaking = diff_result.breaking_for_mode(older_contract.compatibility_mode)
            entry["change_type"] = str(diff_result.change_type.value)
            entry["breaking_changes_count"] = len(breaking)
        else:
            # First contract
            entry["change_type"] = "initial"
            entry["breaking_changes_count"] = 0

        history.append(entry)

    return {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "contracts": history,
    }


@router.get("/{asset_id}/contracts/diff")
@limit_read
async def diff_contract_versions(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    from_version: str = Query(..., description="Source version to compare from"),
    to_version: str = Query(..., description="Target version to compare to"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compare two contract versions for an asset.

    Returns the diff between from_version and to_version.
    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Get the from_version contract
    from_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == from_version)
    )
    from_contract = from_result.scalar_one_or_none()
    if not from_contract:
        raise NotFoundError(
            ErrorCode.CONTRACT_NOT_FOUND,
            f"Contract version '{from_version}' not found for this asset",
        )

    # Get the to_version contract
    to_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == to_version)
    )
    to_contract = to_result.scalar_one_or_none()
    if not to_contract:
        raise NotFoundError(
            ErrorCode.CONTRACT_NOT_FOUND,
            f"Contract version '{to_version}' not found for this asset",
        )

    # Perform diff
    # Try cache
    cached = await get_cached_schema_diff(from_contract.schema_def, to_contract.schema_def)
    if cached:
        diff_result_data = cached
    else:
        diff_result = diff_schemas(from_contract.schema_def, to_contract.schema_def)
        diff_result_data = {
            "change_type": str(diff_result.change_type.value),
            "all_changes": [c.to_dict() for c in diff_result.changes],
        }
        await cache_schema_diff(from_contract.schema_def, to_contract.schema_def, diff_result_data)

    breaking = []  # Re-calculate breaking based on compatibility mode of from_contract
    # We need to re-check compatibility because it depends on the mode
    # actually we should just cache the whole result including compatibility if possible
    # but the mode can change.
    # Let's just keep it simple for now.

    # re-diff for breaking (fast)
    diff_obj = diff_schemas(from_contract.schema_def, to_contract.schema_def)
    breaking = diff_obj.breaking_for_mode(from_contract.compatibility_mode)

    return {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "from_version": from_version,
        "to_version": to_version,
        "change_type": diff_result_data["change_type"],
        "is_compatible": len(breaking) == 0,
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "all_changes": diff_result_data["all_changes"],
        "compatibility_mode": str(from_contract.compatibility_mode.value),
    }


@router.post("/bulk-assign")
@limit_write
async def bulk_assign_owner(
    request: Request,
    bulk_request: BulkAssignRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Bulk assign or unassign a user owner for multiple assets.

    Requires admin scope.

    Set owner_user_id to null to unassign user ownership from assets.
    """
    # Validate user exists if assigning
    if bulk_request.owner_user_id:
        user_result = await session.execute(
            select(UserDB)
            .where(UserDB.id == bulk_request.owner_user_id)
            .where(UserDB.deactivated_at.is_(None))
        )
        if not user_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Owner user not found")

    # Get all assets
    result = await session.execute(
        select(AssetDB)
        .where(AssetDB.id.in_(bulk_request.asset_ids))
        .where(AssetDB.deleted_at.is_(None))
    )
    assets = list(result.scalars().all())

    # Track which were found and updated
    found_ids = {a.id for a in assets}
    not_found = [str(aid) for aid in bulk_request.asset_ids if aid not in found_ids]

    # Update all found assets
    updated = 0
    for asset in assets:
        asset.owner_user_id = bulk_request.owner_user_id
        updated += 1

    await session.flush()

    # Invalidate caches for all updated assets
    for asset in assets:
        await invalidate_asset(str(asset.id))

    return {
        "updated": updated,
        "not_found": not_found,
        "owner_user_id": str(bulk_request.owner_user_id) if bulk_request.owner_user_id else None,
    }
