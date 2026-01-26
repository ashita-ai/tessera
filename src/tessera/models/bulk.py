"""Bulk operation models."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from tessera.models.asset import FQN_PATTERN
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


# Bulk Contract Models
class BulkContractItem(BaseModel):
    """A single contract to publish in a bulk request."""

    asset_id: UUID = Field(..., description="ID of the asset to publish contract for")
    schema_def: dict[str, Any] = Field(..., alias="schema", description="JSON Schema definition")
    compatibility_mode: str | None = Field(
        None,
        description="Compatibility mode (backward, forward, full, none). "
        "Uses asset default if not specified.",
    )
    guarantees: dict[str, Any] | None = Field(None, description="Contract guarantees")


class BulkContractRequest(BaseModel):
    """Request to publish multiple contracts at once."""

    contracts: list[BulkContractItem] = Field(
        ..., min_length=1, max_length=100, description="List of contracts to publish (max 100)"
    )
    published_by: UUID = Field(..., description="Team ID of the publisher")
    published_by_user_id: UUID | None = Field(None, description="User ID who published")


class BulkContractResultStatus(str):
    """Status values for bulk contract results."""

    # Preview statuses
    WILL_PUBLISH = "will_publish"
    WILL_SKIP = "will_skip"
    BREAKING = "breaking"
    # Execution statuses
    PUBLISHED = "published"
    SKIPPED = "skipped"
    PROPOSAL_CREATED = "proposal_created"
    FAILED = "failed"


class BulkContractResultItem(BaseModel):
    """Result for a single contract in a bulk operation."""

    asset_id: UUID
    asset_fqn: str | None = Field(default=None, description="FQN of the asset")
    status: str = Field(..., description="Result status")
    contract_id: UUID | None = Field(default=None, description="ID of published contract")
    proposal_id: UUID | None = Field(default=None, description="ID of created proposal")
    suggested_version: str | None = Field(default=None, description="Suggested version")
    current_version: str | None = Field(default=None, description="Current active version")
    reason: str | None = Field(default=None, description="Reason for status")
    breaking_changes: list[dict[str, Any]] = Field(
        default_factory=list, description="Breaking changes detected"
    )
    error: str | None = Field(default=None, description="Error message if failed")


class BulkContractResponse(BaseModel):
    """Response for bulk contract publishing."""

    preview: bool = Field(..., description="True if this is a dry-run preview")
    total: int = Field(..., description="Total contracts in request")
    published: int = Field(0, description="Contracts published (or would_publish in preview)")
    skipped: int = Field(0, description="Contracts skipped due to no changes")
    proposals_created: int = Field(0, description="Proposals created for breaking changes")
    failed: int = Field(0, description="Contracts that failed validation/processing")
    results: list[BulkContractResultItem] = Field(default_factory=list)
