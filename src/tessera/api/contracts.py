"""Contracts API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError, NotFoundError
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db import AssetDB, ContractDB, RegistrationDB, TeamDB, get_session
from tessera.models import Contract, Guarantees, Registration
from tessera.models.bulk import (
    BulkContractRequest,
    BulkContractResponse,
    BulkContractResultItem,
)
from tessera.models.enums import APIKeyScope, CompatibilityMode, ContractStatus
from tessera.services import log_guarantees_updated
from tessera.services.cache import (
    cache_contract,
    cache_schema_diff,
    get_cached_contract,
    get_cached_schema_diff,
)
from tessera.services.contract_publisher import (
    ContractToPublish,
)
from tessera.services.contract_publisher import (
    bulk_publish_contracts as bulk_publish_service,
)
from tessera.services.schema_diff import diff_schemas

router = APIRouter()


class ContractCompareRequest(BaseModel):
    """Request body for contract comparison."""

    contract_id_1: UUID
    contract_id_2: UUID
    compatibility_mode: CompatibilityMode | None = None


class ContractCompareResponse(BaseModel):
    """Response for contract comparison."""

    contract_1: dict[str, Any]
    contract_2: dict[str, Any]
    change_type: str
    is_compatible: bool
    breaking_changes: list[dict[str, Any]]
    all_changes: list[dict[str, Any]]
    compatibility_mode: str


class GuaranteesUpdate(BaseModel):
    """Request body for updating contract guarantees."""

    guarantees: Guarantees


@router.get("")
@limit_read
async def list_contracts(
    request: Request,
    auth: Auth,
    asset_id: UUID | None = Query(None, description="Filter by asset ID"),
    status: ContractStatus | None = Query(None, description="Filter by status"),
    version: str | None = Query(None, description="Filter by version pattern"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all contracts with filtering and pagination.

    Requires read scope. Returns contracts with asset FQN and publisher team name.
    """
    from sqlalchemy import func

    # Build shared filters once to keep data/count queries in sync
    filters = []
    if asset_id:
        filters.append(ContractDB.asset_id == asset_id)
    if status:
        filters.append(ContractDB.status == status)
    if version:
        filters.append(ContractDB.version.ilike(f"%{version}%"))

    # Manual pagination to handle join result
    count_query = select(func.count()).select_from(select(ContractDB).where(*filters).subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Query with joins to get asset FQN and publisher team name
    publisher_team = TeamDB.__table__.alias("publisher_team")
    query = (
        select(
            ContractDB,
            AssetDB.fqn.label("asset_fqn"),
            publisher_team.c.name.label("publisher_name"),
        )
        .outerjoin(AssetDB, ContractDB.asset_id == AssetDB.id)
        .outerjoin(publisher_team, ContractDB.published_by == publisher_team.c.id)
        .where(*filters)
        .order_by(ContractDB.published_at.desc())
    )

    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    rows = result.all()

    results = []
    for contract_db, asset_fqn, publisher_name in rows:
        contract_dict = Contract.model_validate(contract_db).model_dump()
        contract_dict["asset_fqn"] = asset_fqn
        contract_dict["publisher_name"] = publisher_name
        results.append(contract_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.post("/compare", response_model=ContractCompareResponse)
@limit_read
async def compare_contracts(
    request: Request,
    compare_req: ContractCompareRequest,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ContractCompareResponse:
    """Compare two contracts and return the differences.

    Requires read scope.
    """
    # Fetch both contracts
    result1 = await session.execute(
        select(ContractDB).where(ContractDB.id == compare_req.contract_id_1)
    )
    contract1 = result1.scalar_one_or_none()
    if not contract1:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{compare_req.contract_id_1}' not found",
            details={"contract_id": str(compare_req.contract_id_1)},
        )

    result2 = await session.execute(
        select(ContractDB).where(ContractDB.id == compare_req.contract_id_2)
    )
    contract2 = result2.scalar_one_or_none()
    if not contract2:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{compare_req.contract_id_2}' not found",
            details={"contract_id": str(compare_req.contract_id_2)},
        )

    # Use specified compatibility mode or default to first contract's mode
    mode = compare_req.compatibility_mode or contract1.compatibility_mode

    # Try cache first for schema diff
    cached_diff = await get_cached_schema_diff(contract1.schema_def, contract2.schema_def)
    if cached_diff:
        # Use cached diff data
        change_type_str = cached_diff.get("change_type", "minor")
        all_changes = cached_diff.get("all_changes", [])
        # Re-diff to get breaking changes (fast, just checks compatibility)
        diff_result = diff_schemas(contract1.schema_def, contract2.schema_def)
        breaking = diff_result.breaking_for_mode(mode)
    else:
        # Perform diff
        diff_result = diff_schemas(contract1.schema_def, contract2.schema_def)
        breaking = diff_result.breaking_for_mode(mode)
        # Cache the diff result
        await cache_schema_diff(
            contract1.schema_def,
            contract2.schema_def,
            {
                "change_type": str(diff_result.change_type.value),
                "all_changes": [c.to_dict() for c in diff_result.changes],
            },
        )
        all_changes = [c.to_dict() for c in diff_result.changes]
        change_type_str = str(diff_result.change_type.value)

    return ContractCompareResponse(
        contract_1={
            "id": str(contract1.id),
            "version": contract1.version,
            "published_at": contract1.published_at.isoformat(),
            "asset_id": str(contract1.asset_id),
        },
        contract_2={
            "id": str(contract2.id),
            "version": contract2.version,
            "published_at": contract2.published_at.isoformat(),
            "asset_id": str(contract2.asset_id),
        },
        change_type=change_type_str,
        is_compatible=len(breaking) == 0,
        breaking_changes=[bc.to_dict() for bc in breaking],
        all_changes=all_changes,
        compatibility_mode=str(mode.value),
    )


@router.get("/{contract_id}")
@limit_read
async def get_contract(
    request: Request,
    contract_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a contract by ID.

    Requires read scope. Returns contract with asset FQN and publisher team name.
    """
    # Try cache first
    cached = await get_cached_contract(str(contract_id))
    if cached:
        return cached

    # Query with joins to get asset FQN and publisher team name
    publisher_team = TeamDB.__table__.alias("publisher_team")
    result = await session.execute(
        select(
            ContractDB,
            AssetDB.fqn.label("asset_fqn"),
            publisher_team.c.name.label("publisher_name"),
        )
        .outerjoin(AssetDB, ContractDB.asset_id == AssetDB.id)
        .outerjoin(publisher_team, ContractDB.published_by == publisher_team.c.id)
        .where(ContractDB.id == contract_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )

    contract_db, asset_fqn, publisher_name = row
    contract_dict = Contract.model_validate(contract_db).model_dump()
    contract_dict["asset_fqn"] = asset_fqn
    contract_dict["publisher_name"] = publisher_name

    # Cache result
    await cache_contract(str(contract_id), contract_dict)

    return contract_dict


@router.patch("/{contract_id}/guarantees", response_model=Contract)
@limit_write
async def update_guarantees(
    request: Request,
    contract_id: UUID,
    update: GuaranteesUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ContractDB:
    """Update guarantees on a contract.

    Requires write scope. Only active contracts can be updated.
    Resource-level auth: must own the asset's team or be admin.
    """
    # Get contract with asset info for authorization
    result = await session.execute(
        select(ContractDB, AssetDB)
        .join(AssetDB, ContractDB.asset_id == AssetDB.id)
        .where(ContractDB.id == contract_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )
    contract: ContractDB
    asset: AssetDB
    contract, asset = row

    # Only allow updates on active contracts
    if contract.status != ContractStatus.ACTIVE:
        raise BadRequestError(
            f"Cannot update guarantees on {contract.status.value} contract. "
            "Only active contracts can be updated."
        )

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only update guarantees for contracts on assets owned by your team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Store old guarantees for audit log
    old_guarantees = contract.guarantees

    # Update guarantees
    contract.guarantees = update.guarantees.model_dump()
    await session.flush()
    await session.refresh(contract)

    # Log the update
    await log_guarantees_updated(
        session=session,
        contract_id=contract_id,
        actor_id=auth.team_id,
        old_guarantees=old_guarantees,
        new_guarantees=contract.guarantees,
    )

    # Invalidate cache
    from tessera.services.cache import contract_cache

    await contract_cache.delete(str(contract_id))

    return contract


@router.get("/{contract_id}/registrations")
@limit_read
async def list_contract_registrations(
    request: Request,
    auth: Auth,
    contract_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all registrations for a contract.

    Requires read scope. Returns registrations with consumer team names.
    """
    from sqlalchemy import func

    # Verify contract exists
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )

    # Query with join to get team names (exclude soft-deleted registrations)
    query = (
        select(RegistrationDB, TeamDB.name.label("team_name"))
        .outerjoin(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
        .where(RegistrationDB.contract_id == contract_id)
        .where(RegistrationDB.deleted_at.is_(None))
        .order_by(RegistrationDB.registered_at.desc())
    )

    # Get total count (exclude soft-deleted registrations)
    count_query = select(func.count()).select_from(
        select(RegistrationDB)
        .where(RegistrationDB.contract_id == contract_id)
        .where(RegistrationDB.deleted_at.is_(None))
        .subquery()
    )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    rows = result.all()

    results = []
    for reg_db, team_name in rows:
        reg_dict = Registration.model_validate(reg_db).model_dump()
        reg_dict["consumer_team_name"] = team_name
        results.append(reg_dict)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.post("/bulk", response_model=BulkContractResponse)
@limit_write
async def bulk_publish_contracts(
    request: Request,
    bulk_req: BulkContractRequest,
    auth: Auth,
    dry_run: bool = Query(True, description="Preview mode - no changes made"),
    create_proposals_for_breaking: bool = Query(
        False, description="Auto-create proposals for breaking changes (only when dry_run=false)"
    ),
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> BulkContractResponse:
    """Bulk publish contracts for multiple assets.

    This endpoint supports a two-phase workflow:

    **Phase 1: Preview (dry_run=true, default)**
    Returns what would happen without making changes. Use this to show users
    the impact before they confirm.

    **Phase 2: Execute (dry_run=false)**
    Actually publishes contracts. Set create_proposals_for_breaking=true to
    auto-create proposals for breaking changes instead of skipping them.

    Requires write scope.
    """
    # Verify publisher team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == bulk_req.published_by))
    publisher_team = team_result.scalar_one_or_none()
    if not publisher_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Publisher team not found")

    # Resource-level auth: published_by must match auth.team_id or be admin
    if bulk_req.published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            f"Cannot publish contracts on behalf of team '{publisher_team.name}'. "
            "Use an admin API key to publish on behalf of other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Convert request items to service format
    contracts_to_publish = []
    for item in bulk_req.contracts:
        compat_mode = None
        if item.compatibility_mode:
            try:
                compat_mode = CompatibilityMode(item.compatibility_mode.lower())
            except ValueError:
                pass  # Will default to BACKWARD in service

        contracts_to_publish.append(
            ContractToPublish(
                asset_id=item.asset_id,
                schema_def=item.schema_def,
                compatibility_mode=compat_mode,
                guarantees=item.guarantees,
            )
        )

    # Delegate to service
    result = await bulk_publish_service(
        session=session,
        contracts=contracts_to_publish,
        published_by=bulk_req.published_by,
        published_by_user_id=bulk_req.published_by_user_id,
        dry_run=dry_run,
        create_proposals_for_breaking=create_proposals_for_breaking,
    )

    # Convert service result to API response
    api_results = [
        BulkContractResultItem(
            asset_id=r.asset_id,
            asset_fqn=r.asset_fqn,
            status=r.status,
            contract_id=r.contract_id,
            proposal_id=r.proposal_id,
            suggested_version=r.suggested_version,
            current_version=r.current_version,
            reason=r.reason,
            breaking_changes=r.breaking_changes,
            error=r.error,
        )
        for r in result.results
    ]

    return BulkContractResponse(
        preview=result.preview,
        total=result.total,
        published=result.published,
        skipped=result.skipped,
        proposals_created=result.proposals_created,
        failed=result.failed,
        results=api_results,
    )
