"""Contracts API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import ContractDB, RegistrationDB, get_session
from tessera.models import Contract, Registration
from tessera.models.enums import ContractStatus

router = APIRouter()


@router.get("")
async def list_contracts(
    asset_id: UUID | None = Query(None, description="Filter by asset ID"),
    status: ContractStatus | None = Query(None, description="Filter by status"),
    version: str | None = Query(None, description="Filter by version pattern"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all contracts with filtering and pagination."""
    query = select(ContractDB)
    if asset_id:
        query = query.where(ContractDB.asset_id == asset_id)
    if status:
        query = query.where(ContractDB.status == status)
    if version:
        query = query.where(ContractDB.version.ilike(f"%{version}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(ContractDB.published_at.desc())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    contracts = result.scalars().all()

    return {
        "results": [Contract.model_validate(c).model_dump() for c in contracts],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{contract_id}", response_model=Contract)
async def get_contract(
    contract_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ContractDB:
    """Get a contract by ID."""
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.get("/{contract_id}/registrations", response_model=list[Registration])
async def list_contract_registrations(
    contract_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[RegistrationDB]:
    """List all registrations for a contract."""
    # Verify contract exists
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.contract_id == contract_id)
    )
    return list(result.scalars().all())
