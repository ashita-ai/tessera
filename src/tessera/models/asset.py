"""Asset models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssetBase(BaseModel):
    """Base asset fields."""

    fqn: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Fully qualified name (e.g., 'snowflake.analytics.dim_customers')",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetCreate(AssetBase):
    """Fields for creating an asset."""

    owner_team_id: UUID


class AssetUpdate(BaseModel):
    """Fields for updating an asset."""

    fqn: str | None = Field(None, min_length=1, max_length=1000)
    owner_team_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class Asset(AssetBase):
    """Asset entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_team_id: UUID
    created_at: datetime
