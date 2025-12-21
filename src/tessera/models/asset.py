"""Asset models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# FQN pattern: alphanumeric/underscores separated by dots, at least 2 segments
# Examples: db.schema.table, schema.table, my_db.my_schema.my_table
FQN_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")


class AssetBase(BaseModel):
    """Base asset fields."""

    fqn: str = Field(
        ...,
        min_length=3,  # Minimum: "a.b"
        max_length=1000,
        description="Fully qualified name (e.g., 'snowflake.analytics.dim_customers')",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fqn")
    @classmethod
    def validate_fqn_format(cls, v: str) -> str:
        """Validate FQN format: alphanumeric segments separated by dots."""
        if not FQN_PATTERN.match(v):
            raise ValueError(
                "FQN must be dot-separated segments (e.g., 'database.schema.table'). "
                "Each segment must start with a letter or underscore and contain only "
                "alphanumeric characters and underscores."
            )
        return v


class AssetCreate(AssetBase):
    """Fields for creating an asset."""

    owner_team_id: UUID


class AssetUpdate(BaseModel):
    """Fields for updating an asset."""

    fqn: str | None = Field(None, min_length=1, max_length=1000)
    owner_team_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class Asset(BaseModel):
    """Asset entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fqn: str
    owner_team_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
