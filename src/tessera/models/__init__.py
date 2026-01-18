"""Pydantic models for Tessera entities."""

from tessera.models.acknowledgment import (
    Acknowledgment,
    AcknowledgmentCreate,
    AcknowledgmentResponse,
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
    Proposal,
    ProposalCreate,
)
from tessera.models.registration import Registration, RegistrationCreate, RegistrationUpdate
from tessera.models.team import Team, TeamCreate, TeamUpdate
from tessera.models.user import User, UserCreate, UserUpdate, UserWithTeam

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
    # Proposal
    "AffectedAsset",
    "AffectedTeam",
    "Objection",
    "ObjectionCreate",
    "Proposal",
    "ProposalCreate",
    # Acknowledgment
    "Acknowledgment",
    "AcknowledgmentCreate",
    "AcknowledgmentResponse",
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
]
