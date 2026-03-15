"""Asset listing, search, and bulk operations."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from tessera.api.auth import Auth, RequireAdmin, RequireRead
from tessera.api.errors import ErrorCode, NotFoundError
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import (
    AssetSearchResult,
    AssetWithOwnerInfo,
    BulkAssignResponse,
    PaginatedResponse,
)
from tessera.config import settings
from tessera.db import AssetDB, ContractDB, TeamDB, UserDB, get_session
from tessera.models import Asset, BulkAssignRequest
from tessera.models.enums import ContractStatus, ResourceType
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.cache import (
    cache_asset_search,
    get_cached_asset_search,
    invalidate_asset,
)

from .helpers import _E, _apply_asset_search_filters

router = APIRouter()


@router.get("", responses={k: _E[k] for k in (401, 403)})
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


@router.get("/search", responses={k: _E[k] for k in (401, 403)})
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
    search_results: list[AssetSearchResult] = [
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
        "results": search_results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

    # Cache result if default pagination
    if limit == settings.pagination_limit_default and offset == 0:
        await cache_asset_search(q, filters, response)  # type: ignore[arg-type]

    return response


@router.post("/bulk-assign", responses={k: _E[k] for k in (401, 403, 404)})
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

    # Audit log bulk owner assignment
    if assets:
        await audit.log_event(
            session=session,
            entity_type="asset",
            entity_id=assets[0].id,
            action=AuditAction.BULK_OWNER_ASSIGNED,
            actor_id=auth.team_id,
            payload={
                "new_owner_user_id": str(bulk_request.owner_user_id)
                if bulk_request.owner_user_id
                else None,
                "asset_count": updated,
                "asset_ids": [str(a.id) for a in assets],
            },
        )

    # Invalidate caches for all updated assets
    for asset in assets:
        await invalidate_asset(str(asset.id))

    return BulkAssignResponse(
        updated=updated,
        not_found=not_found,
        owner_user_id=str(bulk_request.owner_user_id) if bulk_request.owner_user_id else None,
    )
