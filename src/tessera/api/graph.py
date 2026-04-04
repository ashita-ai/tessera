"""Service dependency graph API endpoints.

Read-only API returning service-to-service dependency graph for visualization.
Aggregates declared dependencies into a graph-friendly format with caching.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.rate_limit import limit_read
from tessera.db import get_session
from tessera.models.graph import ImpactGraphResponse, ServiceGraphResponse
from tessera.services.cache import CacheService
from tessera.services.graph import build_impact_graph, build_neighborhood, build_service_graph

router = APIRouter()

# 60-second TTL per spec — graph changes infrequently
GRAPH_CACHE_TTL = 60
graph_cache = CacheService(prefix="graph", ttl=GRAPH_CACHE_TTL)


def _graph_cache_key(
    team_id: UUID | None,
    min_confidence: float,
    include_unregistered: bool,
) -> str:
    """Build a deterministic cache key for the full graph endpoint."""
    return f"services:team={team_id or 'all'}:conf={min_confidence}:unreg={include_unregistered}"


@router.get(
    "/services",
    response_model=ServiceGraphResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Forbidden — insufficient permissions"},
    },
)
@limit_read
async def get_service_graph(
    request: Request,
    auth: Auth,
    team_id: UUID | None = Query(None, description="Filter to services owned by this team"),
    min_confidence: float = Query(
        0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for OTEL edges (manual edges always included)",
    ),
    include_unregistered: bool = Query(
        False,
        description="Include OTEL-observed services not yet registered in Tessera",
    ),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ServiceGraphResponse:
    """Return the full service dependency graph.

    Nodes represent services; edges represent aggregated asset-level dependencies.
    When team_id is provided, the graph is scoped to that team's services plus
    their direct neighbors.
    """
    cache_key = _graph_cache_key(team_id, min_confidence, include_unregistered)
    cached = await graph_cache.get(cache_key)
    if cached is not None:
        return ServiceGraphResponse.model_validate(cached)

    graph = await build_service_graph(
        session,
        team_id=team_id,
        min_confidence=min_confidence,
    )

    await graph_cache.set(cache_key, graph.model_dump(mode="json"))
    return graph


@router.get(
    "/services/{service_id}/neighborhood",
    response_model=ServiceGraphResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Forbidden — insufficient permissions"},
        404: {"description": "Service not found"},
    },
)
@limit_read
async def get_service_neighborhood(
    request: Request,
    service_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ServiceGraphResponse:
    """Return the 1-hop subgraph around a service.

    Includes the service itself, all services it depends on (upstream),
    and all services that depend on it (downstream).
    """
    cache_key = f"neighborhood:{service_id}"
    cached = await graph_cache.get(cache_key)
    if cached is not None:
        return ServiceGraphResponse.model_validate(cached)

    graph = await build_neighborhood(session, service_id)
    await graph_cache.set(cache_key, graph.model_dump(mode="json"))
    return graph


@router.get(
    "/impact/{asset_id}",
    response_model=ImpactGraphResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Forbidden — insufficient permissions"},
        404: {"description": "Asset not found"},
    },
)
@limit_read
async def get_impact_graph(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    depth: int = Query(3, ge=1, le=10, description="Maximum traversal depth"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ImpactGraphResponse:
    """Return the subgraph of services affected by a change to the given asset.

    Traverses downstream dependencies up to the specified depth and maps
    asset-level impact to service-level for visualization.
    """
    cache_key = f"impact:{asset_id}:depth={depth}"
    cached = await graph_cache.get(cache_key)
    if cached is not None:
        return ImpactGraphResponse.model_validate(cached)

    result = await build_impact_graph(session, asset_id, depth=depth)
    await graph_cache.set(cache_key, result.model_dump(mode="json"))
    return result
