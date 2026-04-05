"""Pydantic models for asset dependencies."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tessera.models.enums import DependencySource, DependencyType


class DependencyCreate(BaseModel):
    """Request body for creating an asset dependency."""

    depends_on_asset_id: UUID
    dependency_type: DependencyType = DependencyType.CONSUMES


class Dependency(BaseModel):
    """Response model for an asset dependency."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dependent_asset_id: UUID
    dependency_asset_id: UUID
    dependency_type: DependencyType
    source: DependencySource = DependencySource.MANUAL
    confidence: float | None = None
    last_observed_at: datetime | None = None
    call_count: int | None = None
    created_at: datetime
