"""Pydantic models for OTEL dependency discovery."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.models.enums import DependencySource, OtelBackendType


class OtelSyncConfigCreate(BaseModel):
    """Request body for registering an OTEL backend."""

    name: str = Field(..., min_length=1, max_length=200)
    backend_type: OtelBackendType
    endpoint_url: str = Field(..., min_length=1, max_length=500)
    auth_header: str | None = Field(default=None, max_length=500)
    lookback_seconds: int = Field(default=86400, ge=60, le=604800)
    poll_interval_seconds: int = Field(default=3600, ge=300, le=86400)
    min_call_count: int = Field(default=10, ge=1, le=100000)
    enabled: bool = True

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str) -> str:
        """Reject non-HTTP schemes to prevent SSRF via file://, ftp://, etc."""
        lowered = v.lower().strip()
        if not (lowered.startswith("http://") or lowered.startswith("https://")):
            raise ValueError("endpoint_url must use http:// or https:// scheme")
        return v


class OtelSyncConfigUpdate(BaseModel):
    """Request body for updating an OTEL backend config."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=500)
    auth_header: str | None = None
    lookback_seconds: int | None = Field(default=None, ge=60, le=604800)
    poll_interval_seconds: int | None = Field(default=None, ge=300, le=86400)
    min_call_count: int | None = Field(default=None, ge=1, le=100000)
    enabled: bool | None = None

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str | None) -> str | None:
        """Reject non-HTTP schemes to prevent SSRF."""
        if v is None:
            return v
        lowered = v.lower().strip()
        if not (lowered.startswith("http://") or lowered.startswith("https://")):
            raise ValueError("endpoint_url must use http:// or https:// scheme")
        return v


class OtelSyncConfig(BaseModel):
    """Response model for an OTEL sync config."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    backend_type: OtelBackendType
    endpoint_url: str
    lookback_seconds: int
    poll_interval_seconds: int
    min_call_count: int
    enabled: bool
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    created_at: datetime


class OtelDependency(BaseModel):
    """An OTEL-discovered dependency edge."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dependent_asset_id: UUID
    dependency_asset_id: UUID
    source: DependencySource
    confidence: float | None = None
    last_observed_at: datetime | None = None
    call_count: int | None = None
    otel_config_id: UUID | None = None
    created_at: datetime


class OtelServiceEdge(BaseModel):
    """A raw dependency edge from an OTEL backend (pre-resolution)."""

    parent: str
    child: str
    call_count: int


class UnresolvedService(BaseModel):
    """A service name from OTEL that could not be resolved to a Tessera service."""

    otel_service_name: str
    role: str  # "parent" or "child"
    edge_partner: str  # the other side of the edge


class SyncResult(BaseModel):
    """Result of an OTEL sync operation."""

    config_id: UUID
    edges_fetched: int
    edges_resolved: int
    edges_created: int
    edges_updated: int
    edges_stale: int
    unresolved_services: list[UnresolvedService]


class ReconciliationItem(BaseModel):
    """A single item in the reconciliation report."""

    source_service: str | None = None
    target_service: str | None = None
    dependent_asset_id: UUID | None = None
    dependency_asset_id: UUID | None = None
    status: str  # "confirmed", "undeclared", "possibly_stale"
    call_count: int | None = None
    confidence: float | None = None
    note: str


class ReconciliationReport(BaseModel):
    """Declared vs observed dependency comparison."""

    declared_only: list[ReconciliationItem]
    observed_only: list[ReconciliationItem]
    both: list[ReconciliationItem]
