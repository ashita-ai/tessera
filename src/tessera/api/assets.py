"""Assets API endpoints."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead, RequireWrite
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.config import settings
from tessera.db import (
    AssetDB,
    AssetDependencyDB,
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
    Dependency,
    DependencyCreate,
    Proposal,
)
from tessera.models.enums import APIKeyScope, ContractStatus, RegistrationStatus
from tessera.services.cache import (
    asset_cache,
    cache_asset,
    cache_asset_contracts_list,
    cache_asset_search,
    cache_contract,
    contract_cache,
    get_cached_asset,
    get_cached_asset_contracts_list,
    get_cached_asset_search,
    get_cached_contract,
    get_cached_schema_diff,
    invalidate_asset,
    cache_schema_diff,
)
from tessera.services import (
    check_compatibility,
    diff_schemas,
    log_contract_published,
    log_proposal_created,
    validate_json_schema,
)
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
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only create assets for teams you belong to",
            },
        )

    # Validate owner team exists
    result = await session.execute(select(TeamDB).where(TeamDB.id == asset.owner_team_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Owner team not found")

    # Check for duplicate FQN
    existing = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == asset.fqn)
        .where(AssetDB.environment == asset.environment)
        .where(AssetDB.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Asset with FQN '{asset.fqn}' already exists in environment '{asset.environment}'")

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
        raise HTTPException(status_code=409, detail=f"Asset with FQN '{asset.fqn}' already exists")
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
    base_query = (
        select(AssetDB)
        .where(AssetDB.fqn.ilike(f"%{q}%"))
        .where(AssetDB.deleted_at.is_(None))
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
        select(AssetDB)
        .where(AssetDB.id == asset_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

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
        select(AssetDB)
        .where(AssetDB.id == asset_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only update assets belonging to your team",
            },
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
        select(AssetDB)
        .where(AssetDB.id == asset_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Resource-level auth
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only delete assets belonging to your team",
            },
        )

    asset.deleted_at = datetime.now(timezone.utc)
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
    result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.deleted_at is None:
        return asset

    asset.deleted_at = None
    await session.flush()
    await session.refresh(asset)

    # Invalidate cache
    await asset_cache.delete(str(asset_id))

    return asset


@router.post("/{asset_id}/dependencies", response_model=Dependency, status_code=201)
@limit_write
async def create_dependency(
    request: Request,
    asset_id: UUID,
    dependency: DependencyCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> AssetDependencyDB:
    """Register an upstream dependency for an asset.

    Creates a relationship indicating that this asset depends on another asset.
    Requires write scope.
    """
    # Verify the dependent asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Resource-level auth: must own the dependent asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only add dependencies to assets belonging to your team",
            },
        )

    # Verify the dependency asset exists
    result = await session.execute(
        select(AssetDB).where(AssetDB.id == dependency.depends_on_asset_id)
    )
    dependency_asset = result.scalar_one_or_none()
    if not dependency_asset:
        raise HTTPException(status_code=404, detail="Dependency asset not found")

    # Prevent self-dependency
    if asset_id == dependency.depends_on_asset_id:
        raise HTTPException(status_code=400, detail="Asset cannot depend on itself")

    # Check for duplicate dependency
    result = await session.execute(
        select(AssetDependencyDB)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
        .where(AssetDependencyDB.dependency_asset_id == dependency.depends_on_asset_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Dependency already exists")

    db_dependency = AssetDependencyDB(
        dependent_asset_id=asset_id,
        dependency_asset_id=dependency.depends_on_asset_id,
        dependency_type=dependency.dependency_type,
    )
    session.add(db_dependency)
    await session.flush()
    await session.refresh(db_dependency)
    return db_dependency


@router.get("/{asset_id}/dependencies")
@limit_read
async def list_dependencies(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all upstream dependencies for an asset.

    Requires read scope.
    """
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    if not asset_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")

    query = select(AssetDependencyDB).where(AssetDependencyDB.dependent_asset_id == asset_id)
    return await paginate(session, query, params, response_model=Dependency)


@router.delete("/{asset_id}/dependencies/{dependency_id}", status_code=204)
@limit_write
async def delete_dependency(
    request: Request,
    asset_id: UUID,
    dependency_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an upstream dependency.

    Requires write scope.
    """
    result = await session.execute(
        select(AssetDependencyDB)
        .where(AssetDependencyDB.id == dependency_id)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    dependency = result.scalar_one_or_none()
    if not dependency:
        raise HTTPException(status_code=404, detail="Dependency not found")

    await session.delete(dependency)
    await session.flush()


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
        raise HTTPException(status_code=404, detail="Asset not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only publish contracts for assets belonging to your team",
            },
        )

    # Verify publisher team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == published_by))
    publisher_team = team_result.scalar_one_or_none()
    if not publisher_team:
        raise HTTPException(status_code=404, detail="Publisher team not found")

    # Resource-level auth: published_by must match auth.team_id or be admin
    if published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only publish contracts on behalf of your own team",
            },
        )

    # Resource-level auth: published_by must match auth.team_id or be admin
    if published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only publish contracts on behalf of your own team",
            },
        )

    # Validate schema is valid JSON Schema
    is_valid, errors = validate_json_schema(contract.schema_def)
    if not is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_SCHEMA",
                "message": "Invalid JSON Schema",
                "errors": errors,
            },
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
        await cache_contract(str(new_contract.id), Contract.model_validate(new_contract).model_dump())
        return {
            "action": "published",
            "contract": Contract.model_validate(new_contract).model_dump(),
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
        await cache_contract(str(new_contract.id), Contract.model_validate(new_contract).model_dump())
        return {
            "action": "published",
            "change_type": str(diff_result.change_type),
            "contract": Contract.model_validate(new_contract).model_dump(),
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
        await cache_contract(str(new_contract.id), Contract.model_validate(new_contract).model_dump())
        return {
            "action": "force_published",
            "change_type": str(diff_result.change_type),
            "breaking_changes": [bc.to_dict() for bc in breaking_changes],
            "contract": Contract.model_validate(new_contract).model_dump(),
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
        raise HTTPException(status_code=404, detail="Asset not found")

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
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get the from_version contract
    from_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == from_version)
    )
    from_contract = from_result.scalar_one_or_none()
    if not from_contract:
        raise HTTPException(
            status_code=404,
            detail=f"Contract version '{from_version}' not found for this asset",
        )

    # Get the to_version contract
    to_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == to_version)
    )
    to_contract = to_result.scalar_one_or_none()
    if not to_contract:
        raise HTTPException(
            status_code=404,
            detail=f"Contract version '{to_version}' not found for this asset",
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

    breaking = [] # Re-calculate breaking based on compatibility mode of from_contract
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


@router.post("/{asset_id}/impact")
@limit_read
async def analyze_impact(
    request: Request,
    asset_id: UUID,
    proposed_schema: dict[str, Any],
    auth: Auth,
    depth: int = Query(
        settings.impact_depth_default,
        ge=1,
        le=settings.impact_depth_max,
    ),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyze the impact of a proposed schema change.

    Compares the proposed schema against the current active contract
    and recursively identifies breaking changes and impacted consumers.
    Requires read scope.
    """
    # Validate proposed schema is valid JSON Schema
    is_valid, errors = validate_json_schema(proposed_schema)
    if not is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_SCHEMA",
                "message": "Invalid JSON Schema",
                "errors": errors,
            },
        )

    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get the current active contract
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # No active contract = safe to publish (first contract)
    if not current_contract:
        return {
            "change_type": "minor",
            "breaking_changes": [],
            "impacted_consumers": [],
            "impacted_assets": [],
            "safe_to_publish": True,
        }

    # Diff the schemas
    diff_result = diff_schemas(current_contract.schema_def, proposed_schema)
    breaking = diff_result.breaking_for_mode(current_contract.compatibility_mode)

    # Recursive traversal to find all impacted assets and teams
    visited_assets: set[UUID] = set()
    impacted_teams: dict[UUID, dict[str, Any]] = {}
    impacted_assets: list[dict[str, Any]] = []

    async def traverse(current_id: UUID, current_depth: int):
        if current_depth > depth or current_id in visited_assets:
            return
        visited_assets.add(current_id)

        # 1. Get direct consumers (registrations) for this asset
        # We need the active contract for the current_id
        c_result = await session.execute(
            select(ContractDB.id)
            .where(ContractDB.asset_id == current_id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .limit(1)
        )
        active_contract_id = c_result.scalar()

        if active_contract_id:
            regs_result = await session.execute(
                select(RegistrationDB, TeamDB)
                .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
                .where(RegistrationDB.contract_id == active_contract_id)
                .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
            )
            for reg, team in regs_result.all():
                if team.id not in impacted_teams:
                    impacted_teams[team.id] = {
                        "team_id": str(team.id),
                        "team_name": team.name,
                        "status": str(reg.status),
                        "pinned_version": reg.pinned_version,
                        "depth": current_depth,
                    }

        # 2. Get downstream assets
        downstream_result = await session.execute(
            select(AssetDB, AssetDependencyDB.dependency_type)
            .join(AssetDependencyDB, AssetDependencyDB.dependent_asset_id == AssetDB.id)
            .where(AssetDependencyDB.dependency_asset_id == current_id)
        )
        for ds_asset, dep_type in downstream_result.all():
            if ds_asset.id not in visited_assets:
                impacted_assets.append({
                    "asset_id": str(ds_asset.id),
                    "fqn": ds_asset.fqn,
                    "dependency_type": str(dep_type),
                    "depth": current_depth,
                })
                await traverse(ds_asset.id, current_depth + 1)

    # Start traversal
    await traverse(asset_id, 1)

    # Remove the starting asset from impacted_assets if it was added (it shouldn't be)
    impacted_assets = [a for a in impacted_assets if a["asset_id"] != str(asset_id)]

    return {
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "impacted_consumers": list(impacted_teams.values()),
        "impacted_assets": impacted_assets,
        "safe_to_publish": len(breaking) == 0,
        "traversal_depth": depth,
    }


@router.get("/{asset_id}/lineage")
@limit_read
async def get_lineage(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the complete dependency lineage for an asset.

    Returns both upstream (what this asset depends on) and downstream
    (teams/assets that consume this asset) dependencies.
    Requires read scope.
    """
    # Try cache
    cache_key = f"lineage:{asset_id}"
    cached = await asset_cache.get(cache_key)
    if cached:
        return cached

    # Get asset with owner team in single query (fixes N+1)
    result = await session.execute(
        select(AssetDB, TeamDB)
        .join(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .where(AssetDB.id == asset_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset, owner_team = row

    # Alias for joining dependency assets and their teams
    dep_asset = AssetDB.__table__.alias("dep_asset")
    dep_team = TeamDB.__table__.alias("dep_team")

    # Get upstream dependencies with asset and team info in single query (fixes N+1)
    upstream_result = await session.execute(
        select(
            AssetDependencyDB.dependency_asset_id,
            AssetDependencyDB.dependency_type,
            dep_asset.c.fqn,
            dep_team.c.name,
        )
        .join(dep_asset, AssetDependencyDB.dependency_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    upstream = [
        {
            "asset_id": str(dep_asset_id),
            "asset_fqn": fqn,
            "dependency_type": str(dep_type),
            "owner_team": team_name,
        }
        for dep_asset_id, dep_type, fqn, team_name in upstream_result.all()
    ]

    # Get all contracts for this asset
    contracts_result = await session.execute(
        select(ContractDB.id).where(ContractDB.asset_id == asset_id)
    )
    contract_ids = [c for (c,) in contracts_result.all()]

    # Get registrations with team info in single query (fixes N+1)
    downstream = []
    if contract_ids:
        regs_result = await session.execute(
            select(RegistrationDB, TeamDB)
            .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
            .where(RegistrationDB.contract_id.in_(contract_ids))
        )
        rows = regs_result.all()

        # Group registrations by team
        team_regs: dict[UUID, list[tuple[RegistrationDB, TeamDB]]] = defaultdict(list)
        for reg, team in rows:
            team_regs[team.id].append((reg, team))

        for team_id, regs in team_regs.items():
            team_name = regs[0][1].name  # All regs have same team
            downstream.append(
                {
                    "team_id": str(team_id),
                    "team_name": team_name,
                    "registrations": [
                        {
                            "contract_id": str(r.contract_id),
                            "status": str(r.status),
                            "pinned_version": r.pinned_version,
                        }
                        for r, _ in regs
                    ],
                }
            )

    # Get downstream assets (assets that depend on this one) with team info (fixes N+1)
    downstream_assets_result = await session.execute(
        select(
            AssetDependencyDB.dependent_asset_id,
            AssetDependencyDB.dependency_type,
            dep_asset.c.fqn,
            dep_team.c.name,
        )
        .join(dep_asset, AssetDependencyDB.dependent_asset_id == dep_asset.c.id)
        .join(dep_team, dep_asset.c.owner_team_id == dep_team.c.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
    )
    downstream_assets = [
        {
            "asset_id": str(dep_asset_id),
            "asset_fqn": fqn,
            "dependency_type": str(dep_type),
            "owner_team": team_name,
        }
        for dep_asset_id, dep_type, fqn, team_name in downstream_assets_result.all()
    ]

    res = {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "owner_team_id": str(asset.owner_team_id),
        "owner_team_name": owner_team.name,
        "upstream": upstream,
        "downstream": downstream,
        "downstream_assets": downstream_assets,
    }

    # Cache result (5 minutes)
    await asset_cache.set(f"lineage:{asset_id}", res, ttl=300)

    return res
