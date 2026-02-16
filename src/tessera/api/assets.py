"""Assets API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from tessera.api.auth import Auth, RequireAdmin, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_expensive, limit_read, limit_write
from tessera.api.types import (
    AssetSearchResult,
    AssetWithOwnerInfo,
    BulkAssignResponse,
    ContractHistoryEntry,
    ContractHistoryResponse,
    ContractPublishResponse,
    ContractWithPublisherInfo,
    PaginatedResponse,
    SchemaDiffResponse,
)
from tessera.config import settings
from tessera.db import (
    AssetDB,
    AuditRunDB,
    ContractDB,
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
    VersionSuggestion,
    VersionSuggestionRequest,
)
from tessera.models.enums import (
    APIKeyScope,
    AuditRunStatus,
    ChangeType,
    ContractStatus,
    ResourceType,
    SchemaFormat,
    SemverMode,
)
from tessera.services import (
    audit,
    check_compatibility,
    diff_schemas,
    validate_json_schema,
)
from tessera.services.audit import AuditAction
from tessera.services.avro import (
    AvroConversionError,
    avro_to_json_schema,
    validate_avro_schema,
)
from tessera.services.cache import (
    asset_cache,
    cache_asset,
    cache_asset_contracts_list,
    cache_asset_search,
    cache_schema_diff,
    get_cached_asset,
    get_cached_asset_contracts_list,
    get_cached_asset_search,
    get_cached_schema_diff,
    invalidate_asset,
)
from tessera.services.contract_publisher import (
    ContractPublishingWorkflow,
    PublishAction,
    SinglePublishResult,
)
from tessera.services.versioning import (
    compute_version_suggestion,
    parse_semver,
)

router = APIRouter()


def _apply_asset_search_filters(
    query: Select[Any],
    q: str,
    owner: UUID | None,
    environment: str | None,
) -> Select[Any]:
    """Apply common asset search filters to a query."""
    filtered = query.where(AssetDB.fqn.ilike(f"%{q}%")).where(AssetDB.deleted_at.is_(None))
    if owner:
        filtered = filtered.where(AssetDB.owner_team_id == owner)
    if environment:
        filtered = filtered.where(AssetDB.environment == environment)
    return filtered


def validate_version_for_change_type(
    user_version: str,
    current_version: str,
    suggested_change_type: ChangeType,
) -> tuple[bool, str | None]:
    """Validate that user-provided version matches the detected change type.

    Args:
        user_version: The version provided by the user
        current_version: The current contract version
        suggested_change_type: The change type detected from schema diff

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        user_major, user_minor, user_patch = parse_semver(user_version)
        curr_major, curr_minor, curr_patch = parse_semver(current_version)
    except ValueError as e:
        return False, str(e)

    # Version must be greater than current
    user_tuple = (user_major, user_minor, user_patch)
    curr_tuple = (curr_major, curr_minor, curr_patch)
    if user_tuple <= curr_tuple:
        return (
            False,
            f"Version {user_version} must be greater than current version {current_version}",
        )

    # For major changes, major version must increase
    if suggested_change_type == ChangeType.MAJOR:
        if user_major <= curr_major:
            return False, (
                f"Breaking change requires major version bump. "
                f"Expected {curr_major + 1}.0.0 or higher, got {user_version}"
            )

    # For minor changes, version must increase appropriately
    # (major bump is also acceptable for minor changes)
    if suggested_change_type == ChangeType.MINOR:
        if user_major == curr_major and user_minor <= curr_minor:
            return False, (
                f"Backward-compatible additions require at least a minor version bump. "
                f"Expected {curr_major}.{curr_minor + 1}.0 or higher, got {user_version}"
            )

    return True, None


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
) -> PaginatedResponse[AssetWithOwnerInfo]:
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
    sort_column: InstrumentedAttribute[object] = AssetDB.fqn  # default
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

    results: list[AssetWithOwnerInfo] = []
    for asset_db, team_name, user_name, user_email in rows:
        asset_dict: AssetWithOwnerInfo = Asset.model_validate(asset_db).model_dump()  # type: ignore[assignment]
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
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
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
) -> PaginatedResponse[AssetSearchResult]:
    """Search assets by FQN pattern.

    Searches for assets whose FQN contains the search query (case-insensitive).
    Requires read scope.
    """
    # Build filters dict for cache key
    filters: dict[str, str] = {}
    if owner:
        filters["owner"] = str(owner)
    if environment:
        filters["environment"] = environment

    # Try cache first (only for default pagination to keep cache simple)
    if limit == settings.pagination_limit_default and offset == 0:
        cached = await get_cached_asset_search(q, filters)
        if cached:
            return cached  # type: ignore[return-value]

    base_query = _apply_asset_search_filters(select(AssetDB), q, owner, environment)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # JOIN with teams to get names in a single query (fixes N+1)
    query = _apply_asset_search_filters(
        select(AssetDB, TeamDB).join(TeamDB, AssetDB.owner_team_id == TeamDB.id),
        q,
        owner,
        environment,
    )
    query = query.order_by(AssetDB.fqn).limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    # Build response with owner team names from join
    results: list[AssetSearchResult] = [
        AssetSearchResult(
            id=str(asset.id),
            fqn=asset.fqn,
            owner_team_id=str(asset.owner_team_id),
            owner_team_name=team.name,
            environment=asset.environment,
        )
        for asset, team in rows
    ]

    response: PaginatedResponse[AssetSearchResult] = {
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

    # Cache result if default pagination
    if limit == settings.pagination_limit_default and offset == 0:
        await cache_asset_search(q, filters, response)  # type: ignore[arg-type]

    return response


@router.get("/{asset_id}")
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
    if update.guarantee_mode is not None:
        asset.guarantee_mode = update.guarantee_mode
    if update.semver_mode is not None:
        asset.semver_mode = update.semver_mode
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


def _build_publish_response(
    result: SinglePublishResult,
    original_format: SchemaFormat,
) -> ContractPublishResponse:
    """Convert a SinglePublishResult from the workflow into the API response format.

    Translates the workflow's dataclass result into the ContractPublishResponse
    TypedDict that the API endpoint returns. Only includes fields that have
    meaningful values to keep the response clean.
    """
    response: ContractPublishResponse = {"action": str(result.action)}

    if result.contract:
        response["contract"] = Contract.model_validate(result.contract).model_dump()

    if result.proposal:
        response["proposal"] = Proposal.model_validate(result.proposal).model_dump()

    if result.change_type is not None:
        response["change_type"] = str(result.change_type)

    if result.breaking_changes:
        response["breaking_changes"] = result.breaking_changes

    if result.message:
        response["message"] = result.message

    if result.warning:
        response["warning"] = result.warning

    if result.version_auto_generated:
        response["version_auto_generated"] = True

    if result.schema_converted_from:
        response["schema_converted_from"] = result.schema_converted_from
    elif original_format == SchemaFormat.AVRO:
        response["schema_converted_from"] = "avro"

    if result.audit_warning:
        response["audit_warning"] = result.audit_warning

    return response


@router.post("/{asset_id}/contracts", status_code=201, response_model=None)
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
) -> ContractPublishResponse | JSONResponse:
    """Publish a new contract for an asset.

    Requires write scope. Delegates to ContractPublishingWorkflow for the actual
    publishing logic, which uses FOR UPDATE locking to prevent concurrent publish
    races.

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
    # Verify asset exists and is not soft-deleted
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Check audit status for WAP enforcement
    audit_status, audit_failed, audit_run_at = await _get_last_audit_status(session, asset_id)
    audit_warning: str | None = None

    if require_audit_pass:
        if audit_status is None:
            raise PreconditionFailedError(
                ErrorCode.AUDIT_REQUIRED,
                "No audit runs found. Run audits before publishing with require_audit_pass=True.",
            )
        if audit_status != AuditRunStatus.PASSED:
            raise PreconditionFailedError(
                ErrorCode.AUDIT_FAILED,
                f"Most recent audit {audit_status.value}. "
                "Cannot publish with require_audit_pass=True.",
                details={
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

    # Validate and normalize schema based on format
    schema_to_store = contract.schema_def
    original_format = contract.schema_format

    if contract.schema_format == SchemaFormat.AVRO:
        is_valid, avro_errors = validate_avro_schema(contract.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid Avro schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": avro_errors, "schema_format": "avro"},
            )
        try:
            schema_to_store = avro_to_json_schema(contract.schema_def)
        except AvroConversionError as e:
            raise BadRequestError(
                f"Failed to convert Avro schema: {e.message}",
                code=ErrorCode.INVALID_SCHEMA,
                details={"path": e.path, "schema_format": "avro"},
            )
    else:
        is_valid, errors = validate_json_schema(contract.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid JSON Schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": errors},
            )

    # --- Pre-workflow validation (without FOR UPDATE lock) ---
    # Compute version suggestion for SUGGEST/ENFORCE mode validation.
    # The workflow will re-compute under lock for the actual publish decision.
    pre_contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    pre_current_contract = pre_contract_result.scalar_one_or_none()

    if pre_current_contract:
        pre_diff = diff_schemas(pre_current_contract.schema_def, schema_to_store)
        pre_is_compatible, pre_breaks = check_compatibility(
            pre_current_contract.schema_def,
            schema_to_store,
            pre_current_contract.compatibility_mode,
        )
        version_suggestion = compute_version_suggestion(
            pre_current_contract.version,
            pre_diff.change_type,
            pre_is_compatible,
            breaking_changes=[bc.to_dict() for bc in pre_breaks],
        )
    else:
        version_suggestion = compute_version_suggestion(None, ChangeType.PATCH, True)

    # Handle version based on semver_mode
    semver_mode = asset.semver_mode
    version_for_workflow: str | None = None

    if contract.version is None:
        # No version provided by user
        if semver_mode == SemverMode.SUGGEST:
            # Return suggestion without publishing (200 since nothing created).
            # This is handled before the workflow to avoid acquiring a FOR UPDATE
            # lock for a read-only operation.
            msg = (
                "Version not provided. Please review the suggested version "
                "and re-submit with an explicit version."
            )
            return JSONResponse(
                status_code=200,
                content={
                    "action": "version_required",
                    "message": msg,
                    "version_suggestion": version_suggestion.model_dump(),
                },
            )
        # AUTO mode: pass None to workflow, which will auto-generate under lock
        version_for_workflow = None
    else:
        # User provided a version
        version_for_workflow = contract.version

        # In ENFORCE mode, validate the user's version matches the change type
        if semver_mode == SemverMode.ENFORCE and pre_current_contract:
            is_valid_version, error_msg = validate_version_for_change_type(
                version_for_workflow,
                pre_current_contract.version,
                version_suggestion.change_type,
            )
            if not is_valid_version:
                raise BadRequestError(
                    error_msg or "Invalid version for change type",
                    code=ErrorCode.INVALID_VERSION,
                    details={
                        "provided_version": version_for_workflow,
                        "version_suggestion": version_suggestion.model_dump(),
                    },
                )

        # Check if version already exists (fast failure before acquiring lock)
        existing_version_result = await session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == asset_id)
            .where(ContractDB.version == version_for_workflow)
        )
        existing_version = existing_version_result.scalar_one_or_none()
        if existing_version:
            raise DuplicateError(
                ErrorCode.VERSION_EXISTS,
                f"Contract version {version_for_workflow} already exists for this asset",
                details={"existing_contract_id": str(existing_version.id)},
            )

    # --- Delegate to ContractPublishingWorkflow ---
    # The workflow handles: FOR UPDATE locking, version computation (for AUTO mode),
    # schema diffing, compatibility checking, contract creation, deprecation of old
    # contracts, guarantee change logging, proposal creation, and notifications.
    workflow = ContractPublishingWorkflow(
        session=session,
        asset=asset,
        publisher_team=publisher_team,
        schema_def=schema_to_store,
        schema_format=original_format,
        compatibility_mode=contract.compatibility_mode,
        version=version_for_workflow,
        published_by=published_by,
        published_by_user_id=published_by_user_id,
        guarantees=contract.guarantees.model_dump() if contract.guarantees else None,
        force=force,
        audit_warning=audit_warning,
    )
    result = await workflow.execute()

    # Handle duplicate proposal: the workflow returns PROPOSAL_CREATED with the
    # existing proposal when one already exists. Convert to the expected HTTP error.
    if (
        result.action == PublishAction.PROPOSAL_CREATED
        and result.proposal is not None
        and result.message
        and "already has pending proposal" in result.message
    ):
        raise DuplicateError(
            ErrorCode.DUPLICATE_PROPOSAL,
            f"Asset already has a pending proposal (ID: {result.proposal.id}). "
            "Resolve the existing proposal before creating a new one.",
        )

    return _build_publish_response(result, original_format)


@router.get("/{asset_id}/contracts")
@limit_read
async def list_asset_contracts(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[ContractWithPublisherInfo]:
    """List all contracts for an asset.

    Requires read scope. Returns contracts with publisher team and user names.
    """
    # Try cache first (only for default pagination to keep cache simple)
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        cached = await get_cached_asset_contracts_list(str(asset_id))
        if cached:
            return cached  # type: ignore[return-value]

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

    results: list[ContractWithPublisherInfo] = []
    for contract_db, publisher_team_name, publisher_user_name in rows:
        contract_dict: ContractWithPublisherInfo = Contract.model_validate(contract_db).model_dump()  # type: ignore[assignment]
        contract_dict["published_by_team_name"] = publisher_team_name
        contract_dict["published_by_user_name"] = publisher_user_name
        results.append(contract_dict)

    response: PaginatedResponse[ContractWithPublisherInfo] = {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }

    # Cache result if default pagination
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        await cache_asset_contracts_list(str(asset_id), response)  # type: ignore[arg-type]

    return response


@router.get("/{asset_id}/contracts/history")
@limit_read
async def get_contract_history(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ContractHistoryResponse:
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
    history: list[ContractHistoryEntry] = []
    for i, contract_item in enumerate(contracts):
        entry: ContractHistoryEntry = {
            "id": str(contract_item.id),
            "version": contract_item.version,
            "status": str(contract_item.status.value),
            "published_at": contract_item.published_at.isoformat(),
            "published_by": str(contract_item.published_by),
            "compatibility_mode": str(contract_item.compatibility_mode.value),
        }

        # Compare with next (older) contract if exists
        if i < len(contracts) - 1:
            older_contract = contracts[i + 1]
            diff_result = diff_schemas(older_contract.schema_def, contract_item.schema_def)
            breaking = diff_result.breaking_for_mode(older_contract.compatibility_mode)
            entry["change_type"] = str(diff_result.change_type.value)
            entry["breaking_changes_count"] = len(breaking)
        else:
            # First contract
            entry["change_type"] = "initial"
            entry["breaking_changes_count"] = 0

        history.append(entry)

    return ContractHistoryResponse(
        asset_id=str(asset_id),
        asset_fqn=asset.fqn,
        contracts=history,
    )


@router.get("/{asset_id}/contracts/diff")
@limit_read
@limit_expensive  # Per-team rate limit for expensive schema diff operation
async def diff_contract_versions(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    from_version: str = Query(..., description="Source version to compare from"),
    to_version: str = Query(..., description="Target version to compare to"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> SchemaDiffResponse:
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

    # Re-calculate breaking based on compatibility mode of from_contract
    # We need to re-check compatibility because it depends on the mode
    # re-diff for breaking (fast)
    diff_obj = diff_schemas(from_contract.schema_def, to_contract.schema_def)
    breaking = diff_obj.breaking_for_mode(from_contract.compatibility_mode)

    return SchemaDiffResponse(
        asset_id=str(asset_id),
        asset_fqn=asset.fqn,
        from_version=from_version,
        to_version=to_version,
        change_type=diff_result_data["change_type"],
        is_compatible=len(breaking) == 0,
        breaking_changes=[bc.to_dict() for bc in breaking],
        all_changes=diff_result_data["all_changes"],
        compatibility_mode=str(from_contract.compatibility_mode.value),
    )


@router.post("/{asset_id}/version-suggestion", response_model=VersionSuggestion)
@limit_read
async def preview_version_suggestion(
    request: Request,
    asset_id: UUID,
    body: VersionSuggestionRequest,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> VersionSuggestion:
    """Preview version suggestion for a schema change without publishing.

    This endpoint analyzes a proposed schema against the current active contract
    and returns what version would be suggested, along with any breaking changes.
    No side effects - no contracts or proposals are created.

    Useful for:
    - CI/CD pipelines that want to show impact before PR merge
    - UIs that want to preview "this will be version 2.0.0" before confirmation

    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Validate and normalize schema based on format
    schema_to_check = body.schema_def

    if body.schema_format == SchemaFormat.AVRO:
        from tessera.services.avro import (
            AvroConversionError,
            avro_to_json_schema,
            validate_avro_schema,
        )

        is_valid, avro_errors = validate_avro_schema(body.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid Avro schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": avro_errors, "schema_format": "avro"},
            )
        try:
            schema_to_check = avro_to_json_schema(body.schema_def)
        except AvroConversionError as e:
            raise BadRequestError(
                f"Failed to convert Avro schema: {e.message}",
                code=ErrorCode.INVALID_SCHEMA,
                details={"path": e.path, "schema_format": "avro"},
            )
    else:
        is_valid, errors = validate_json_schema(body.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid JSON Schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": errors},
            )

    # Get current active contract
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # Compute version suggestion
    if current_contract:
        diff_result = diff_schemas(current_contract.schema_def, schema_to_check)
        is_compatible, breaking_changes = check_compatibility(
            current_contract.schema_def,
            schema_to_check,
            current_contract.compatibility_mode,
        )
        return compute_version_suggestion(
            current_contract.version,
            diff_result.change_type,
            is_compatible,
            breaking_changes=[bc.to_dict() for bc in breaking_changes],
        )
    else:
        # First contract for this asset
        return compute_version_suggestion(None, ChangeType.PATCH, True)


@router.post("/bulk-assign")
@limit_write
async def bulk_assign_owner(
    request: Request,
    bulk_request: BulkAssignRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> BulkAssignResponse:
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
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "Owner user not found")

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

    return BulkAssignResponse(
        updated=updated,
        not_found=not_found,
        owner_user_id=str(bulk_request.owner_user_id) if bulk_request.owner_user_id else None,
    )
