"""Asset models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.config import settings
from tessera.models.enums import GuaranteeMode, ResourceType

# FQN pattern: alphanumeric/underscores separated by dots, at least 2 segments
# Examples: db.schema.table, schema.table, my_db.my_schema.my_table
FQN_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")


class AssetBase(BaseModel):
    """Base asset fields."""

    fqn: str = Field(
        ...,
        min_length=3,  # Minimum: "a.b"
        max_length=settings.max_fqn_length,
        description="Fully qualified name (e.g., 'snowflake.analytics.dim_customers')",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    environment: str = Field(
        default_factory=lambda: settings.default_environment,
        min_length=1,
        max_length=50,
        description="Environment (e.g., 'dev', 'staging', 'production')",
    )

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
    owner_user_id: UUID | None = None
    resource_type: ResourceType = ResourceType.UNKNOWN
    guarantee_mode: GuaranteeMode = GuaranteeMode.NOTIFY


class AssetUpdate(BaseModel):
    """Fields for updating an asset."""

    fqn: str | None = Field(None, min_length=1, max_length=settings.max_fqn_length)
    owner_team_id: UUID | None = None
    owner_user_id: UUID | None = None
    environment: str | None = Field(None, min_length=1, max_length=50)
    resource_type: ResourceType | None = None
    guarantee_mode: GuaranteeMode | None = None
    metadata: dict[str, Any] | None = None


class Asset(BaseModel):
    """Asset entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fqn: str
    owner_team_id: UUID
    owner_user_id: UUID | None = None
    environment: str
    resource_type: ResourceType = ResourceType.UNKNOWN
    guarantee_mode: GuaranteeMode = GuaranteeMode.NOTIFY
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime


class AssetWithOwners(Asset):
    """Asset with owner team and user names for display."""

    owner_team_name: str | None = None
    owner_user_name: str | None = None
    owner_user_email: str | None = None


# Backwards compatible alias
AssetWithTeam = AssetWithOwners


class BulkAssignRequest(BaseModel):
    """Request to bulk assign assets to a user."""

    asset_ids: list[UUID] = Field(..., min_length=1)
    owner_user_id: UUID | None = Field(
        None, description="User to assign ownership to. Set to null to unassign."
    )
