"""Service dependency graph construction.

Aggregates asset-level dependencies into service-level edges for visualization.
Currently uses declared dependencies (asset_dependencies table).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    ProposalDB,
    RepoDB,
    ServiceDB,
    TeamDB,
)
from tessera.models.enums import ProposalStatus
from tessera.models.graph import (
    AffectedServiceNode,
    GraphMetadata,
    ImpactEdge,
    ImpactGraphResponse,
    ServiceEdge,
    ServiceGraphResponse,
    ServiceNode,
    SourceAsset,
)

# Services with last_synced_at older than this are "stale"
STALE_THRESHOLD = timedelta(hours=24)


def _sync_status(last_synced_at: datetime | None) -> str:
    """Derive sync status from the repo's last_synced_at timestamp."""
    if last_synced_at is None:
        return "never"
    age = datetime.now(UTC) - last_synced_at.replace(tzinfo=UTC)
    if age > STALE_THRESHOLD:
        return "stale"
    return "ok"


async def _load_service_nodes(
    session: AsyncSession,
    team_id: UUID | None = None,
) -> list[ServiceNode]:
    """Load all active services as graph nodes with asset counts and breaking proposal flags.

    If team_id is provided, only loads services owned by that team. The caller
    is responsible for expanding to include neighbor services.
    """
    # Base query: services joined to repos and teams with asset counts
    svc_query = (
        select(
            ServiceDB.id,
            ServiceDB.name,
            ServiceDB.repo_id,
            RepoDB.name.label("repo_name"),
            ServiceDB.owner_team_id,
            TeamDB.name.label("team_name"),
            RepoDB.last_synced_at,
            func.count(AssetDB.id).label("asset_count"),
        )
        .join(RepoDB, ServiceDB.repo_id == RepoDB.id)
        .join(TeamDB, ServiceDB.owner_team_id == TeamDB.id)
        .outerjoin(
            AssetDB,
            (AssetDB.service_id == ServiceDB.id) & (AssetDB.deleted_at.is_(None)),
        )
        .where(ServiceDB.deleted_at.is_(None))
        .group_by(
            ServiceDB.id,
            ServiceDB.name,
            ServiceDB.repo_id,
            RepoDB.name,
            ServiceDB.owner_team_id,
            TeamDB.name,
            RepoDB.last_synced_at,
        )
    )

    if team_id is not None:
        svc_query = svc_query.where(ServiceDB.owner_team_id == team_id)

    result = await session.execute(svc_query)
    rows = result.all()

    if not rows:
        return []

    service_ids = [row.id for row in rows]

    # Batch check for pending breaking proposals across all service assets
    breaking_query = (
        select(AssetDB.service_id)
        .join(ProposalDB, ProposalDB.asset_id == AssetDB.id)
        .where(AssetDB.service_id.in_(service_ids))
        .where(AssetDB.deleted_at.is_(None))
        .where(ProposalDB.status == ProposalStatus.PENDING)
        .group_by(AssetDB.service_id)
    )
    breaking_result = await session.execute(breaking_query)
    services_with_breaking: set[UUID] = {row[0] for row in breaking_result.all()}

    return [
        ServiceNode(
            id=row.id,
            name=row.name,
            repo_id=row.repo_id,
            repo_name=row.repo_name,
            team_id=row.owner_team_id,
            team_name=row.team_name,
            asset_count=row.asset_count,
            has_breaking_proposal=row.id in services_with_breaking,
            last_synced_at=row.last_synced_at,
            sync_status=_sync_status(row.last_synced_at),
        )
        for row in rows
    ]


async def _load_service_edges(
    session: AsyncSession,
    service_ids: set[UUID] | None = None,
) -> list[ServiceEdge]:
    """Load and aggregate asset-level dependencies into service-level edges.

    Groups by (source_service, target_service, dependency_type). For each group:
      - confidence = max (NULL for manual-only edges)
      - call_count = sum (NULL for manual-only edges)
      - asset_level_edges = count of asset pairs

    Args:
        session: Database session.
        service_ids: If provided, only include edges where both endpoints are
            in this set. Pass None for full graph.
    """
    # Alias the assets table for source and target sides of the join
    src_asset = AssetDB.__table__.alias("src_asset")
    tgt_asset = AssetDB.__table__.alias("tgt_asset")

    edge_query = (
        select(
            src_asset.c.service_id.label("source_service_id"),
            tgt_asset.c.service_id.label("target_service_id"),
            AssetDependencyDB.dependency_type,
            func.count().label("edge_count"),
        )
        .join(
            src_asset,
            AssetDependencyDB.dependent_asset_id == src_asset.c.id,
        )
        .join(
            tgt_asset,
            AssetDependencyDB.dependency_asset_id == tgt_asset.c.id,
        )
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(src_asset.c.deleted_at.is_(None))
        .where(tgt_asset.c.deleted_at.is_(None))
        .where(src_asset.c.service_id.is_not(None))
        .where(tgt_asset.c.service_id.is_not(None))
        # Exclude self-loops at service level
        .where(src_asset.c.service_id != tgt_asset.c.service_id)
        .group_by(
            src_asset.c.service_id,
            tgt_asset.c.service_id,
            AssetDependencyDB.dependency_type,
        )
    )

    if service_ids is not None:
        edge_query = edge_query.where(
            src_asset.c.service_id.in_(service_ids) & tgt_asset.c.service_id.in_(service_ids)
        )

    result = await session.execute(edge_query)
    rows = result.all()

    return [
        ServiceEdge(
            source=row.source_service_id,
            target=row.target_service_id,
            dependency_type=str(row.dependency_type),
            source_type="manual",
            confidence=None,
            call_count=None,
            asset_level_edges=row.edge_count,
        )
        for row in rows
    ]


async def build_service_graph(
    session: AsyncSession,
    team_id: UUID | None = None,
) -> ServiceGraphResponse:
    """Build the full service dependency graph.

    When team_id is provided, the graph is scoped to that team's services
    plus their direct neighbors (services connected by at least one edge).
    """
    # 1. Load all edges first (unfiltered) so we can find neighbors
    all_edges = await _load_service_edges(session)

    # 2. Load services (filtered by team if requested)
    if team_id is not None:
        team_nodes = await _load_service_nodes(session, team_id=team_id)
        team_service_ids = {n.id for n in team_nodes}

        # Find neighbor service IDs from edges
        neighbor_ids: set[UUID] = set()
        for edge in all_edges:
            if edge.source in team_service_ids:
                neighbor_ids.add(edge.target)
            if edge.target in team_service_ids:
                neighbor_ids.add(edge.source)
        neighbor_ids -= team_service_ids

        # Load neighbor nodes
        if neighbor_ids:
            neighbor_nodes = await _load_service_nodes(session)
            neighbor_nodes = [n for n in neighbor_nodes if n.id in neighbor_ids]
            nodes = team_nodes + neighbor_nodes
        else:
            nodes = team_nodes

        # Filter edges to only those touching our node set
        node_ids = {n.id for n in nodes}
        edges = [e for e in all_edges if e.source in node_ids and e.target in node_ids]
    else:
        nodes = await _load_service_nodes(session)
        edges = all_edges

    teams_in_graph = sorted({n.team_name for n in nodes})

    return ServiceGraphResponse(
        nodes=nodes,
        edges=edges,
        unregistered_services=[],
        metadata=GraphMetadata(
            node_count=len(nodes),
            edge_count=len(edges),
            teams=teams_in_graph,
            last_otel_sync=None,
        ),
    )


async def build_neighborhood(
    session: AsyncSession,
    service_id: UUID,
) -> ServiceGraphResponse:
    """Build a 1-hop subgraph around the given service.

    Returns the service, its direct upstream dependencies, and its direct
    downstream dependents. Raises NotFoundError if the service does not exist.
    """
    svc_result = await session.execute(
        select(ServiceDB.id).where(ServiceDB.id == service_id).where(ServiceDB.deleted_at.is_(None))
    )
    if svc_result.scalar_one_or_none() is None:
        from tessera.api.errors import ErrorCode, NotFoundError

        raise NotFoundError(ErrorCode.SERVICE_NOT_FOUND, "Service not found")

    all_edges = await _load_service_edges(session)

    # Find all services connected to this one (1-hop)
    neighbor_ids: set[UUID] = {service_id}
    for edge in all_edges:
        if edge.source == service_id:
            neighbor_ids.add(edge.target)
        if edge.target == service_id:
            neighbor_ids.add(edge.source)

    # Load all nodes, filter to neighborhood
    all_nodes = await _load_service_nodes(session)
    nodes = [n for n in all_nodes if n.id in neighbor_ids]

    # Filter edges to only those within the neighborhood
    edges = [e for e in all_edges if e.source in neighbor_ids and e.target in neighbor_ids]

    teams_in_graph = sorted({n.team_name for n in nodes})

    return ServiceGraphResponse(
        nodes=nodes,
        edges=edges,
        unregistered_services=[],
        metadata=GraphMetadata(
            node_count=len(nodes),
            edge_count=len(edges),
            teams=teams_in_graph,
            last_otel_sync=None,
        ),
    )


async def build_impact_graph(
    session: AsyncSession,
    asset_id: UUID,
    depth: int = 3,
) -> ImpactGraphResponse:
    """Build the impact propagation subgraph for a given asset.

    Traverses downstream asset dependencies breadth-first, then maps each
    affected asset to its owning service. Returns unique service-level paths.
    """
    # Load source asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    source_asset = asset_result.scalar_one_or_none()
    if source_asset is None:
        from tessera.api.errors import ErrorCode, NotFoundError

        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Resolve source service name
    source_service_name: str | None = None
    if source_asset.service_id:
        svc_result = await session.execute(
            select(ServiceDB.name).where(ServiceDB.id == source_asset.service_id)
        )
        row = svc_result.scalar_one_or_none()
        if row:
            source_service_name = row

    # BFS traversal of downstream asset dependencies
    visited: set[UUID] = {asset_id}
    # Map asset_id -> (depth, parent_asset_id)
    asset_parents: dict[UUID, tuple[int, UUID | None]] = {asset_id: (0, None)}
    current_ids = [asset_id]

    for current_depth in range(1, depth + 1):
        if not current_ids:
            break

        deps_query = (
            select(AssetDependencyDB.dependent_asset_id, AssetDependencyDB.dependency_asset_id)
            .where(AssetDependencyDB.dependency_asset_id.in_(current_ids))
            .where(AssetDependencyDB.deleted_at.is_(None))
        )
        deps_result = await session.execute(deps_query)
        downstream = deps_result.all()

        next_ids: list[UUID] = []
        for dependent_id, parent_id in downstream:
            if dependent_id not in visited:
                visited.add(dependent_id)
                asset_parents[dependent_id] = (current_depth, parent_id)
                next_ids.append(dependent_id)

        current_ids = next_ids

    # Remove the source asset from results
    downstream_asset_ids = [aid for aid in visited if aid != asset_id]

    if not downstream_asset_ids:
        return ImpactGraphResponse(
            source_asset=SourceAsset(
                id=source_asset.id,
                fqn=source_asset.fqn,
                service_name=source_service_name,
            ),
            affected_services=[],
            impact_edges=[],
        )

    # Load downstream assets with their service and team info
    downstream_query = (
        select(AssetDB.id, AssetDB.service_id, ServiceDB.name, TeamDB.name.label("team_name"))
        .outerjoin(ServiceDB, AssetDB.service_id == ServiceDB.id)
        .outerjoin(TeamDB, ServiceDB.owner_team_id == TeamDB.id)
        .where(AssetDB.id.in_(downstream_asset_ids))
        .where(AssetDB.deleted_at.is_(None))
    )
    ds_result = await session.execute(downstream_query)
    ds_rows: list[Any] = list(ds_result.all())

    # Map asset -> service info
    # Row columns: (asset_id, service_id, service_name, team_name)
    asset_to_service: dict[UUID, tuple[UUID | None, str | None, str | None]] = {}
    for row in ds_rows:
        asset_to_service[row[0]] = (row[1], row[2], row[3])

    # Also map the source asset
    asset_to_service[asset_id] = (source_asset.service_id, source_service_name, None)

    # Build service-level path for each affected asset
    def _build_service_path(aid: UUID) -> list[str]:
        """Walk parent chain to build service name path."""
        path: list[str] = []
        current: UUID | None = aid
        seen: set[UUID] = set()
        while current is not None and current not in seen:
            seen.add(current)
            svc_info = asset_to_service.get(current)
            svc_name = svc_info[1] if svc_info else None
            if svc_name and (not path or path[-1] != svc_name):
                path.append(svc_name)
            parent_info = asset_parents.get(current)
            current = parent_info[1] if parent_info else None
        path.reverse()
        return path

    # Deduplicate to service level: one entry per (service_id, depth)
    seen_services: dict[UUID, AffectedServiceNode] = {}
    impact_edge_pairs: set[tuple[str, str, int]] = set()

    for aid in downstream_asset_ids:
        svc_info = asset_to_service.get(aid)
        if not svc_info or svc_info[0] is None:
            continue  # Asset not assigned to a service
        svc_id_raw, svc_name, team_name = svc_info
        assert svc_id_raw is not None  # guarded above
        svc_id: UUID = svc_id_raw
        asset_depth = asset_parents[aid][0]
        path = _build_service_path(aid)

        # Keep the shallowest depth per service
        if svc_id not in seen_services or asset_depth < seen_services[svc_id].depth:
            seen_services[svc_id] = AffectedServiceNode(
                id=svc_id,
                name=svc_name or "unknown",
                team_name=team_name or "unknown",
                depth=asset_depth,
                path=path,
            )

        # Build impact edges from service path
        for i in range(len(path) - 1):
            impact_edge_pairs.add((path[i], path[i + 1], i + 1))

    affected = sorted(seen_services.values(), key=lambda s: (s.depth, s.name))
    impact_edges = [
        ImpactEdge(source=src, target=tgt, depth=d)
        for src, tgt, d in sorted(impact_edge_pairs, key=lambda x: (x[2], x[0]))
    ]

    return ImpactGraphResponse(
        source_asset=SourceAsset(
            id=source_asset.id,
            fqn=source_asset.fqn,
            service_name=source_service_name,
        ),
        affected_services=affected,
        impact_edges=impact_edges,
    )
