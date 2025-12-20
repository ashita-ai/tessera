"""Pydantic models for asset dependencies."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tessera.models.enums import DependencyType


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
    created_at: datetime
