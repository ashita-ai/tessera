"""Passive dependency discovery via audit signal mining.

Scans preflight.checked audit events to infer which teams consume which
assets, computes confidence scores, and manages the lifecycle of inferred
dependencies (pending -> confirmed/rejected/expired).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AuditEventDB,
    ContractDB,
    InferredDependencyDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    ContractStatus,
    DependencyType,
    InferredDependencyStatus,
    RegistrationStatus,
)
from tessera.services.audit import AuditAction, log_event

logger = logging.getLogger(__name__)

# Confidence scoring weights (must sum to 1.0)
_W_FREQUENCY = 0.35
_W_REGULARITY = 0.30
_W_RECENCY = 0.25
_W_AGENT = 0.10


def compute_preflight_confidence(
    call_count: int,
    distinct_days: int,
    days_since_last_call: int,
    is_agent: bool,
    lookback_days: int = 30,
) -> float:
    """Score a preflight-inferred dependency.

    Args:
        call_count: Total preflight calls in the lookback window.
        distinct_days: Number of distinct days with at least one call.
        days_since_last_call: Days since the most recent call.
        is_agent: Whether the dominant actor type is an agent.
        lookback_days: Size of the lookback window in days.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if lookback_days <= 0 or call_count <= 0:
        return 0.0

    frequency = min(call_count / lookback_days, 1.0)
    regularity = min(distinct_days / lookback_days, 1.0)
    recency = max(1.0 - (days_since_last_call / lookback_days), 0.0)
    agent_bonus = 1.0 if is_agent else 0.0

    score = (
        _W_FREQUENCY * frequency
        + _W_REGULARITY * regularity
        + _W_RECENCY * recency
        + _W_AGENT * agent_bonus
    )
    return round(min(score, 1.0), 4)


@dataclass
class ScanStats:
    """Statistics from a single inference scan run."""

    source: str
    scan_duration_ms: int = 0
    events_scanned: int = 0
    pairs_evaluated: int = 0
    inferred_new: int = 0
    inferred_updated: int = 0
    inferred_expired: int = 0
    skipped_already_registered: int = 0
    skipped_previously_rejected: int = 0


@dataclass
class _AggregatedPair:
    """Aggregated audit signals for a single (asset, team) pair."""

    asset_id: UUID
    team_id: UUID
    call_count: int
    distinct_days: int
    last_call: datetime
    is_agent: bool
    evidence: dict[str, Any] = field(default_factory=dict)


async def run_preflight_inference(
    session: AsyncSession,
    lookback_days: int = 30,
    min_calls: int = 5,
    min_confidence: float = 0.5,
) -> ScanStats:
    """Scan preflight audit events and create/update inferred dependencies.

    Steps:
        1. Query preflight.checked events within the lookback window.
        2. Aggregate by (asset_id, team_id).
        3. Skip pairs with existing registrations or rejected inferences.
        4. Compute confidence and upsert above-threshold pairs.
        5. Expire stale inferences not refreshed in 2x the lookback window.

    Args:
        session: Database session.
        lookback_days: Days of audit history to scan.
        min_calls: Minimum call count to evaluate a pair.
        min_confidence: Minimum confidence score to store an inference.

    Returns:
        ScanStats with counts of what happened.
    """
    start_time = time.monotonic()
    stats = ScanStats(source="preflight_audit")
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=lookback_days)

    # Step 1: Load all preflight.checked events in the lookback window
    events_result = await session.execute(
        select(AuditEventDB).where(
            and_(
                AuditEventDB.action == str(AuditAction.PREFLIGHT_CHECKED),
                AuditEventDB.occurred_at >= cutoff,
                AuditEventDB.actor_id.is_not(None),
            )
        )
    )
    events = events_result.scalars().all()
    stats.events_scanned = len(events)

    # Step 5 (run early): Expire stale inferences regardless of new events
    expiry_cutoff = now - timedelta(days=lookback_days * 2)
    expire_result = await session.execute(
        update(InferredDependencyDB)
        .where(
            and_(
                InferredDependencyDB.source == "preflight_audit",
                InferredDependencyDB.status == InferredDependencyStatus.PENDING,
                InferredDependencyDB.last_observed_at < expiry_cutoff,
            )
        )
        .values(status=InferredDependencyStatus.EXPIRED)
    )
    stats.inferred_expired = expire_result.rowcount  # type: ignore[attr-defined]

    if not events:
        await session.flush()
        stats.scan_duration_ms = int((time.monotonic() - start_time) * 1000)
        return stats

    # Step 2: Aggregate by (entity_id=asset_id, actor_id=team_id)
    # actor_id is guaranteed non-null by the WHERE clause above
    pairs: dict[tuple[UUID, UUID], _AggregatedPair] = {}
    for event in events:
        assert event.actor_id is not None  # enforced by query filter
        key = (event.entity_id, event.actor_id)
        if key not in pairs:
            pairs[key] = _AggregatedPair(
                asset_id=event.entity_id,
                team_id=event.actor_id,
                call_count=0,
                distinct_days=0,
                last_call=event.occurred_at,
                is_agent=False,
            )
        pair = pairs[key]
        pair.call_count += 1
        if event.occurred_at > pair.last_call:
            pair.last_call = event.occurred_at

    # Compute distinct days and agent status per pair
    day_sets: dict[tuple[UUID, UUID], set[str]] = {}
    agent_counts: dict[tuple[UUID, UUID], int] = {}
    for event in events:
        assert event.actor_id is not None
        key = (event.entity_id, event.actor_id)
        day_sets.setdefault(key, set()).add(event.occurred_at.strftime("%Y-%m-%d"))
        if event.actor_type == "agent":
            agent_counts[key] = agent_counts.get(key, 0) + 1

    for key, pair in pairs.items():
        pair.distinct_days = len(day_sets.get(key, set()))
        total = pair.call_count
        pair.is_agent = agent_counts.get(key, 0) > total / 2

    stats.pairs_evaluated = len(pairs)

    # Step 3: Load existing registrations and rejected inferences in bulk
    all_asset_ids = {p.asset_id for p in pairs.values()}
    all_team_ids = {p.team_id for p in pairs.values()}

    # Find teams that already have active registrations for these assets
    # Registration is per-contract, so we need to join through contracts
    registered_result = await session.execute(
        select(ContractDB.asset_id, RegistrationDB.consumer_team_id)
        .join(RegistrationDB, RegistrationDB.contract_id == ContractDB.id)
        .where(
            and_(
                ContractDB.asset_id.in_(all_asset_ids),
                RegistrationDB.consumer_team_id.in_(all_team_ids),
                RegistrationDB.deleted_at.is_(None),
                RegistrationDB.status == RegistrationStatus.ACTIVE,
            )
        )
        .distinct()
    )
    registered_pairs: set[tuple[UUID, UUID]] = {(row[0], row[1]) for row in registered_result.all()}

    # Find rejected inferences for these pairs
    rejected_result = await session.execute(
        select(
            InferredDependencyDB.asset_id,
            InferredDependencyDB.consumer_team_id,
        ).where(
            and_(
                InferredDependencyDB.asset_id.in_(all_asset_ids),
                InferredDependencyDB.consumer_team_id.in_(all_team_ids),
                InferredDependencyDB.source == "preflight_audit",
                InferredDependencyDB.status == InferredDependencyStatus.REJECTED,
            )
        )
    )
    rejected_pairs: set[tuple[UUID, UUID]] = {(row[0], row[1]) for row in rejected_result.all()}

    # Step 4: Score and upsert
    for key, pair in pairs.items():
        asset_team = (pair.asset_id, pair.team_id)

        if asset_team in registered_pairs:
            stats.skipped_already_registered += 1
            continue

        if asset_team in rejected_pairs:
            stats.skipped_previously_rejected += 1
            continue

        if pair.call_count < min_calls:
            continue

        days_since_last = max((now - pair.last_call).days, 0)
        confidence = compute_preflight_confidence(
            call_count=pair.call_count,
            distinct_days=pair.distinct_days,
            days_since_last_call=days_since_last,
            is_agent=pair.is_agent,
            lookback_days=lookback_days,
        )

        if confidence < min_confidence:
            continue

        evidence = {
            "preflight_calls_30d": pair.call_count,
            "distinct_days": pair.distinct_days,
            "days_since_last_call": days_since_last,
            "actor_type": "agent" if pair.is_agent else "human",
        }

        # Upsert: update if exists, insert if new
        existing_result = await session.execute(
            select(InferredDependencyDB).where(
                and_(
                    InferredDependencyDB.asset_id == pair.asset_id,
                    InferredDependencyDB.consumer_team_id == pair.team_id,
                    InferredDependencyDB.source == "preflight_audit",
                )
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            if existing.status in (
                InferredDependencyStatus.CONFIRMED,
                InferredDependencyStatus.REJECTED,
            ):
                # Don't overwrite terminal states
                continue
            existing.confidence = confidence
            existing.evidence = evidence
            existing.last_observed_at = now
            existing.status = InferredDependencyStatus.PENDING
            stats.inferred_updated += 1
        else:
            new_dep = InferredDependencyDB(
                asset_id=pair.asset_id,
                consumer_team_id=pair.team_id,
                dependency_type=DependencyType.CONSUMES,
                confidence=confidence,
                source="preflight_audit",
                evidence=evidence,
                status=InferredDependencyStatus.PENDING,
                first_observed_at=now,
                last_observed_at=now,
            )
            session.add(new_dep)
            stats.inferred_new += 1

    await session.flush()

    stats.scan_duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "Preflight inference scan completed: %d events, %d pairs, %d new, %d updated, %d expired",
        stats.events_scanned,
        stats.pairs_evaluated,
        stats.inferred_new,
        stats.inferred_updated,
        stats.inferred_expired,
    )
    return stats


async def confirm_inference(
    session: AsyncSession,
    inference_id: UUID,
    confirmed_by: UUID,
    dependency_type: DependencyType | None = None,
    pinned_version: str | None = None,
) -> dict[str, Any]:
    """Confirm an inferred dependency and promote it to a registration.

    Args:
        session: Database session.
        inference_id: ID of the inferred dependency to confirm.
        confirmed_by: Team ID of the confirming team.
        dependency_type: Override the inferred dependency type.
        pinned_version: Optional pinned version for the registration.

    Returns:
        Dict with confirmation details and promoted registration info.

    Raises:
        ValueError: If the inference is not found or not in PENDING status.
    """
    result = await session.execute(
        select(InferredDependencyDB).where(InferredDependencyDB.id == inference_id)
    )
    inference = result.scalar_one_or_none()

    if not inference:
        raise ValueError("Inferred dependency not found")
    if inference.status != InferredDependencyStatus.PENDING:
        raise ValueError(
            f"Cannot confirm inference with status '{inference.status}'; "
            "only PENDING inferences can be confirmed"
        )

    now = datetime.now(UTC)

    if dependency_type:
        inference.dependency_type = dependency_type

    # Find the active contract for this asset
    contract_result = await session.execute(
        select(ContractDB)
        .where(
            and_(
                ContractDB.asset_id == inference.asset_id,
                ContractDB.status == ContractStatus.ACTIVE,
            )
        )
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    contract = contract_result.scalar_one_or_none()

    promoted_registration: dict[str, Any] | None = None

    if contract:
        # Check for existing registration (race condition guard)
        existing_reg_result = await session.execute(
            select(RegistrationDB).where(
                and_(
                    RegistrationDB.contract_id == contract.id,
                    RegistrationDB.consumer_team_id == inference.consumer_team_id,
                    RegistrationDB.deleted_at.is_(None),
                )
            )
        )
        existing_reg = existing_reg_result.scalar_one_or_none()

        if existing_reg:
            registration = existing_reg
        else:
            registration = RegistrationDB(
                contract_id=contract.id,
                consumer_team_id=inference.consumer_team_id,
                pinned_version=pinned_version,
                status=RegistrationStatus.ACTIVE,
            )
            session.add(registration)
            await session.flush()

        inference.promoted_registration_id = registration.id
        promoted_registration = {
            "registration_id": str(registration.id),
            "contract_id": str(contract.id),
            "consumer_team_id": str(inference.consumer_team_id),
            "status": str(registration.status),
        }

    # Update inference status
    inference.status = InferredDependencyStatus.CONFIRMED
    inference.confirmed_at = now
    inference.confirmed_by = confirmed_by

    # Audit log
    await log_event(
        session=session,
        entity_type="inferred_dependency",
        entity_id=inference.id,
        action=AuditAction.DISCOVERY_CONFIRMED,
        actor_id=confirmed_by,
        payload={
            "asset_id": str(inference.asset_id),
            "consumer_team_id": str(inference.consumer_team_id),
            "confidence": inference.confidence,
            "promoted_registration_id": (
                str(inference.promoted_registration_id)
                if inference.promoted_registration_id
                else None
            ),
        },
    )

    await session.flush()

    return {
        "inferred_dependency_id": str(inference.id),
        "status": "confirmed",
        "promoted_registration": promoted_registration,
    }


async def reject_inference(
    session: AsyncSession,
    inference_id: UUID,
    rejected_by: UUID,
    reason: str,
) -> dict[str, Any]:
    """Reject an inferred dependency. Future scans will skip this pair.

    Args:
        session: Database session.
        inference_id: ID of the inferred dependency to reject.
        rejected_by: Team ID of the rejecting team.
        reason: Human-readable reason for rejection.

    Returns:
        Dict with rejection details.

    Raises:
        ValueError: If the inference is not found or not in PENDING status.
    """
    result = await session.execute(
        select(InferredDependencyDB).where(InferredDependencyDB.id == inference_id)
    )
    inference = result.scalar_one_or_none()

    if not inference:
        raise ValueError("Inferred dependency not found")
    if inference.status != InferredDependencyStatus.PENDING:
        raise ValueError(
            f"Cannot reject inference with status '{inference.status}'; "
            "only PENDING inferences can be rejected"
        )

    inference.status = InferredDependencyStatus.REJECTED

    # Audit log
    await log_event(
        session=session,
        entity_type="inferred_dependency",
        entity_id=inference.id,
        action=AuditAction.DISCOVERY_REJECTED,
        actor_id=rejected_by,
        payload={
            "asset_id": str(inference.asset_id),
            "consumer_team_id": str(inference.consumer_team_id),
            "reason": reason,
        },
    )

    await session.flush()

    return {
        "inferred_dependency_id": str(inference.id),
        "status": "rejected",
    }


@dataclass
class CoverageReport:
    """Gap analysis report for dependency coverage."""

    total_assets: int = 0
    assets_with_registrations: int = 0
    assets_with_inferred_only: int = 0
    assets_with_no_known_consumers: int = 0
    coverage_registered: float = 0.0
    coverage_with_inferred: float = 0.0
    highest_risk_gaps: list[dict[str, Any]] = field(default_factory=list)


async def compute_coverage_report(
    session: AsyncSession,
    *,
    team_id: UUID | None = None,
) -> CoverageReport:
    """Compute a gap analysis report for dependency coverage.

    Returns counts of assets by consumer coverage status and identifies
    the highest-risk gaps (assets with lots of preflight activity but
    zero registrations).
    """
    report = CoverageReport()

    # Base filter: non-deleted assets, optionally scoped to a single team
    asset_filters: list[ColumnElement[bool]] = [AssetDB.deleted_at.is_(None)]
    if team_id is not None:
        asset_filters.append(AssetDB.owner_team_id == team_id)

    # Total non-deleted assets (within team scope when filtered)
    total_result = await session.execute(select(func.count(AssetDB.id)).where(and_(*asset_filters)))
    report.total_assets = total_result.scalar() or 0

    if report.total_assets == 0:
        return report

    # Assets with at least one active registration (within team scope)
    reg_filters: list[ColumnElement[bool]] = [
        AssetDB.deleted_at.is_(None),
        RegistrationDB.deleted_at.is_(None),
        RegistrationDB.status == RegistrationStatus.ACTIVE,
    ]
    if team_id is not None:
        reg_filters.append(AssetDB.owner_team_id == team_id)

    registered_result = await session.execute(
        select(func.count(func.distinct(ContractDB.asset_id)))
        .join(RegistrationDB, RegistrationDB.contract_id == ContractDB.id)
        .join(AssetDB, ContractDB.asset_id == AssetDB.id)
        .where(and_(*reg_filters))
    )
    report.assets_with_registrations = registered_result.scalar() or 0

    # Non-deleted assets with pending inferred dependencies (but no registrations)
    registered_asset_ids = (
        select(func.distinct(ContractDB.asset_id))
        .join(RegistrationDB, RegistrationDB.contract_id == ContractDB.id)
        .join(AssetDB, ContractDB.asset_id == AssetDB.id)
        .where(and_(*reg_filters))
    )
    inferred_filters: list[ColumnElement[bool]] = [
        AssetDB.deleted_at.is_(None),
        InferredDependencyDB.status == InferredDependencyStatus.PENDING,
        InferredDependencyDB.asset_id.not_in(registered_asset_ids),
    ]
    if team_id is not None:
        inferred_filters.append(AssetDB.owner_team_id == team_id)

    inferred_only_result = await session.execute(
        select(func.count(func.distinct(InferredDependencyDB.asset_id)))
        .join(AssetDB, InferredDependencyDB.asset_id == AssetDB.id)
        .where(and_(*inferred_filters))
    )
    report.assets_with_inferred_only = inferred_only_result.scalar() or 0

    report.assets_with_no_known_consumers = (
        report.total_assets - report.assets_with_registrations - report.assets_with_inferred_only
    )

    report.coverage_registered = round(report.assets_with_registrations / report.total_assets, 4)
    report.coverage_with_inferred = round(
        (report.assets_with_registrations + report.assets_with_inferred_only) / report.total_assets,
        4,
    )

    # Highest-risk gaps: assets with most preflight activity and zero registrations
    # Use a 30-day lookback for activity counting
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    gap_filters: list[ColumnElement[bool]] = [
        AuditEventDB.action == str(AuditAction.PREFLIGHT_CHECKED),
        AuditEventDB.occurred_at >= thirty_days_ago,
        AuditEventDB.actor_id.is_not(None),
    ]

    gap_query = select(
        AuditEventDB.entity_id.label("asset_id"),
        func.count(AuditEventDB.id).label("preflight_calls_30d"),
        func.count(func.distinct(AuditEventDB.actor_id)).label("distinct_consumer_teams"),
    ).where(and_(*gap_filters))

    # When team-scoped, restrict to assets owned by this team
    if team_id is not None:
        team_asset_ids = select(AssetDB.id).where(
            and_(AssetDB.deleted_at.is_(None), AssetDB.owner_team_id == team_id)
        )
        gap_query = gap_query.where(AuditEventDB.entity_id.in_(team_asset_ids))

    gap_query = (
        gap_query.group_by(AuditEventDB.entity_id)
        .order_by(func.count(AuditEventDB.id).desc())
        .limit(20)
    )
    gap_result = await session.execute(gap_query)
    gap_rows = gap_result.all()

    if gap_rows:
        gap_asset_ids = [row[0] for row in gap_rows]

        # Load asset FQNs
        asset_result = await session.execute(
            select(AssetDB.id, AssetDB.fqn).where(AssetDB.id.in_(gap_asset_ids))
        )
        fqn_map = {row[0]: row[1] for row in asset_result.all()}

        # Load registration counts per asset
        reg_count_result = await session.execute(
            select(
                ContractDB.asset_id,
                func.count(func.distinct(RegistrationDB.id)),
            )
            .join(RegistrationDB, RegistrationDB.contract_id == ContractDB.id)
            .where(
                and_(
                    ContractDB.asset_id.in_(gap_asset_ids),
                    RegistrationDB.deleted_at.is_(None),
                    RegistrationDB.status == RegistrationStatus.ACTIVE,
                )
            )
            .group_by(ContractDB.asset_id)
        )
        reg_count_map = {row[0]: row[1] for row in reg_count_result.all()}

        # Load pending inference counts per asset
        inferred_count_result = await session.execute(
            select(
                InferredDependencyDB.asset_id,
                func.count(InferredDependencyDB.id),
            )
            .where(
                and_(
                    InferredDependencyDB.asset_id.in_(gap_asset_ids),
                    InferredDependencyDB.status == InferredDependencyStatus.PENDING,
                )
            )
            .group_by(InferredDependencyDB.asset_id)
        )
        inferred_count_map = {row[0]: row[1] for row in inferred_count_result.all()}

        for row in gap_rows:
            asset_id = row[0]
            report.highest_risk_gaps.append(
                {
                    "asset_id": str(asset_id),
                    "asset_fqn": fqn_map.get(asset_id, "unknown"),
                    "preflight_calls_30d": row[1],
                    "distinct_consumer_teams": row[2],
                    "registrations": reg_count_map.get(asset_id, 0),
                    "inferred_pending": inferred_count_map.get(asset_id, 0),
                }
            )

    return report


async def get_pending_inferences_for_asset(
    session: AsyncSession,
    asset_id: UUID,
) -> list[dict[str, Any]]:
    """Get pending inferred consumers for an asset (for impact preview).

    Returns a list of unconfirmed consumer summaries suitable for inclusion
    in an impact preview response.
    """
    result = await session.execute(
        select(InferredDependencyDB, TeamDB)
        .join(TeamDB, InferredDependencyDB.consumer_team_id == TeamDB.id)
        .where(
            and_(
                InferredDependencyDB.asset_id == asset_id,
                InferredDependencyDB.status == InferredDependencyStatus.PENDING,
                TeamDB.deleted_at.is_(None),
            )
        )
    )
    rows = result.all()

    return [
        {
            "consumer_team_id": str(dep.consumer_team_id),
            "consumer_team_name": team.name,
            "confidence": dep.confidence,
            "source": dep.source,
            "status": str(dep.status),
        }
        for dep, team in rows
    ]
