"""Pydantic models for service dependency graph API responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ServiceNode(BaseModel):
    """A service node in the dependency graph."""

    id: UUID
    name: str
    repo_id: UUID
    repo_name: str
    team_id: UUID
    team_name: str
    asset_count: int
    has_breaking_proposal: bool
    last_synced_at: datetime | None
    sync_status: str = Field(description="One of: ok, error, never, stale")


class ServiceEdge(BaseModel):
    """A service-level dependency edge, aggregated from asset-level edges."""

    source: UUID = Field(description="Service that depends on the target")
    target: UUID = Field(description="Service being depended on")
    dependency_type: str
    source_type: str = Field(description="manual, otel, or inferred")
    confidence: float | None = Field(
        default=None, description="Max confidence across asset edges (OTEL only)"
    )
    call_count: int | None = Field(
        default=None, description="Sum of call counts across asset edges (OTEL only)"
    )
    asset_level_edges: int = Field(description="Number of asset-to-asset edges aggregated")


class UnregisteredService(BaseModel):
    """An OTEL-observed service not yet registered in Tessera."""

    otel_name: str
    connected_to: list[str]
    total_call_count: int


class GraphMetadata(BaseModel):
    """Summary metadata for the graph response."""

    node_count: int
    edge_count: int
    teams: list[str]
    last_otel_sync: datetime | None = None


class ServiceGraphResponse(BaseModel):
    """Full service dependency graph response."""

    nodes: list[ServiceNode]
    edges: list[ServiceEdge]
    unregistered_services: list[UnregisteredService]
    metadata: GraphMetadata


class SourceAsset(BaseModel):
    """The asset that is the root of an impact analysis."""

    id: UUID
    fqn: str
    service_name: str | None


class AffectedServiceNode(BaseModel):
    """A service affected by a change to the source asset."""

    id: UUID
    name: str
    team_name: str
    depth: int
    path: list[str]


class ImpactEdge(BaseModel):
    """An edge in the impact propagation graph."""

    source: str
    target: str
    depth: int


class ImpactGraphResponse(BaseModel):
    """Response for impact analysis graph endpoint."""

    source_asset: SourceAsset
    affected_services: list[AffectedServiceNode]
    impact_edges: list[ImpactEdge]
