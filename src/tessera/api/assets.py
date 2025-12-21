"""Assets API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from tessera.models.enums import ChangeType, ContractStatus, RegistrationStatus
from tessera.services import (
    check_compatibility,
    diff_schemas,
    log_contract_published,
    log_proposal_created,
    validate_json_schema,
)

router = APIRouter()


@router.post("", response_model=Asset, status_code=201)
async def create_asset(
    asset: AssetCreate,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Create a new asset."""
    # Validate owner team exists
    result = await session.execute(select(TeamDB).where(TeamDB.id == asset.owner_team_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Owner team not found")

    db_asset = AssetDB(
        fqn=asset.fqn,
        owner_team_id=asset.owner_team_id,
        metadata_=asset.metadata,
    )
    session.add(db_asset)
    await session.flush()
    await session.refresh(db_asset)
    return db_asset


@router.get("")
async def list_assets(
    owner: UUID | None = Query(None, description="Filter by owner team ID"),
    fqn: str | None = Query(None, description="Filter by FQN pattern (case-insensitive)"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all assets with filtering and pagination."""
    query = select(AssetDB)
    if owner:
        query = query.where(AssetDB.owner_team_id == owner)
    if fqn:
        query = query.where(AssetDB.fqn.ilike(f"%{fqn}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(AssetDB.fqn)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    assets = result.scalars().all()

    return {
        "results": [Asset.model_validate(a).model_dump() for a in assets],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/search")
async def search_assets(
    q: str = Query(..., min_length=1, description="Search query"),
    owner: UUID | None = Query(None, description="Filter by owner team ID"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search assets by FQN pattern.

    Searches for assets whose FQN contains the search query (case-insensitive).
    """
    query = select(AssetDB).where(AssetDB.fqn.ilike(f"%{q}%"))
    if owner:
        query = query.where(AssetDB.owner_team_id == owner)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(AssetDB.fqn)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    assets = result.scalars().all()

    # Build response with owner team names
    results = []
    for asset in assets:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == asset.owner_team_id)
        )
        team = team_result.scalar_one_or_none()
        results.append({
            "id": str(asset.id),
            "fqn": asset.fqn,
            "owner_team_id": str(asset.owner_team_id),
            "owner_team_name": team.name if team else "Unknown",
        })

    return {
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{asset_id}", response_model=Asset)
async def get_asset(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Get an asset by ID."""
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.patch("/{asset_id}", response_model=Asset)
async def update_asset(
    asset_id: UUID,
    update: AssetUpdate,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Update an asset."""
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if update.fqn is not None:
        asset.fqn = update.fqn
    if update.owner_team_id is not None:
        asset.owner_team_id = update.owner_team_id
    if update.metadata is not None:
        asset.metadata_ = update.metadata

    await session.flush()
    await session.refresh(asset)
    return asset


@router.post("/{asset_id}/dependencies", response_model=Dependency, status_code=201)
async def create_dependency(
    asset_id: UUID,
    dependency: DependencyCreate,
    session: AsyncSession = Depends(get_session),
) -> AssetDependencyDB:
    """Register an upstream dependency for an asset.

    Creates a relationship indicating that this asset depends on another asset.
    """
    # Verify the dependent asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

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


@router.get("/{asset_id}/dependencies", response_model=list[Dependency])
async def list_dependencies(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[AssetDependencyDB]:
    """List all upstream dependencies for an asset."""
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")

    result = await session.execute(
        select(AssetDependencyDB).where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    return list(result.scalars().all())


@router.delete("/{asset_id}/dependencies/{dependency_id}", status_code=204)
async def delete_dependency(
    asset_id: UUID,
    dependency_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an upstream dependency."""
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
async def create_contract(
    asset_id: UUID,
    contract: ContractCreate,
    published_by: UUID = Query(..., description="Team ID of the publisher"),
    force: bool = Query(False, description="Force publish even if breaking (creates audit trail)"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Publish a new contract for an asset.

    Behavior:
    - If no active contract exists: auto-publish (first contract)
    - If change is compatible: auto-publish, deprecate old contract
    - If change is breaking: create a Proposal for consumer acknowledgment
    - If force=True: publish anyway but log the override

    Returns either a Contract (if published) or a Proposal (if breaking).
    """
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Verify publisher team exists
    result = await session.execute(select(TeamDB).where(TeamDB.id == published_by))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Publisher team not found")

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
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = result.scalar_one_or_none()

    # Helper to create and return the new contract
    async def publish_contract() -> ContractDB:
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

    # TODO: Notify consumers via webhook

    return {
        "action": "proposal_created",
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking_changes],
        "proposal": Proposal.model_validate(db_proposal).model_dump(),
        "message": "Breaking change detected. Proposal created for consumer acknowledgment.",
    }


@router.get("/{asset_id}/contracts", response_model=list[Contract])
async def list_asset_contracts(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ContractDB]:
    """List all contracts for an asset."""
    result = await session.execute(
        select(ContractDB).where(ContractDB.asset_id == asset_id).order_by(ContractDB.published_at)
    )
    return list(result.scalars().all())


@router.get("/{asset_id}/contracts/history")
async def get_contract_history(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the complete contract history for an asset with change summaries.

    Returns all versions ordered by publication date with change type annotations.
    """
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get all contracts ordered by published_at
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )
    contracts = list(result.scalars().all())

    # Build history with change analysis
    history = []
    for i, contract in enumerate(contracts):
        entry = {
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
async def diff_contract_versions(
    asset_id: UUID,
    from_version: str = Query(..., description="Source version to compare from"),
    to_version: str = Query(..., description="Target version to compare to"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compare two contract versions for an asset.

    Returns the diff between from_version and to_version.
    """
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get the from_version contract
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == from_version)
    )
    from_contract = result.scalar_one_or_none()
    if not from_contract:
        raise HTTPException(
            status_code=404,
            detail=f"Contract version '{from_version}' not found for this asset",
        )

    # Get the to_version contract
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == to_version)
    )
    to_contract = result.scalar_one_or_none()
    if not to_contract:
        raise HTTPException(
            status_code=404,
            detail=f"Contract version '{to_version}' not found for this asset",
        )

    # Perform diff
    diff_result = diff_schemas(from_contract.schema_def, to_contract.schema_def)
    breaking = diff_result.breaking_for_mode(from_contract.compatibility_mode)

    return {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "from_version": from_version,
        "to_version": to_version,
        "change_type": str(diff_result.change_type.value),
        "is_compatible": len(breaking) == 0,
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "all_changes": [c.to_dict() for c in diff_result.changes],
        "compatibility_mode": str(from_contract.compatibility_mode.value),
    }


@router.post("/{asset_id}/impact")
async def analyze_impact(
    asset_id: UUID,
    proposed_schema: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyze the impact of a proposed schema change.

    Compares the proposed schema against the current active contract
    and identifies breaking changes and impacted consumers.
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
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get the current active contract
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = result.scalar_one_or_none()

    # No active contract = safe to publish (first contract)
    if not current_contract:
        return {
            "change_type": "minor",
            "breaking_changes": [],
            "impacted_consumers": [],
            "safe_to_publish": True,
        }

    # Diff the schemas
    diff_result = diff_schemas(current_contract.schema_def, proposed_schema)
    breaking = diff_result.breaking_for_mode(current_contract.compatibility_mode)

    # Get impacted consumers (registrations for this contract)
    result = await session.execute(
        select(RegistrationDB)
        .where(RegistrationDB.contract_id == current_contract.id)
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
    )
    registrations = result.scalars().all()

    # Get team names for impacted consumers
    impacted_consumers = []
    for reg in registrations:
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == reg.consumer_team_id)
        )
        team = team_result.scalar_one_or_none()
        impacted_consumers.append({
            "team_id": str(reg.consumer_team_id),
            "team_name": team.name if team else "Unknown",
            "status": str(reg.status),
            "pinned_version": reg.pinned_version,
        })

    return {
        "change_type": str(diff_result.change_type),
        "breaking_changes": [bc.to_dict() for bc in breaking],
        "impacted_consumers": impacted_consumers,
        "safe_to_publish": len(breaking) == 0,
    }


@router.get("/{asset_id}/lineage")
async def get_lineage(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the complete dependency lineage for an asset.

    Returns both upstream (what this asset depends on) and downstream
    (teams/assets that consume this asset) dependencies.
    """
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get owner team name
    owner_result = await session.execute(
        select(TeamDB).where(TeamDB.id == asset.owner_team_id)
    )
    owner_team = owner_result.scalar_one_or_none()

    # Get upstream dependencies (assets this asset depends on)
    upstream = []
    deps_result = await session.execute(
        select(AssetDependencyDB).where(AssetDependencyDB.dependent_asset_id == asset_id)
    )
    dependencies = deps_result.scalars().all()

    for dep in dependencies:
        dep_asset_result = await session.execute(
            select(AssetDB).where(AssetDB.id == dep.dependency_asset_id)
        )
        dep_asset = dep_asset_result.scalar_one_or_none()
        if dep_asset:
            dep_team_result = await session.execute(
                select(TeamDB).where(TeamDB.id == dep_asset.owner_team_id)
            )
            dep_team = dep_team_result.scalar_one_or_none()
            upstream.append({
                "asset_id": str(dep.dependency_asset_id),
                "asset_fqn": dep_asset.fqn,
                "dependency_type": str(dep.dependency_type),
                "owner_team": dep_team.name if dep_team else "Unknown",
            })

    # Get all contracts for this asset
    contracts_result = await session.execute(
        select(ContractDB).where(ContractDB.asset_id == asset_id)
    )
    contracts = contracts_result.scalars().all()
    contract_ids = [c.id for c in contracts]

    # Get all registrations (consumers) for these contracts
    downstream = []
    if contract_ids:
        regs_result = await session.execute(
            select(RegistrationDB).where(RegistrationDB.contract_id.in_(contract_ids))
        )
        registrations = regs_result.scalars().all()

        # Get unique consumer teams
        consumer_team_ids = set(reg.consumer_team_id for reg in registrations)
        for team_id in consumer_team_ids:
            team_result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
            team = team_result.scalar_one_or_none()
            if team:
                # Get the registrations for this team
                team_regs = [r for r in registrations if r.consumer_team_id == team_id]
                downstream.append({
                    "team_id": str(team_id),
                    "team_name": team.name,
                    "registrations": [
                        {
                            "contract_id": str(r.contract_id),
                            "status": str(r.status),
                            "pinned_version": r.pinned_version,
                        }
                        for r in team_regs
                    ],
                })

    # Also get assets that depend on this asset (downstream assets)
    downstream_assets = []
    reverse_deps_result = await session.execute(
        select(AssetDependencyDB).where(AssetDependencyDB.dependency_asset_id == asset_id)
    )
    reverse_deps = reverse_deps_result.scalars().all()

    for dep in reverse_deps:
        dep_asset_result = await session.execute(
            select(AssetDB).where(AssetDB.id == dep.dependent_asset_id)
        )
        dep_asset = dep_asset_result.scalar_one_or_none()
        if dep_asset:
            dep_team_result = await session.execute(
                select(TeamDB).where(TeamDB.id == dep_asset.owner_team_id)
            )
            dep_team = dep_team_result.scalar_one_or_none()
            downstream_assets.append({
                "asset_id": str(dep.dependent_asset_id),
                "asset_fqn": dep_asset.fqn,
                "dependency_type": str(dep.dependency_type),
                "owner_team": dep_team.name if dep_team else "Unknown",
            })

    return {
        "asset_id": str(asset_id),
        "asset_fqn": asset.fqn,
        "owner_team_id": str(asset.owner_team_id),
        "owner_team_name": owner_team.name if owner_team else "Unknown",
        "upstream": upstream,
        "downstream": downstream,
        "downstream_assets": downstream_assets,
    }
