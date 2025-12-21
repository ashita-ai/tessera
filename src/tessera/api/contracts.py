"""Contracts API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.errors import ErrorCode, NotFoundError
from tessera.db import AssetDB, ContractDB, RegistrationDB, get_session
from tessera.models import Contract, Registration
from tessera.models.enums import CompatibilityMode, ContractStatus
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


@router.post("/compare", response_model=ContractCompareResponse)
async def compare_contracts(
    request: ContractCompareRequest,
    session: AsyncSession = Depends(get_session),
) -> ContractCompareResponse:
    """Compare two contracts and return the differences."""
    # Fetch both contracts
    result1 = await session.execute(
        select(ContractDB).where(ContractDB.id == request.contract_id_1)
    )
    contract1 = result1.scalar_one_or_none()
    if not contract1:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{request.contract_id_1}' not found",
            details={"contract_id": str(request.contract_id_1)},
        )

    result2 = await session.execute(
        select(ContractDB).where(ContractDB.id == request.contract_id_2)
    )
    contract2 = result2.scalar_one_or_none()
    if not contract2:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{request.contract_id_2}' not found",
            details={"contract_id": str(request.contract_id_2)},
        )

    # Use specified compatibility mode or default to first contract's mode
    mode = request.compatibility_mode or contract1.compatibility_mode

    # Perform diff
    diff_result = diff_schemas(contract1.schema_def, contract2.schema_def)
    breaking = diff_result.breaking_for_mode(mode)

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
        change_type=str(diff_result.change_type.value),
        is_compatible=len(breaking) == 0,
        breaking_changes=[bc.to_dict() for bc in breaking],
        all_changes=[c.to_dict() for c in diff_result.changes],
        compatibility_mode=str(mode.value),
    )


@router.get("/{contract_id}", response_model=Contract)
async def get_contract(
    contract_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ContractDB:
    """Get a contract by ID."""
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )
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
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )

    result = await session.execute(
        select(RegistrationDB).where(RegistrationDB.contract_id == contract_id)
    )
    return list(result.scalars().all())
