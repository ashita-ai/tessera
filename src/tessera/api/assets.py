"""Assets API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
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
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.config import settings
from tessera.db import (
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
    get_session,
)
from tessera.models import (
    Asset,
    AssetCreate,
    AssetUpdate,
    Contract,
    ContractCreate,
    Proposal,
)
from tessera.models.enums import APIKeyScope, ContractStatus, RegistrationStatus
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
    # Resource-level auth: must own the team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only create assets for teams you belong to",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Validate owner team exists
    result = await session.execute(select(TeamDB).where(TeamDB.id == asset.owner_team_id))
    if not result.scalar_one_or_none():
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

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
        environment=asset.environment,
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
    fqn: str | None = Query(None, description="Filter by FQN pattern (case-insensitive)"),
    environment: str | None = Query(None, description="Filter by environment"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all assets with filtering and pagination.

    Requires read scope.
    """
    query = select(AssetDB).where(AssetDB.deleted_at.is_(None))
    if owner:
        query = query.where(AssetDB.owner_team_id == owner)
    if fqn:
        query = query.where(AssetDB.fqn.ilike(f"%{fqn}%"))
    if environment:
        query = query.where(AssetDB.environment == environment)
    query = query.order_by(AssetDB.fqn)

    return await paginate(session, query, params, response_model=Asset)


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


@router.get("/{asset_id}", response_model=Asset)
@limit_read
async def get_asset(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> AssetDB | dict[str, Any]:
    """Get an asset by ID.

    Requires read scope.
    """
    # Try cache first
    cached = await get_cached_asset(str(asset_id))
    if cached:
        return cached

    result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Cache result
    await cache_asset(str(asset_id), Asset.model_validate(asset).model_dump())

    return asset


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
        raise ForbiddenError(
            "You can only update assets belonging to your team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    if update.fqn is not None:
        asset.fqn = update.fqn
    if update.owner_team_id is not None:
        asset.owner_team_id = update.owner_team_id
    if update.environment is not None:
        asset.environment = update.environment
    if update.metadata is not None:
        asset.metadata_ = update.metadata

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
        raise ForbiddenError(
            "You can only delete assets belonging to your team",
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


@router.post("/{asset_id}/contracts", status_code=201)
@limit_write
async def create_contract(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    contract: ContractCreate,
    published_by: UUID = Query(..., description="Team ID of the publisher"),
    force: bool = Query(False, description="Force publish even if breaking (creates audit trail)"),
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

    Returns either a Contract (if published) or a Proposal (if breaking).
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only publish contracts for assets belonging to your team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Verify publisher team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == published_by))
    publisher_team = team_result.scalar_one_or_none()
    if not publisher_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Publisher team not found")

    # Resource-level auth: published_by must match auth.team_id or be admin
    if published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only publish contracts on behalf of your own team",
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

    # Get current active contract
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # Helper to create and return the new contract
    # Uses nested transaction (savepoint) to ensure atomicity of multi-step publish
    async def publish_contract() -> ContractDB:
        async with session.begin_nested():
            db_contract = ContractDB(
                asset_id=asset_id,
                version=contract.version,
                schema_def=contract.schema_def,
                compatibility_mode=contract.compatibility_mode,
                guarantees=contract.guarantees.model_dump() if contract.guarantees else None,
                published_by=published_by,
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
        return {
            "action": "published",
            "contract": contract_data,
        }

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
        return {
            "action": "published",
            "change_type": str(diff_result.change_type),
            "contract": contract_data,
        }

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
        return {
            "action": "force_published",
            "change_type": str(diff_result.change_type),
            "breaking_changes": [bc.to_dict() for bc in breaking_changes],
            "contract": contract_data,
            "warning": "Breaking change was force-published. Consumers may be affected.",
        }

    # Breaking change without force = create proposal
    db_proposal = ProposalDB(
        asset_id=asset_id,
        proposed_schema=contract.schema_def,
        change_type=diff_result.change_type,
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
        proposed_by=published_by,
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
        proposed_version=contract.version,
        breaking_changes=[bc.to_dict() for bc in breaking_changes],
        impacted_consumers=impacted_consumers,
    )

    # Send Slack notification
    await notify_proposal_created(
        asset_fqn=asset.fqn,
        version=contract.version,
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

    Requires read scope.
    """
    # Try cache first (only for default pagination to keep cache simple)
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        cached = await get_cached_asset_contracts_list(str(asset_id))
        if cached:
            return cached

    query = (
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )
    result = await paginate(session, query, params, response_model=Contract)

    # Cache result if default pagination
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        await cache_asset_contracts_list(str(asset_id), result)

    return result


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
