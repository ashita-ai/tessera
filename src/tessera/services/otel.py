"""OTEL-based dependency discovery service.

Queries OTEL trace backends (Jaeger, Tempo, Datadog) to discover
service-to-service dependency edges and reconciles them against
manually declared dependencies.
"""

import asyncio
import ipaddress
import logging
import math
import socket
import time
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    OtelSyncConfigDB,
    ServiceDB,
)
from tessera.models.enums import DependencySource, DependencyType, OtelBackendType
from tessera.models.otel import (
    OtelServiceEdge,
    ReconciliationItem,
    ReconciliationReport,
    SyncResult,
    UnresolvedService,
)

logger = logging.getLogger(__name__)


async def validate_otel_endpoint_host(url: str) -> tuple[bool, str]:
    """Validate that an OTEL endpoint URL does not target internal/private hosts.

    Performs async DNS resolution and rejects non-global IPs to prevent SSRF
    attacks targeting cloud metadata services, localhost, or private networks.

    Args:
        url: The endpoint URL to validate.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    try:
        parsed = urlparse(url)
        if not parsed.hostname:
            return False, "Endpoint URL must have a hostname"

        loop = asyncio.get_running_loop()
        addrinfo = await asyncio.wait_for(
            loop.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                family=socket.AF_UNSPEC,
            ),
            timeout=5.0,
        )

        for family, _, _, _, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if not ip_obj.is_global:
                    logger.warning(
                        "OTEL endpoint URL %s resolves to non-global IP %s",
                        url,
                        ip_obj,
                    )
                    return False, f"Endpoint URL resolves to blocked IP range ({ip_obj})"
            except ValueError:
                continue

        return True, ""
    except TimeoutError:
        return False, "DNS resolution timed out for endpoint URL"
    except socket.gaierror:
        logger.warning("Could not resolve OTEL endpoint hostname: %s", parsed.hostname)
        return False, "Could not resolve endpoint hostname"
    except Exception as exc:
        return False, f"Invalid endpoint URL: {exc}"


def compute_confidence(call_count: int, syncs_seen: int, total_syncs: int) -> float:
    """Compute confidence score for an OTEL-discovered dependency.

    Confidence is a weighted combination of:
    - Call count (60%): logarithmic scale, 10k calls = 1.0
    - Consistency (40%): fraction of syncs where this edge was observed

    Args:
        call_count: Number of calls observed in the lookback window.
        syncs_seen: Number of sync cycles where this edge was observed.
        total_syncs: Total number of sync cycles run.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    count_score = min(math.log10(max(call_count, 1)) / 4.0, 1.0)
    consistency_score = syncs_seen / max(total_syncs, 1)
    return round(0.6 * count_score + 0.4 * consistency_score, 2)


async def fetch_jaeger_dependencies(
    config: OtelSyncConfigDB,
    http_client: httpx.AsyncClient | None = None,
) -> list[OtelServiceEdge]:
    """Fetch dependency edges from a Jaeger backend.

    Queries Jaeger's ``/api/dependencies`` endpoint which returns aggregated
    service-to-service edges derived from trace data.

    Args:
        config: The OTEL sync config with Jaeger endpoint details.
        http_client: Optional pre-configured httpx client (for testing).

    Returns:
        List of raw service edges with call counts.

    Raises:
        httpx.HTTPStatusError: If the Jaeger API returns an error status.
        httpx.ConnectError: If the Jaeger endpoint is unreachable.
    """
    end_ts = int(time.time() * 1000)
    lookback_ms = config.lookback_seconds * 1000

    headers: dict[str, str] = {}
    if config.auth_header:
        headers["Authorization"] = config.auth_header

    url = f"{config.endpoint_url.rstrip('/')}/api/dependencies"
    params = {"endTs": str(end_ts), "lookback": str(lookback_ms)}

    if http_client is None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
    else:
        response = await http_client.get(url, params=params, headers=headers)

    response.raise_for_status()
    data = response.json()

    # Jaeger returns {"data": [...]} or just [...] depending on version
    edges_raw: list[dict[str, object]]
    if isinstance(data, dict) and "data" in data:
        edges_raw = data["data"]
    elif isinstance(data, list):
        edges_raw = data
    else:
        logger.warning("Unexpected Jaeger response format: %s", type(data))
        return []

    results: list[OtelServiceEdge] = []
    for edge in edges_raw:
        call_count_val = edge.get("callCount", 0)
        cc = int(float(str(call_count_val))) if call_count_val is not None else 0
        results.append(
            OtelServiceEdge(
                parent=str(edge["parent"]),
                child=str(edge["child"]),
                call_count=cc,
            )
        )
    return results


async def fetch_dependencies(
    config: OtelSyncConfigDB,
    http_client: httpx.AsyncClient | None = None,
) -> list[OtelServiceEdge]:
    """Fetch dependency edges from the configured OTEL backend.

    Dispatches to the appropriate backend client based on ``config.backend_type``.

    Args:
        config: The OTEL sync config.
        http_client: Optional pre-configured httpx client (for testing).

    Returns:
        List of service edges.

    Raises:
        ValueError: If the backend type is not yet supported.
    """
    if config.backend_type == OtelBackendType.JAEGER:
        return await fetch_jaeger_dependencies(config, http_client)
    raise ValueError(f"Backend type '{config.backend_type}' is not yet supported")


async def resolve_service_name(
    session: AsyncSession,
    otel_name: str,
) -> ServiceDB | None:
    """Resolve an OTEL service name to a Tessera service.

    Looks up ``services.otel_service_name`` to find the matching Tessera service.

    Args:
        session: Database session.
        otel_name: The service name from OTEL traces.

    Returns:
        The matched ServiceDB or None if unresolved.
    """
    result = await session.execute(
        select(ServiceDB).where(
            and_(
                ServiceDB.otel_service_name == otel_name,
                ServiceDB.deleted_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_primary_asset(session: AsyncSession, service_id: UUID) -> AssetDB | None:
    """Get the first non-deleted asset for a service (used as dependency anchor)."""
    result = await session.execute(
        select(AssetDB)
        .where(
            and_(
                AssetDB.service_id == service_id,
                AssetDB.deleted_at.is_(None),
            )
        )
        .order_by(AssetDB.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert_otel_dependency(
    session: AsyncSession,
    dependent_asset_id: UUID,
    dependency_asset_id: UUID,
    call_count: int,
    confidence: float,
    now: datetime,
    config_id: UUID,
) -> tuple[AssetDependencyDB, bool]:
    """Create or update an OTEL-discovered dependency edge.

    Looks up existing OTEL-sourced dependencies only. MANUAL dependencies are
    separate rows (enabled by the unique constraint including ``source``) so
    the reconciliation report can identify edges confirmed by both sources.

    Args:
        session: Database session.
        dependent_asset_id: The downstream consumer asset.
        dependency_asset_id: The upstream provider asset.
        call_count: Observed call count.
        confidence: Computed confidence score.
        now: Current timestamp.
        config_id: The OTEL sync config that discovered this edge.

    Returns:
        Tuple of (dependency, was_created).
    """
    result = await session.execute(
        select(AssetDependencyDB).where(
            and_(
                AssetDependencyDB.dependent_asset_id == dependent_asset_id,
                AssetDependencyDB.dependency_asset_id == dependency_asset_id,
                AssetDependencyDB.dependency_type == DependencyType.CONSUMES,
                AssetDependencyDB.source == DependencySource.OTEL,
                AssetDependencyDB.deleted_at.is_(None),
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.last_observed_at = now
        existing.call_count = call_count
        existing.confidence = confidence
        existing.syncs_seen = existing.syncs_seen + 1
        existing.otel_config_id = config_id
        await session.flush()
        return existing, False

    dep = AssetDependencyDB(
        dependent_asset_id=dependent_asset_id,
        dependency_asset_id=dependency_asset_id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=confidence,
        last_observed_at=now,
        call_count=call_count,
        syncs_seen=1,
        otel_config_id=config_id,
    )
    session.add(dep)
    await session.flush()
    return dep, True


async def mark_stale_dependencies(
    session: AsyncSession,
    config: OtelSyncConfigDB,
    now: datetime,
) -> int:
    """Mark OTEL dependencies as stale when not observed recently.

    Dependencies with source='otel' where last_observed_at is older than
    N * lookback_seconds are given a low confidence score. They are NOT
    deleted — stale deps remain visible in the reconciliation endpoint.

    Args:
        session: Database session.
        config: The OTEL sync config (provides lookback_seconds).
        now: Current timestamp.

    Returns:
        Number of dependencies marked stale.
    """
    stale_threshold_seconds = config.lookback_seconds * settings.otel_stale_multiplier
    cutoff = datetime.fromtimestamp(now.timestamp() - stale_threshold_seconds, tz=UTC)

    result = await session.execute(
        select(AssetDependencyDB).where(
            and_(
                AssetDependencyDB.source == DependencySource.OTEL,
                AssetDependencyDB.otel_config_id == config.id,
                AssetDependencyDB.deleted_at.is_(None),
                AssetDependencyDB.last_observed_at.isnot(None),
                AssetDependencyDB.last_observed_at < cutoff,
                AssetDependencyDB.confidence > 0.05,  # Don't re-demote already-stale
            )
        )
    )
    stale_deps = list(result.scalars().all())
    for dep in stale_deps:
        dep.confidence = 0.01
    if stale_deps:
        await session.flush()
    return len(stale_deps)


async def run_sync(
    session: AsyncSession,
    config: OtelSyncConfigDB,
    http_client: httpx.AsyncClient | None = None,
) -> SyncResult:
    """Execute a full OTEL dependency discovery sync cycle.

    1. Fetch edges from the OTEL backend
    2. Resolve service names to Tessera services
    3. Compute confidence and upsert dependencies
    4. Mark stale dependencies

    Args:
        session: Database session.
        config: The OTEL sync config to sync.
        http_client: Optional pre-configured httpx client (for testing).

    Returns:
        SyncResult with counts of fetched/resolved/created/updated/stale edges.
    """
    now = datetime.now(UTC)
    edges = await fetch_dependencies(config, http_client)

    unresolved: list[UnresolvedService] = []
    created_count = 0
    updated_count = 0
    resolved_count = 0

    for edge in edges:
        if edge.call_count < config.min_call_count:
            continue

        parent_svc = await resolve_service_name(session, edge.parent)
        child_svc = await resolve_service_name(session, edge.child)

        if parent_svc is None:
            unresolved.append(
                UnresolvedService(
                    otel_service_name=edge.parent,
                    role="parent",
                    edge_partner=edge.child,
                )
            )
        if child_svc is None:
            unresolved.append(
                UnresolvedService(
                    otel_service_name=edge.child,
                    role="child",
                    edge_partner=edge.parent,
                )
            )

        if parent_svc is None or child_svc is None:
            continue

        # Resolve services to assets (use the first asset as anchor)
        parent_asset = await _get_primary_asset(session, parent_svc.id)
        child_asset = await _get_primary_asset(session, child_svc.id)

        if parent_asset is None or child_asset is None:
            continue

        # child depends on parent (child calls parent)
        # Look up existing edge to get current syncs_seen for confidence calc
        existing_result = await session.execute(
            select(AssetDependencyDB).where(
                and_(
                    AssetDependencyDB.dependent_asset_id == child_asset.id,
                    AssetDependencyDB.dependency_asset_id == parent_asset.id,
                    AssetDependencyDB.dependency_type == DependencyType.CONSUMES,
                    AssetDependencyDB.source == DependencySource.OTEL,
                    AssetDependencyDB.deleted_at.is_(None),
                )
            )
        )
        existing_dep = existing_result.scalar_one_or_none()
        edge_syncs_seen = (existing_dep.syncs_seen + 1) if existing_dep else 1
        total_syncs = config.sync_count + 1  # +1 for the current sync

        confidence = compute_confidence(edge.call_count, edge_syncs_seen, total_syncs)
        if confidence < settings.otel_min_confidence:
            continue

        resolved_count += 1

        _, was_created = await upsert_otel_dependency(
            session=session,
            dependent_asset_id=child_asset.id,
            dependency_asset_id=parent_asset.id,
            call_count=edge.call_count,
            confidence=confidence,
            now=now,
            config_id=config.id,
        )
        if was_created:
            created_count += 1
        else:
            updated_count += 1

    stale_count = await mark_stale_dependencies(session, config, now)

    # Update config sync state
    config.sync_count = config.sync_count + 1
    config.last_synced_at = now
    config.last_sync_error = None
    await session.flush()

    return SyncResult(
        config_id=config.id,
        edges_fetched=len(edges),
        edges_resolved=resolved_count,
        edges_created=created_count,
        edges_updated=updated_count,
        edges_stale=stale_count,
        unresolved_services=unresolved,
    )


async def build_reconciliation_report(
    session: AsyncSession,
) -> ReconciliationReport:
    """Compare declared (manual) dependencies against observed (OTEL) dependencies.

    Returns three lists:
    - declared_only: manual deps with no OTEL observation (possibly stale)
    - observed_only: OTEL deps with no manual registration (undeclared)
    - both: deps that exist in both (confirmed)
    """
    # Fetch all active dependencies
    result = await session.execute(
        select(AssetDependencyDB).where(AssetDependencyDB.deleted_at.is_(None))
    )
    all_deps = list(result.scalars().all())

    # Group by (dependent, dependency) pair
    edge_map: dict[tuple[UUID, UUID], list[AssetDependencyDB]] = {}
    for dep in all_deps:
        key = (dep.dependent_asset_id, dep.dependency_asset_id)
        edge_map.setdefault(key, []).append(dep)

    # Collect asset IDs for service name lookup
    asset_ids: set[UUID] = set()
    for dep in all_deps:
        asset_ids.add(dep.dependent_asset_id)
        asset_ids.add(dep.dependency_asset_id)

    # Build asset_id → service_name mapping
    asset_service_names: dict[UUID, str] = {}
    if asset_ids:
        assets_result = await session.execute(
            select(AssetDB.id, ServiceDB.otel_service_name)
            .outerjoin(ServiceDB, AssetDB.service_id == ServiceDB.id)
            .where(AssetDB.id.in_(asset_ids))
        )
        for asset_id, svc_name in assets_result.all():
            if svc_name:
                asset_service_names[asset_id] = svc_name

    declared_only: list[ReconciliationItem] = []
    observed_only: list[ReconciliationItem] = []
    both: list[ReconciliationItem] = []

    for (dep_id, target_id), deps in edge_map.items():
        sources = {d.source for d in deps}
        has_manual = DependencySource.MANUAL in sources
        has_otel = DependencySource.OTEL in sources

        src_name = asset_service_names.get(dep_id)
        tgt_name = asset_service_names.get(target_id)

        otel_dep = next((d for d in deps if d.source == DependencySource.OTEL), None)
        manual_dep = next((d for d in deps if d.source == DependencySource.MANUAL), None)

        if has_manual and has_otel:
            both.append(
                ReconciliationItem(
                    source_service=src_name,
                    target_service=tgt_name,
                    dependent_asset_id=dep_id,
                    dependency_asset_id=target_id,
                    status="confirmed",
                    call_count=otel_dep.call_count if otel_dep else None,
                    confidence=otel_dep.confidence if otel_dep else None,
                    note="Declared dependency confirmed by OTEL traces",
                )
            )
        elif has_manual and not has_otel:
            # Check if manual dep was ever observed via last_observed_at
            observed = manual_dep and manual_dep.last_observed_at is not None
            declared_only.append(
                ReconciliationItem(
                    source_service=src_name,
                    target_service=tgt_name,
                    dependent_asset_id=dep_id,
                    dependency_asset_id=target_id,
                    status="possibly_stale",
                    note="Not observed in OTEL traces"
                    if not observed
                    else "Last observed via OTEL but no active OTEL edge",
                )
            )
        elif has_otel and not has_manual:
            observed_only.append(
                ReconciliationItem(
                    source_service=src_name,
                    target_service=tgt_name,
                    dependent_asset_id=dep_id,
                    dependency_asset_id=target_id,
                    status="undeclared",
                    call_count=otel_dep.call_count if otel_dep else None,
                    confidence=otel_dep.confidence if otel_dep else None,
                    note="Observed in traces but no explicit registration exists",
                )
            )

    return ReconciliationReport(
        declared_only=declared_only,
        observed_only=observed_only,
        both=both,
    )


async def get_due_configs(session: AsyncSession) -> list[OtelSyncConfigDB]:
    """Find enabled OTEL configs that are due for a sync.

    A config is due when either:
    - It has never been synced (last_synced_at IS NULL)
    - It was last synced more than poll_interval_seconds ago
    """
    now = datetime.now(UTC)
    result = await session.execute(
        select(OtelSyncConfigDB).where(
            and_(
                OtelSyncConfigDB.deleted_at.is_(None),
                OtelSyncConfigDB.enabled.is_(True),
                (
                    OtelSyncConfigDB.last_synced_at.is_(None)
                    | (
                        func.extract("epoch", now - OtelSyncConfigDB.last_synced_at)
                        > OtelSyncConfigDB.poll_interval_seconds
                    )
                ),
            )
        )
    )
    return list(result.scalars().all())
