"""Registrations API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db import ContractDB, RegistrationDB, get_session
from tessera.models import Registration, RegistrationCreate, RegistrationUpdate
from tessera.models.enums import APIKeyScope, RegistrationStatus
from tessera.services import audit
from tessera.services.audit import AuditAction

router = APIRouter()


@router.post("", response_model=Registration, status_code=201)
@limit_write
async def create_registration(
    request: Request,
    auth: Auth,
    registration: RegistrationCreate,
    contract_id: UUID = Query(..., description="Contract ID to register for"),
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Register a consumer for a contract.

    Requires write scope.
    """
    # Resource-level auth: consumer_team_id must match auth.team_id or be admin
    if registration.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only register for contracts on behalf of your own team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Verify contract exists
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(ErrorCode.CONTRACT_NOT_FOUND, "Contract not found")

    db_registration = RegistrationDB(
        contract_id=contract_id,
        consumer_team_id=registration.consumer_team_id,
        pinned_version=registration.pinned_version,
    )
    session.add(db_registration)
    await session.flush()
    await session.refresh(db_registration)

    # Audit log registration creation
    await audit.log_event(
        session=session,
        entity_type="registration",
        entity_id=db_registration.id,
        action=AuditAction.REGISTRATION_CREATED,
        actor_id=registration.consumer_team_id,
        payload={"contract_id": str(contract_id)},
    )

    return db_registration


@router.get("")
@limit_read
async def list_registrations(
    request: Request,
    response: Response,
    auth: Auth,
    consumer_team_id: UUID | None = Query(None, description="Filter by consumer team ID"),
    contract_id: UUID | None = Query(None, description="Filter by contract ID"),
    status: RegistrationStatus | None = Query(None, description="Filter by status"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all registrations with filtering and pagination.

    Requires read scope. Returns X-Total-Count header with total count.
    """
    query = select(RegistrationDB)
    if consumer_team_id:
        query = query.where(RegistrationDB.consumer_team_id == consumer_team_id)
    if contract_id:
        query = query.where(RegistrationDB.contract_id == contract_id)
    if status:
        query = query.where(RegistrationDB.status == status)
    query = query.order_by(RegistrationDB.registered_at.desc())

    return await paginate(session, query, params, response_model=Registration, response=response)


@router.get("/{registration_id}", response_model=Registration)
@limit_read
async def get_registration(
    request: Request,
    auth: Auth,
    registration_id: UUID,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Get a registration by ID.

    Requires read scope.
    """
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise NotFoundError(ErrorCode.REGISTRATION_NOT_FOUND, "Registration not found")
    return registration


@router.patch("/{registration_id}", response_model=Registration)
@limit_write
async def update_registration(
    request: Request,
    auth: Auth,
    registration_id: UUID,
    update: RegistrationUpdate,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> RegistrationDB:
    """Update a registration.

    Requires write scope.
    """
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise NotFoundError(ErrorCode.REGISTRATION_NOT_FOUND, "Registration not found")

    # Resource-level auth: must own the registration's consumer team or be admin
    if registration.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only update registrations belonging to your team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    if update.pinned_version is not None:
        registration.pinned_version = update.pinned_version
    if update.status is not None:
        registration.status = update.status

    await session.flush()
    await session.refresh(registration)

    # Audit log registration update
    await audit.log_event(
        session=session,
        entity_type="registration",
        entity_id=registration_id,
        action=AuditAction.REGISTRATION_UPDATED,
        actor_id=auth.team_id,
        payload={
            "pinned_version_changed": update.pinned_version is not None,
            "status_changed": update.status is not None,
        },
    )

    return registration


@router.delete("/{registration_id}", status_code=204)
@limit_write
async def delete_registration(
    request: Request,
    auth: Auth,
    registration_id: UUID,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a registration.

    Requires write scope.
    """
    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise NotFoundError(ErrorCode.REGISTRATION_NOT_FOUND, "Registration not found")

    # Resource-level auth: must own the registration's consumer team or be admin
    if registration.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only delete registrations belonging to your team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Audit log registration deletion
    await audit.log_event(
        session=session,
        entity_type="registration",
        entity_id=registration_id,
        action=AuditAction.REGISTRATION_DELETED,
        actor_id=auth.team_id,
        payload={"contract_id": str(registration.contract_id)},
    )

    await session.delete(registration)
