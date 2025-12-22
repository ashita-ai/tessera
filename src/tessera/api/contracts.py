"""Contracts API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import ErrorCode, NotFoundError
from tessera.api.pagination import PaginationParams, paginate, pagination_params
from tessera.api.rate_limit import limit_read
from tessera.db import ContractDB, RegistrationDB, get_session
from tessera.models import Contract, Registration
from tessera.models.enums import CompatibilityMode, ContractStatus
from tessera.services.cache import (
    cache_contract,
    cache_schema_diff,
    get_cached_contract,
    get_cached_schema_diff,
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

    Requires read scope.
    """
    query = select(ContractDB)
    if asset_id:
        query = query.where(ContractDB.asset_id == asset_id)
    if status:
        query = query.where(ContractDB.status == status)
    if version:
        query = query.where(ContractDB.version.ilike(f"%{version}%"))
    query = query.order_by(ContractDB.published_at.desc())

    return await paginate(session, query, params, response_model=Contract)


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


@router.get("/{contract_id}", response_model=Contract)
@limit_read
async def get_contract(
    request: Request,
    contract_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ContractDB | dict[str, Any]:
    """Get a contract by ID.

    Requires read scope.
    """
    # Try cache first
    cached = await get_cached_contract(str(contract_id))
    if cached:
        return cached

    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )

    # Cache result
    await cache_contract(str(contract_id), Contract.model_validate(contract).model_dump())

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

    Requires read scope.
    """
    # Verify contract exists
    result = await session.execute(select(ContractDB).where(ContractDB.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            code=ErrorCode.CONTRACT_NOT_FOUND,
            message=f"Contract with ID '{contract_id}' not found",
            details={"contract_id": str(contract_id)},
        )

    query = select(RegistrationDB).where(RegistrationDB.contract_id == contract_id)
    return await paginate(session, query, params, response_model=Registration)
