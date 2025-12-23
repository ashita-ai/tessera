"""Audit run API endpoints for WAP (Write-Audit-Publish) integration.

Enables data quality tools (dbt, Great Expectations, Soda) to report test results
back to Tessera for tracking and visibility.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth
from tessera.db import AssetDB, AuditRunDB, ContractDB, get_session
from tessera.models.enums import AuditRunStatus, ContractStatus

router = APIRouter()


class AuditResultCreate(BaseModel):
    """Request body for reporting audit results."""

    status: AuditRunStatus = Field(..., description="Overall status: passed, failed, or partial")
    guarantees_checked: int = Field(0, ge=0, description="Total number of guarantees checked")
    guarantees_passed: int = Field(0, ge=0, description="Number of guarantees that passed")
    guarantees_failed: int = Field(0, ge=0, description="Number of guarantees that failed")
    triggered_by: str = Field(
        ...,
        max_length=50,
        description="Source: dbt_test, great_expectations, soda, manual",
    )
    run_id: str | None = Field(
        None,
        max_length=255,
        description="External run ID for correlation (e.g., dbt invocation_id)",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional details: failed tests, error messages, etc.",
    )
    run_at: datetime | None = Field(
        None,
        description="When the audit ran (defaults to now if not provided)",
    )


class AuditResultResponse(BaseModel):
    """Response after recording an audit result."""

    id: UUID
    asset_id: UUID
    asset_fqn: str
    contract_id: UUID | None
    contract_version: str | None
    status: AuditRunStatus
    guarantees_checked: int
    guarantees_passed: int
    guarantees_failed: int
    triggered_by: str
    run_id: str | None
    run_at: datetime


class AuditRunListItem(BaseModel):
    """Summary of an audit run for listing."""

    id: UUID
    status: AuditRunStatus
    guarantees_checked: int
    guarantees_passed: int
    guarantees_failed: int
    triggered_by: str
    run_id: str | None
    run_at: datetime
    contract_version: str | None


class AuditHistoryResponse(BaseModel):
    """Response for audit history query."""

    asset_id: UUID
    asset_fqn: str
    total_runs: int
    runs: list[AuditRunListItem]


@router.post("/{asset_id}/audit-results", response_model=AuditResultResponse)
async def report_audit_result(
    asset_id: UUID,
    result: AuditResultCreate,
    auth: Auth,
    session: AsyncSession = Depends(get_session),
) -> AuditResultResponse:
    """Report data quality audit results for an asset.

    Called by dbt post-hooks, Great Expectations, Soda, or other data quality tools
    after running tests. Enables WAP (Write-Audit-Publish) pattern tracking.

    Example dbt integration:
    ```yaml
    on-run-end:
      - "python scripts/report_to_tessera.py"
    ```

    The script parses target/run_results.json and POSTs to this endpoint.
    """
    # Look up asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    # Get active contract if one exists
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    contract = contract_result.scalar_one_or_none()

    # Create audit run record
    audit_run = AuditRunDB(
        asset_id=asset_id,
        contract_id=contract.id if contract else None,
        status=result.status,
        guarantees_checked=result.guarantees_checked,
        guarantees_passed=result.guarantees_passed,
        guarantees_failed=result.guarantees_failed,
        triggered_by=result.triggered_by,
        run_id=result.run_id,
        details=result.details,
        run_at=result.run_at or datetime.now(),
    )
    session.add(audit_run)
    await session.flush()

    return AuditResultResponse(
        id=audit_run.id,
        asset_id=asset_id,
        asset_fqn=asset.fqn,
        contract_id=contract.id if contract else None,
        contract_version=contract.version if contract else None,
        status=audit_run.status,
        guarantees_checked=audit_run.guarantees_checked,
        guarantees_passed=audit_run.guarantees_passed,
        guarantees_failed=audit_run.guarantees_failed,
        triggered_by=audit_run.triggered_by,
        run_id=audit_run.run_id,
        run_at=audit_run.run_at,
    )


@router.get("/{asset_id}/audit-history", response_model=AuditHistoryResponse)
async def get_audit_history(
    asset_id: UUID,
    auth: Auth,
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
    triggered_by: str | None = Query(None, description="Filter by source"),
    status: AuditRunStatus | None = Query(None, description="Filter by status"),
    session: AsyncSession = Depends(get_session),
) -> AuditHistoryResponse:
    """Get audit run history for an asset.

    Returns recent audit runs with optional filtering by source or status.
    Useful for dashboards showing data quality trends over time.
    """
    # Look up asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    # Build query with filters
    query = select(AuditRunDB).where(AuditRunDB.asset_id == asset_id)
    if triggered_by:
        query = query.where(AuditRunDB.triggered_by == triggered_by)
    if status:
        query = query.where(AuditRunDB.status == status)

    # Get total count
    from sqlalchemy import func

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total_runs = total_result.scalar() or 0

    # Get runs ordered by most recent
    query = query.order_by(desc(AuditRunDB.run_at)).limit(limit)
    runs_result = await session.execute(query)
    runs = runs_result.scalars().all()

    # Get contract versions for runs
    contract_ids = {r.contract_id for r in runs if r.contract_id}
    contract_versions: dict[UUID, str] = {}
    if contract_ids:
        contracts_result = await session.execute(
            select(ContractDB).where(ContractDB.id.in_(contract_ids))
        )
        for contract in contracts_result.scalars().all():
            contract_versions[contract.id] = contract.version

    return AuditHistoryResponse(
        asset_id=asset_id,
        asset_fqn=asset.fqn,
        total_runs=total_runs,
        runs=[
            AuditRunListItem(
                id=run.id,
                status=run.status,
                guarantees_checked=run.guarantees_checked,
                guarantees_passed=run.guarantees_passed,
                guarantees_failed=run.guarantees_failed,
                triggered_by=run.triggered_by,
                run_id=run.run_id,
                run_at=run.run_at,
                contract_version=(
                    contract_versions.get(run.contract_id) if run.contract_id else None
                ),
            )
            for run in runs
        ],
    )
