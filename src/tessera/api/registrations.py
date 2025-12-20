"""Registrations API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import ContractDB, RegistrationDB, get_session
from tessera.models import Registration, RegistrationCreate, RegistrationUpdate

router = APIRouter()


@router.post("", response_model=Registration, status_code=201)
async def create_registration(
    registration: RegistrationCreate,
    contract_id: UUID = Query(..., description="Contract ID to register for"),
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Register a consumer for a contract."""
    # Verify contract exists
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    db_registration = RegistrationDB(
        contract_id=contract_id,
        consumer_team_id=registration.consumer_team_id,
        pinned_version=registration.pinned_version,
    )
    session.add(db_registration)
    await session.flush()
    await session.refresh(db_registration)
    return db_registration


@router.get("/{registration_id}", response_model=Registration)
async def get_registration(
    registration_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Get a registration by ID."""
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    return registration


@router.patch("/{registration_id}", response_model=Registration)
async def update_registration(
    registration_id: UUID,
    update: RegistrationUpdate,
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Update a registration."""
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    if update.pinned_version is not None:
        registration.pinned_version = update.pinned_version
    if update.status is not None:
        registration.status = update.status

    await session.flush()
    await session.refresh(registration)
    return registration


@router.delete("/{registration_id}", status_code=204)
async def delete_registration(
    registration_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a registration."""
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    await session.delete(registration)
