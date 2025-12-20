"""Contracts API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import ContractDB, RegistrationDB, get_session
from tessera.models import Contract, Registration

router = APIRouter()


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
