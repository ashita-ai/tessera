"""Dependency discovery endpoints.

Exposes the preflight inference pipeline: trigger scans, list/confirm/reject
inferred dependencies, and view coverage reports.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead, RequireWrite
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError, NotFoundError
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db.database import get_session
from tessera.db.models import AssetDB, InferredDependencyDB, TeamDB
from tessera.models.enums import (
    APIKeyScope,
    DependencyType,
    InferredDependencyStatus,
)
from tessera.services.discovery import (
    compute_coverage_report,
    confirm_inference,
    reject_inference,
    run_preflight_inference,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Request body for triggering a discovery scan."""

    source: str = Field(
        default="preflight_audit",
        description="Signal source to scan",
    )
    lookback_days: int = Field(default=30, ge=1, le=365)
    min_calls: int = Field(default=5, ge=1)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ScanResponse(BaseModel):
    """Statistics returned after a scan completes."""

    source: str
    scan_duration_ms: int
    events_scanned: int
    pairs_evaluated: int
    inferred_new: int
    inferred_updated: int
    inferred_expired: int
    skipped_already_registered: int
    skipped_previously_rejected: int


class ConfirmRequest(BaseModel):
    """Request body for confirming an inferred dependency."""

    dependency_type: DependencyType | None = None
    pinned_version: str | None = None


class RejectRequest(BaseModel):
    """Request body for rejecting an inferred dependency."""

    reason: str = Field(..., min_length=1, max_length=2000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=ScanResponse)
@limit_write
async def trigger_scan(
    request: Request,
    body: ScanRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> ScanResponse:
    """Trigger a preflight inference scan.

    Mines audit events for dependency signals and creates/updates inferred
    dependencies. This is an admin-only operational action.
    """
    if body.source != "preflight_audit":
        raise BadRequestError(
            f"Unsupported source: {body.source}. Only 'preflight_audit' is supported.",
            code=ErrorCode.VALIDATION_ERROR,
        )

    stats = await run_preflight_inference(
        session=session,
        lookback_days=body.lookback_days,
        min_calls=body.min_calls,
        min_confidence=body.min_confidence,
    )

    return ScanResponse(
        source=stats.source,
        scan_duration_ms=stats.scan_duration_ms,
        events_scanned=stats.events_scanned,
        pairs_evaluated=stats.pairs_evaluated,
        inferred_new=stats.inferred_new,
        inferred_updated=stats.inferred_updated,
        inferred_expired=stats.inferred_expired,
        skipped_already_registered=stats.skipped_already_registered,
        skipped_previously_rejected=stats.skipped_previously_rejected,
    )


@router.get("/inferred")
@limit_read
async def list_inferred(
    request: Request,
    auth: Auth,
    _: None = RequireRead,
    asset_id: UUID | None = Query(None, description="Filter by asset"),
    team_id: UUID | None = Query(None, description="Filter by consumer team"),
    status: InferredDependencyStatus = Query(
        InferredDependencyStatus.PENDING,
        description="Filter by status",
    ),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    source: str | None = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List inferred dependencies with filtering.

    Non-admin keys only see inferences for their own team.
    """
    query = (
        select(InferredDependencyDB, AssetDB.fqn, TeamDB.name)
        .join(AssetDB, InferredDependencyDB.asset_id == AssetDB.id)
        .join(TeamDB, InferredDependencyDB.consumer_team_id == TeamDB.id)
    )

    filters = [InferredDependencyDB.status == status]

    # Team scoping: non-admin keys see only their own team's inferences
    if not auth.has_scope(APIKeyScope.ADMIN):
        filters.append(InferredDependencyDB.consumer_team_id == auth.team_id)

    if asset_id is not None:
        filters.append(InferredDependencyDB.asset_id == asset_id)
    if team_id is not None:
        filters.append(InferredDependencyDB.consumer_team_id == team_id)
    if min_confidence > 0.0:
        filters.append(InferredDependencyDB.confidence >= min_confidence)
    if source is not None:
        filters.append(InferredDependencyDB.source == source)

    query = query.where(and_(*filters))

    # Count total matching rows
    from sqlalchemy import func

    count_query = (
        select(func.count(InferredDependencyDB.id))
        .join(AssetDB, InferredDependencyDB.asset_id == AssetDB.id)
        .join(TeamDB, InferredDependencyDB.consumer_team_id == TeamDB.id)
        .where(and_(*filters))
    )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(InferredDependencyDB.confidence.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    rows = result.all()

    inferred_dependencies = [
        {
            "id": str(dep.id),
            "asset_id": str(dep.asset_id),
            "asset_fqn": asset_fqn,
            "consumer_team_id": str(dep.consumer_team_id),
            "consumer_team_name": team_name,
            "dependency_type": str(dep.dependency_type),
            "confidence": dep.confidence,
            "source": dep.source,
            "status": str(dep.status),
            "evidence": dep.evidence,
            "first_observed_at": (
                dep.first_observed_at.isoformat() if dep.first_observed_at else None
            ),
            "last_observed_at": (
                dep.last_observed_at.isoformat() if dep.last_observed_at else None
            ),
        }
        for dep, asset_fqn, team_name in rows
    ]

    return {
        "inferred_dependencies": inferred_dependencies,
        "total": total,
    }


@router.post("/inferred/{inference_id}/confirm")
@limit_write
async def confirm_inferred(
    request: Request,
    inference_id: UUID,
    body: ConfirmRequest,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Confirm an inferred dependency and promote it to a registration.

    Team-scoped: the confirming team must match the inferred consumer_team_id,
    or the key must have ADMIN scope.
    """
    # Load the inference to check team scoping
    inference_result = await session.execute(
        select(InferredDependencyDB).where(InferredDependencyDB.id == inference_id)
    )
    inference = inference_result.scalar_one_or_none()

    if not inference:
        raise NotFoundError(
            ErrorCode.DEPENDENCY_NOT_FOUND,
            "Inferred dependency not found",
        )

    # Team scoping
    if inference.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Can only confirm inferences for your own team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    try:
        return await confirm_inference(
            session=session,
            inference_id=inference_id,
            confirmed_by=auth.team_id,
            dependency_type=body.dependency_type,
            pinned_version=body.pinned_version,
        )
    except ValueError as e:
        raise BadRequestError(str(e), code=ErrorCode.VALIDATION_ERROR) from e


@router.post("/inferred/{inference_id}/reject")
@limit_write
async def reject_inferred(
    request: Request,
    inference_id: UUID,
    body: RejectRequest,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Reject an inferred dependency. Future scans will skip this pair.

    Team-scoped: the rejecting team must match the inferred consumer_team_id,
    or the key must have ADMIN scope.
    """
    # Load the inference to check team scoping
    inference_result = await session.execute(
        select(InferredDependencyDB).where(InferredDependencyDB.id == inference_id)
    )
    inference = inference_result.scalar_one_or_none()

    if not inference:
        raise NotFoundError(
            ErrorCode.DEPENDENCY_NOT_FOUND,
            "Inferred dependency not found",
        )

    # Team scoping
    if inference.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Can only reject inferences for your own team",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    try:
        return await reject_inference(
            session=session,
            inference_id=inference_id,
            rejected_by=auth.team_id,
            reason=body.reason,
        )
    except ValueError as e:
        raise BadRequestError(str(e), code=ErrorCode.VALIDATION_ERROR) from e


@router.get("/coverage")
@limit_read
async def coverage_report(
    request: Request,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Gap analysis report for dependency coverage.

    Shows how many assets have registrations, inferred-only consumers, or
    no known consumers at all. Includes the top 20 highest-risk gaps.
    """
    report = await compute_coverage_report(session)

    return {
        "total_assets": report.total_assets,
        "assets_with_registrations": report.assets_with_registrations,
        "assets_with_inferred_only": report.assets_with_inferred_only,
        "assets_with_no_known_consumers": report.assets_with_no_known_consumers,
        "coverage_registered": report.coverage_registered,
        "coverage_with_inferred": report.coverage_with_inferred,
        "highest_risk_gaps": report.highest_risk_gaps,
    }
