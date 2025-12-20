"""Assets API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, ContractDB, get_session
from tessera.models import Asset, AssetCreate, AssetUpdate, Contract, ContractCreate

router = APIRouter()


@router.post("", response_model=Asset, status_code=201)
async def create_asset(
    asset: AssetCreate,
    session: AsyncSession = Depends(get_session),
) -> AssetDB:
    """Create a new asset."""
    db_asset = AssetDB(
        fqn=asset.fqn,
        owner_team_id=asset.owner_team_id,
        metadata_=asset.metadata,
    )
    session.add(db_asset)
    await session.flush()
    await session.refresh(db_asset)
    return db_asset


@router.get("", response_model=list[Asset])
async def list_assets(
    owner: UUID | None = Query(None, description="Filter by owner team ID"),
    session: AsyncSession = Depends(get_session),
) -> list[AssetDB]:
    """List all assets, optionally filtered by owner."""
    query = select(AssetDB)
    if owner:
        query = query.where(AssetDB.owner_team_id == owner)
    result = await session.execute(query)
    return list(result.scalars().all())


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


@router.post("/{asset_id}/contracts", response_model=Contract, status_code=201)
async def create_contract(
    asset_id: UUID,
    contract: ContractCreate,
    published_by: UUID = Query(..., description="Team ID of the publisher"),
    session: AsyncSession = Depends(get_session),
) -> ContractDB:
    """Publish a new contract for an asset."""
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    db_contract = ContractDB(
        asset_id=asset_id,
        version=contract.version,
        schema_def=contract.schema_def,
        compatibility_mode=contract.compatibility_mode,
        guarantees=contract.guarantees.model_dump() if contract.guarantees else None,
        published_by=published_by,
    )
    session.add(db_contract)
    await session.flush()
    await session.refresh(db_contract)
    return db_contract


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


@router.get("/{asset_id}/impact")
async def analyze_impact(
    asset_id: UUID,
    proposed_schema: dict[str, Any] = Query(..., description="Proposed schema as JSON"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Analyze the impact of a proposed schema change."""
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # TODO: Implement actual schema diffing and impact analysis
    # For now, return a placeholder response
    return {
        "change_type": "unknown",
        "breaking_changes": [],
        "impacted_consumers": [],
        "safe_to_publish": True,
    }


@router.get("/{asset_id}/lineage")
async def get_lineage(
    asset_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the dependency lineage for an asset."""
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # TODO: Implement actual lineage traversal
    return {
        "asset_id": str(asset_id),
        "upstream": [],
        "downstream": [],
    }
