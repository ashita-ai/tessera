"""Preflight endpoint for consumption-time contract metadata.

Provides a lightweight, read-only endpoint that returns contract metadata
for a given asset FQN. Designed for machine consumption — AI agents check
this before querying underlying data to understand schema guarantees,
freshness SLAs, and compatibility constraints.

Every call is logged as a ``preflight.checked`` audit event so contract
authors can measure utilization and detect unmonitored consumption.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_read
from tessera.db import AuditRunDB, ContractDB, get_session
from tessera.db.models import AssetDB
from tessera.models.enums import AuditRunStatus, ContractStatus
from tessera.services.audit import log_preflight_checked

router = APIRouter(tags=["preflight"])


class FreshnessSLA(BaseModel):
    """Freshness SLA details from contract guarantees."""

    max_staleness_minutes: int | None = None
    last_measured_at: datetime | None = None


class PreflightResponse(BaseModel):
    """Contract metadata returned at consumption time.

    Designed for machine-readable consumption by AI agents and pipelines.
    """

    asset_fqn: str
    asset_id: UUID
    contract_version: str
    compatibility_mode: str
    schema_format: str
    fresh: bool | None = Field(
        None,
        description="Whether data meets the freshness SLA. None if no SLA defined.",
    )
    freshness_sla: FreshnessSLA | None = None
    guarantees: dict[str, Any] | None = Field(
        None, description="Contract guarantees (not_null, unique, accepted_values, etc.)."
    )
    last_audit_status: str | None = Field(
        None,
        description="Status of the most recent audit run (passed, failed, partial).",
    )
    last_audit_at: datetime | None = None
    caveats: list[str] = Field(
        default_factory=list,
        description="Warnings about data validity, methodology changes, etc.",
    )


def _evaluate_freshness(
    guarantees: dict[str, Any] | None,
    last_audit_at: datetime | None,
) -> tuple[bool | None, FreshnessSLA | None]:
    """Evaluate freshness against SLA from guarantees.

    Returns (fresh_bool, freshness_sla). Both are None when no SLA is defined.
    """
    if not guarantees:
        return None, None

    freshness = guarantees.get("freshness")
    if not freshness:
        return None, None

    max_staleness = freshness.get("max_staleness_minutes")
    if max_staleness is None:
        return None, None

    sla = FreshnessSLA(
        max_staleness_minutes=max_staleness,
        last_measured_at=last_audit_at,
    )

    if last_audit_at is None:
        # No audit data — can't determine freshness
        return None, sla

    threshold = datetime.now(UTC) - timedelta(minutes=max_staleness)
    # Normalize timezone: SQLite returns naive datetimes, PostgreSQL returns aware.
    if last_audit_at.tzinfo is None:
        last_audit_at = last_audit_at.replace(tzinfo=UTC)
    return last_audit_at >= threshold, sla


@router.get(
    "/{fqn}/preflight",
    response_model=PreflightResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Forbidden — insufficient permissions"},
        404: {"description": "Asset not found"},
    },
    summary="Preflight contract metadata check",
    description=(
        "Returns contract metadata for a given asset FQN at consumption time. "
        "Designed for AI agents and pipelines to check schema guarantees, "
        "freshness SLAs, and compatibility before querying data. "
        "Each call is logged as a consumption event for utilization tracking."
    ),
)
@limit_read
async def preflight_check(
    request: Request,
    fqn: str,
    auth: Auth,
    consumer_type: str | None = Query(
        None,
        description="Type of consumer making the check (e.g., 'agent', 'human', 'pipeline').",
    ),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PreflightResponse:
    """Return contract metadata for consumption-time checks and log the event."""
    # Look up asset by FQN (non-deleted only)
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.fqn == fqn).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(
            code=ErrorCode.ASSET_NOT_FOUND,
            message=f"No asset found with FQN '{fqn}'",
        )

    # Get active contract, falling back to deprecated if no active version exists.
    # This lets consumers see metadata (with a caveat) instead of a bare 404.
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset.id)
        .where(ContractDB.status.in_([ContractStatus.ACTIVE, ContractStatus.DEPRECATED]))
        .order_by(
            # ACTIVE sorts before DEPRECATED so we always prefer it
            (ContractDB.status == ContractStatus.DEPRECATED).asc(),
            ContractDB.published_at.desc(),
        )
        .limit(1)
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            code=ErrorCode.NOT_FOUND,
            message=f"No active contract found for asset '{fqn}'",
        )

    # Get latest audit run for freshness evaluation
    audit_run_result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset.id)
        .order_by(AuditRunDB.run_at.desc())
        .limit(1)
    )
    latest_audit = audit_run_result.scalar_one_or_none()

    last_audit_status = latest_audit.status.value if latest_audit else None
    last_audit_at = latest_audit.run_at if latest_audit else None

    # Evaluate freshness against SLA
    fresh, freshness_sla = _evaluate_freshness(contract.guarantees, last_audit_at)

    # Build caveats
    caveats: list[str] = []
    if contract.status == ContractStatus.DEPRECATED:
        caveats.append("Contract is deprecated; a newer version may be available.")
    if latest_audit and latest_audit.status == AuditRunStatus.FAILED:
        caveats.append("Most recent audit run failed — guarantee violations detected.")
    if fresh is False:
        caveats.append("Data does not meet the freshness SLA.")

    has_guarantees = contract.guarantees is not None and len(contract.guarantees) > 0

    # Determine actor_id from auth context
    actor_id: UUID | None = None
    if hasattr(auth, "api_key") and auth.api_key:
        actor_id = auth.api_key.team_id

    # Log the consumption event
    await log_preflight_checked(
        session=session,
        asset_id=asset.id,
        actor_id=actor_id,
        asset_fqn=fqn,
        contract_version=contract.version,
        freshness_status="fresh" if fresh else ("stale" if fresh is False else "unknown"),
        guarantees_checked=has_guarantees,
        consumer_type=consumer_type,
    )

    return PreflightResponse(
        asset_fqn=fqn,
        asset_id=asset.id,
        contract_version=contract.version,
        compatibility_mode=contract.compatibility_mode.value,
        schema_format=contract.schema_format.value,
        fresh=fresh,
        freshness_sla=freshness_sla,
        guarantees=contract.guarantees,
        last_audit_status=last_audit_status,
        last_audit_at=last_audit_at,
        caveats=caveats,
    )
