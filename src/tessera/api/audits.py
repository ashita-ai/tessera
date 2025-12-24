"""Audit run API endpoints for data quality tracking.

Enables data quality tools (dbt, Great Expectations, Soda) to report test results
back to Tessera for tracking, visibility, and enforcement.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth
from tessera.api.errors import ErrorCode, ForbiddenError, NotFoundError
from tessera.db import AssetDB, AuditRunDB, ContractDB, get_session
from tessera.models.enums import APIKeyScope, AuditRunStatus, ContractStatus

# Size limits for JSON fields (in bytes when serialized)
MAX_METADATA_SIZE = 10 * 1024  # 10KB per guarantee metadata
MAX_DETAILS_SIZE = 100 * 1024  # 100KB for details
MAX_GUARANTEE_RESULTS = 1000  # Max number of guarantees per audit


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC.

    SQLite returns naive datetimes while PostgreSQL returns timezone-aware ones.
    This normalizes both to UTC for consistent comparisons.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


router = APIRouter()


class GuaranteeResult(BaseModel):
    """Result of checking a single guarantee/test."""

    guarantee_id: str = Field(
        ..., max_length=255, description="Identifier: test name, guarantee key, etc."
    )
    passed: bool = Field(..., description="Whether this guarantee passed")
    error_message: str | None = Field(None, max_length=2000, description="Error message if failed")
    rows_checked: int | None = Field(None, ge=0, description="Number of rows checked")
    rows_failed: int | None = Field(None, ge=0, description="Number of rows that failed")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context")

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Limit metadata size to prevent abuse."""
        serialized = json.dumps(v)
        if len(serialized) > MAX_METADATA_SIZE:
            raise ValueError(
                f"metadata exceeds maximum size of {MAX_METADATA_SIZE} bytes "
                f"(got {len(serialized)} bytes)"
            )
        return v


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
    guarantee_results: list[GuaranteeResult] = Field(
        default_factory=list,
        description="Per-guarantee/test results for granular tracking",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional details: failed tests, error messages, etc.",
    )
    run_at: datetime | None = Field(
        None,
        description="When the audit ran (defaults to now if not provided)",
    )

    @field_validator("guarantee_results")
    @classmethod
    def validate_guarantee_results_count(cls, v: list[GuaranteeResult]) -> list[GuaranteeResult]:
        """Limit number of guarantee results to prevent abuse."""
        if len(v) > MAX_GUARANTEE_RESULTS:
            raise ValueError(
                f"guarantee_results exceeds maximum count of {MAX_GUARANTEE_RESULTS} (got {len(v)})"
            )
        return v

    @field_validator("details")
    @classmethod
    def validate_details_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Limit details size to prevent abuse."""
        serialized = json.dumps(v)
        if len(serialized) > MAX_DETAILS_SIZE:
            raise ValueError(
                f"details exceeds maximum size of {MAX_DETAILS_SIZE} bytes "
                f"(got {len(serialized)} bytes)"
            )
        return v


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
    guarantee_results: list[GuaranteeResult] = []


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
    failed_guarantees: list[str] = []  # Names of failed guarantees for quick view


class AuditHistoryResponse(BaseModel):
    """Response for audit history query."""

    asset_id: UUID
    asset_fqn: str
    total_runs: int
    runs: list[AuditRunListItem]


class AuditTrendPeriod(BaseModel):
    """Audit statistics for a time period."""

    total_runs: int
    passed: int
    failed: int
    partial: int
    failure_rate: float  # 0.0 - 1.0
    most_failed_guarantees: list[dict[str, Any]]  # [{guarantee_id, failure_count}]


class AuditTrendsResponse(BaseModel):
    """Response for audit trends analysis."""

    asset_id: UUID
    asset_fqn: str
    last_run: dict[str, Any] | None  # Most recent run summary
    last_24h: AuditTrendPeriod
    last_7d: AuditTrendPeriod
    last_30d: AuditTrendPeriod
    alerts: list[str]  # Alert messages for high failure rates, etc.


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
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, f"Asset {asset_id} not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot report audit results for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Get active contract if one exists
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    contract = contract_result.scalar_one_or_none()

    # Store guarantee_results in details JSON
    details = result.details.copy()
    if result.guarantee_results:
        details["guarantee_results"] = [gr.model_dump() for gr in result.guarantee_results]

    # Auto-calculate counts from guarantee_results if provided and counts are 0
    guarantees_checked = result.guarantees_checked
    guarantees_passed = result.guarantees_passed
    guarantees_failed = result.guarantees_failed
    if result.guarantee_results and guarantees_checked == 0:
        guarantees_checked = len(result.guarantee_results)
        guarantees_passed = sum(1 for gr in result.guarantee_results if gr.passed)
        guarantees_failed = sum(1 for gr in result.guarantee_results if not gr.passed)

    # Create audit run record
    audit_run = AuditRunDB(
        asset_id=asset_id,
        contract_id=contract.id if contract else None,
        status=result.status,
        guarantees_checked=guarantees_checked,
        guarantees_passed=guarantees_passed,
        guarantees_failed=guarantees_failed,
        triggered_by=result.triggered_by,
        run_id=result.run_id,
        details=details,
        run_at=result.run_at or datetime.now(UTC),
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
        guarantee_results=result.guarantee_results,
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
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, f"Asset {asset_id} not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot view audit history for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Build query with filters
    query = select(AuditRunDB).where(AuditRunDB.asset_id == asset_id)
    if triggered_by:
        query = query.where(AuditRunDB.triggered_by == triggered_by)
    if status:
        query = query.where(AuditRunDB.status == status)

    # Get total count
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

    # Build run list items with failed guarantee names
    run_items = []
    for run in runs:
        # Extract failed guarantee names from details
        failed_guarantees: list[str] = []
        if run.details and "guarantee_results" in run.details:
            for gr in run.details["guarantee_results"]:
                if not gr.get("passed", True):
                    failed_guarantees.append(gr.get("guarantee_id", "unknown"))

        run_items.append(
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
                failed_guarantees=failed_guarantees,
            )
        )

    return AuditHistoryResponse(
        asset_id=asset_id,
        asset_fqn=asset.fqn,
        total_runs=total_runs,
        runs=run_items,
    )


def _compute_trend_period(runs: list[AuditRunDB]) -> AuditTrendPeriod:
    """Compute audit statistics for a set of runs."""
    total = len(runs)
    passed = sum(1 for r in runs if r.status == AuditRunStatus.PASSED)
    failed = sum(1 for r in runs if r.status == AuditRunStatus.FAILED)
    partial = sum(1 for r in runs if r.status == AuditRunStatus.PARTIAL)

    # Calculate failure rate (failed + partial count as failures)
    failure_rate = (failed + partial) / total if total > 0 else 0.0

    # Count guarantee failures across all runs
    guarantee_failures: dict[str, int] = {}
    for run in runs:
        if run.details and "guarantee_results" in run.details:
            for gr in run.details["guarantee_results"]:
                if not gr.get("passed", True):
                    gid = gr.get("guarantee_id", "unknown")
                    guarantee_failures[gid] = guarantee_failures.get(gid, 0) + 1

    # Sort by failure count, take top 10
    sorted_failures = sorted(guarantee_failures.items(), key=lambda x: x[1], reverse=True)[:10]
    most_failed = [{"guarantee_id": k, "failure_count": v} for k, v in sorted_failures]

    return AuditTrendPeriod(
        total_runs=total,
        passed=passed,
        failed=failed,
        partial=partial,
        failure_rate=failure_rate,
        most_failed_guarantees=most_failed,
    )


@router.get("/{asset_id}/audit-trends", response_model=AuditTrendsResponse)
async def get_audit_trends(
    asset_id: UUID,
    auth: Auth,
    session: AsyncSession = Depends(get_session),
) -> AuditTrendsResponse:
    """Get audit trend analysis for an asset.

    Returns aggregated statistics for 24h, 7d, and 30d periods including:
    - Pass/fail/partial counts
    - Failure rate (0.0 - 1.0)
    - Most frequently failing guarantees
    - Alerts for high failure rates

    Useful for dashboards and monitoring data quality trends over time.
    """
    # Look up asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, f"Asset {asset_id} not found")

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot view audit trends for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Get all runs from the last 30 days
    cutoff_30d = datetime.now(UTC) - timedelta(days=30)
    runs_result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .where(AuditRunDB.run_at >= cutoff_30d)
        .order_by(desc(AuditRunDB.run_at))
    )
    all_runs = list(runs_result.scalars().all())

    # Partition runs by time period
    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    runs_24h = [r for r in all_runs if _ensure_utc(r.run_at) >= cutoff_24h]
    runs_7d = [r for r in all_runs if _ensure_utc(r.run_at) >= cutoff_7d]
    runs_30d = all_runs

    # Compute trends for each period
    trend_24h = _compute_trend_period(runs_24h)
    trend_7d = _compute_trend_period(runs_7d)
    trend_30d = _compute_trend_period(runs_30d)

    # Get last run summary
    last_run: dict[str, Any] | None = None
    if all_runs:
        latest = all_runs[0]
        last_run = {
            "id": str(latest.id),
            "status": latest.status.value,
            "run_at": latest.run_at.isoformat(),
            "triggered_by": latest.triggered_by,
            "guarantees_failed": latest.guarantees_failed,
        }

    # Generate alerts based on failure patterns
    alerts: list[str] = []

    # Alert: High failure rate in last 24h
    if trend_24h.failure_rate > 0.5 and trend_24h.total_runs >= 3:
        alerts.append(
            f"High failure rate in last 24h: {trend_24h.failure_rate:.0%} "
            f"({trend_24h.failed + trend_24h.partial}/{trend_24h.total_runs} runs failed)"
        )

    # Alert: Failure rate increasing
    if trend_7d.total_runs >= 5 and trend_30d.total_runs >= 10:
        if trend_7d.failure_rate > trend_30d.failure_rate * 1.5:
            alerts.append(
                f"Failure rate trending up: {trend_7d.failure_rate:.0%} (7d) vs "
                f"{trend_30d.failure_rate:.0%} (30d)"
            )

    # Alert: Specific guarantee consistently failing
    if trend_7d.most_failed_guarantees:
        top_failure = trend_7d.most_failed_guarantees[0]
        if top_failure["failure_count"] >= 5:
            alerts.append(
                f"Guarantee '{top_failure['guarantee_id']}' failed "
                f"{top_failure['failure_count']} times in last 7 days"
            )

    # Alert: Last run failed
    if all_runs and all_runs[0].status == AuditRunStatus.FAILED:
        alerts.append("Most recent audit run failed")

    return AuditTrendsResponse(
        asset_id=asset_id,
        asset_fqn=asset.fqn,
        last_run=last_run,
        last_24h=trend_24h,
        last_7d=trend_7d,
        last_30d=trend_30d,
        alerts=alerts,
    )
