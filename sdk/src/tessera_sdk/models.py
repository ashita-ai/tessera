"""Pydantic models for Tessera SDK."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# StrEnum is Python 3.11+, use str + Enum for 3.10 compatibility
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """String enum for Python 3.10 compatibility."""

        pass


# Enums
class CompatibilityMode(StrEnum):
    """Schema compatibility modes."""

    BACKWARD = "backward"
    FORWARD = "forward"
    FULL = "full"
    NONE = "none"


class ContractStatus(StrEnum):
    """Lifecycle status of a contract."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RegistrationStatus(StrEnum):
    """Status of a consumer registration."""

    ACTIVE = "active"
    MIGRATING = "migrating"
    INACTIVE = "inactive"


class ChangeType(StrEnum):
    """Semantic versioning change classification."""

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


class ProposalStatus(StrEnum):
    """Status of a breaking change proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class AcknowledgmentResponseType(StrEnum):
    """Consumer response to a proposal."""

    APPROVED = "approved"
    BLOCKED = "blocked"
    MIGRATING = "migrating"


class DependencyType(StrEnum):
    """Type of asset-to-asset dependency."""

    CONSUMES = "consumes"
    REFERENCES = "references"
    TRANSFORMS = "transforms"


# Team models
class Team(BaseModel):
    """Team entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TeamCreate(BaseModel):
    """Fields for creating a team."""

    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeamUpdate(BaseModel):
    """Fields for updating a team."""

    name: str | None = Field(None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None


# Asset models
class Asset(BaseModel):
    """Asset entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fqn: str
    owner_team_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AssetCreate(BaseModel):
    """Fields for creating an asset."""

    fqn: str = Field(..., min_length=1, max_length=1000)
    owner_team_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetUpdate(BaseModel):
    """Fields for updating an asset."""

    fqn: str | None = Field(None, min_length=1, max_length=1000)
    owner_team_id: UUID | None = None
    metadata: dict[str, Any] | None = None


# Contract models
class Guarantees(BaseModel):
    """Contract guarantees beyond schema."""

    freshness: dict[str, Any] | None = None
    volume: dict[str, Any] | None = None
    nullability: dict[str, str] | None = None
    accepted_values: dict[str, list[str]] | None = None


class Contract(BaseModel):
    """Contract entity."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    asset_id: UUID
    version: str
    schema_def: dict[str, Any] = Field(..., alias="schema")
    compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD
    guarantees: Guarantees | None = None
    status: ContractStatus = ContractStatus.ACTIVE
    published_at: datetime
    published_by: UUID


class ContractCreate(BaseModel):
    """Fields for creating a contract."""

    model_config = ConfigDict(populate_by_name=True)

    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    schema_def: dict[str, Any] = Field(..., serialization_alias="schema")
    compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD
    guarantees: Guarantees | None = None


# Registration models
class Registration(BaseModel):
    """Registration entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    consumer_team_id: UUID
    pinned_version: str | None = None
    status: RegistrationStatus = RegistrationStatus.ACTIVE
    registered_at: datetime
    acknowledged_at: datetime | None = None


class RegistrationCreate(BaseModel):
    """Fields for creating a registration."""

    consumer_team_id: UUID
    pinned_version: str | None = Field(None, pattern=r"^\d+\.\d+\.\d+$")


class RegistrationUpdate(BaseModel):
    """Fields for updating a registration."""

    pinned_version: str | None = None
    status: RegistrationStatus | None = None


# Proposal models
class BreakingChange(BaseModel):
    """A specific breaking change in a proposal."""

    type: str
    column: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """Proposal entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    proposed_schema: dict[str, Any]
    change_type: ChangeType
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    proposed_by: UUID
    proposed_at: datetime
    resolved_at: datetime | None = None


class ProposalCreate(BaseModel):
    """Fields for creating a proposal."""

    proposed_schema: dict[str, Any]


# Acknowledgment models
class Acknowledgment(BaseModel):
    """Acknowledgment entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proposal_id: UUID
    consumer_team_id: UUID
    response: AcknowledgmentResponseType
    notes: str | None = None
    acknowledged_at: datetime


class AcknowledgmentCreate(BaseModel):
    """Fields for creating an acknowledgment."""

    consumer_team_id: UUID
    response: AcknowledgmentResponseType
    notes: str | None = None


# Dependency models
class Dependency(BaseModel):
    """Dependency entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_asset_id: UUID
    target_asset_id: UUID
    dependency_type: DependencyType
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DependencyCreate(BaseModel):
    """Fields for creating a dependency."""

    target_asset_id: UUID
    dependency_type: DependencyType
    metadata: dict[str, Any] = Field(default_factory=dict)


# Response models for specific endpoints
class ImpactAnalysis(BaseModel):
    """Result of impact analysis."""

    asset_id: UUID
    safe_to_publish: bool
    change_type: ChangeType
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    impacted_consumers: list[dict[str, Any]] = Field(default_factory=list)


class ContractDiff(BaseModel):
    """Result of schema diff between contracts."""

    from_version: str
    to_version: str
    change_type: ChangeType
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    all_changes: list[dict[str, Any]] = Field(default_factory=list)


class PublishResult(BaseModel):
    """Result of contract publishing."""

    contract: Contract | None = None
    proposal: Proposal | None = None
    message: str


class ProposalStatusResponse(BaseModel):
    """Status of a proposal with acknowledgment details."""

    proposal: Proposal
    required_acknowledgments: int
    received_acknowledgments: int
    pending_consumers: list[dict[str, Any]] = Field(default_factory=list)
    acknowledged_consumers: list[dict[str, Any]] = Field(default_factory=list)


class LineageResponse(BaseModel):
    """Lineage graph for an asset."""

    asset_id: UUID
    upstream: list[dict[str, Any]] = Field(default_factory=list)
    downstream: list[dict[str, Any]] = Field(default_factory=list)
