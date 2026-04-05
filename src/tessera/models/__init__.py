"""Pydantic models for Tessera entities."""

from tessera.models.acknowledgment import (
    Acknowledgment,
    AcknowledgmentCreate,
)
from tessera.models.asset import (
    Asset,
    AssetCreate,
    AssetUpdate,
    AssetWithOwners,
    AssetWithTeam,
    BulkAssignRequest,
)
from tessera.models.bulk import (
    BulkAcknowledgmentItem,
    BulkAcknowledgmentRequest,
    BulkAcknowledgmentResponse,
    BulkAssetItem,
    BulkAssetRequest,
    BulkAssetResponse,
    BulkContractItem,
    BulkContractRequest,
    BulkContractResponse,
    BulkContractResultItem,
    BulkItemResult,
    BulkOperationResponse,
    BulkRegistrationItem,
    BulkRegistrationRequest,
    BulkRegistrationResponse,
)
from tessera.models.contract import (
    Contract,
    ContractCreate,
    Guarantees,
    VersionSuggestion,
    VersionSuggestionRequest,
)
from tessera.models.dependency import Dependency, DependencyCreate
from tessera.models.enums import (
    AcknowledgmentResponseType,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    DependencyType,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.models.proposal import (
    AffectedAsset,
    AffectedTeam,
    Objection,
    ObjectionCreate,
    PendingProposalsResponse,
    PendingProposalSummary,
    Proposal,
    ProposalCreate,
)
from tessera.models.registration import Registration, RegistrationCreate, RegistrationUpdate
from tessera.models.repo import Repo, RepoCreate, RepoUpdate
from tessera.models.service import Service, ServiceCreate, ServiceUpdate
from tessera.models.slack_config import (
    SlackConfig,
    SlackConfigCreate,
    SlackConfigResponse,
    SlackConfigUpdate,
    TestMessageResult,
)
from tessera.models.team import Team, TeamCreate, TeamUpdate
from tessera.models.user import User, UserCreate, UserUpdate, UserWithTeam
from tessera.models.webhook import WebhookDelivery

__all__ = [
    # Enums
    "AcknowledgmentResponseType",
    "ChangeType",
    "CompatibilityMode",
    "ContractStatus",
    "DependencyType",
    "ProposalStatus",
    "RegistrationStatus",
    # User
    "User",
    "UserCreate",
    "UserUpdate",
    "UserWithTeam",
    # Service
    "Service",
    "ServiceCreate",
    "ServiceUpdate",
    # Team
    "Team",
    "TeamCreate",
    "TeamUpdate",
    # Asset
    "Asset",
    "AssetCreate",
    "AssetUpdate",
    "AssetWithOwners",
    "AssetWithTeam",
    "BulkAssignRequest",
    # Contract
    "Contract",
    "ContractCreate",
    "Guarantees",
    "VersionSuggestion",
    "VersionSuggestionRequest",
    # Dependency
    "Dependency",
    "DependencyCreate",
    # Registration
    "Registration",
    "RegistrationCreate",
    "RegistrationUpdate",
    # Repo
    "Repo",
    "RepoCreate",
    "RepoUpdate",
    # Proposal
    "AffectedAsset",
    "AffectedTeam",
    "Objection",
    "ObjectionCreate",
    "PendingProposalSummary",
    "PendingProposalsResponse",
    "Proposal",
    "ProposalCreate",
    # Acknowledgment
    "Acknowledgment",
    "AcknowledgmentCreate",
    # Bulk Operations
    "BulkItemResult",
    "BulkOperationResponse",
    "BulkRegistrationItem",
    "BulkRegistrationRequest",
    "BulkRegistrationResponse",
    "BulkAssetItem",
    "BulkAssetRequest",
    "BulkAssetResponse",
    "BulkAcknowledgmentItem",
    "BulkAcknowledgmentRequest",
    "BulkAcknowledgmentResponse",
    "BulkContractItem",
    "BulkContractRequest",
    "BulkContractResponse",
    "BulkContractResultItem",
    # Slack Config
    "SlackConfig",
    "SlackConfigCreate",
    "SlackConfigResponse",
    "SlackConfigUpdate",
    "TestMessageResult",
    # Webhook Delivery
    "WebhookDelivery",
]
