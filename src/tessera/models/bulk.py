"""Bulk operation models."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from tessera.models.enums import AcknowledgmentResponseType, GuaranteeMode, ResourceType


class BulkItemResult(BaseModel):
    """Result for a single item in a bulk operation."""

    success: bool
    index: int = Field(..., description="Original index in the request array")
    id: UUID | None = Field(default=None, description="ID of the created/updated resource")
    error: str | None = Field(default=None, description="Error message if operation failed")
    details: dict[str, Any] = Field(default_factory=dict)


class BulkOperationResponse(BaseModel):
    """Response for a bulk operation."""

    total: int = Field(..., description="Total number of items in the request")
    succeeded: int = Field(..., description="Number of successful operations")
    failed: int = Field(..., description="Number of failed operations")
    results: list[BulkItemResult] = Field(default_factory=list)


# Bulk Registration Models
class BulkRegistrationItem(BaseModel):
    """A single registration to create in a bulk request."""

    contract_id: UUID
    consumer_team_id: UUID
    pinned_version: str | None = Field(
        None,
        pattern=r"^\d+\.\d+\.\d+$",
        description="Pinned version (null = track latest compatible)",
    )


class BulkRegistrationRequest(BaseModel):
    """Request to create multiple registrations at once."""

    registrations: list[BulkRegistrationItem] = Field(
        ..., min_length=1, max_length=100, description="List of registrations to create (max 100)"
    )
    skip_duplicates: bool = Field(
        False, description="If true, skip duplicate registrations instead of failing"
    )


class BulkRegistrationResponse(BulkOperationResponse):
    """Response for bulk registration creation."""

    pass


# Bulk Asset Models
class BulkAssetItem(BaseModel):
    """A single asset to create in a bulk request."""

    fqn: str = Field(
        ...,
        min_length=3,
        description="Fully qualified name (e.g., 'snowflake.analytics.dim_customers')",
    )
    owner_team_id: UUID
    owner_user_id: UUID | None = None
    environment: str = Field(default="production", min_length=1, max_length=50)
    resource_type: ResourceType = ResourceType.OTHER
    guarantee_mode: GuaranteeMode = GuaranteeMode.NOTIFY
    metadata: dict[str, Any] = Field(default_factory=dict)


class BulkAssetRequest(BaseModel):
    """Request to create multiple assets at once."""

    assets: list[BulkAssetItem] = Field(
        ..., min_length=1, max_length=100, description="List of assets to create (max 100)"
    )
    skip_duplicates: bool = Field(
        False, description="If true, skip duplicate assets (by FQN) instead of failing"
    )


class BulkAssetResponse(BulkOperationResponse):
    """Response for bulk asset creation."""

    pass


# Bulk Acknowledgment Models
class BulkAcknowledgmentItem(BaseModel):
    """A single acknowledgment to create in a bulk request."""

    proposal_id: UUID
    consumer_team_id: UUID
    acknowledged_by_user_id: UUID | None = None
    response: AcknowledgmentResponseType
    migration_deadline: str | None = Field(
        None, description="ISO datetime string for migration deadline"
    )
    notes: str | None = None


class BulkAcknowledgmentRequest(BaseModel):
    """Request to acknowledge multiple proposals at once."""

    acknowledgments: list[BulkAcknowledgmentItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of acknowledgments to create (max 50)",
    )
    continue_on_error: bool = Field(
        True, description="If true, continue processing remaining items after an error"
    )


class BulkAcknowledgmentResponse(BulkOperationResponse):
    """Response for bulk acknowledgment creation."""

    pass
