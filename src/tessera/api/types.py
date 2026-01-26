"""Type definitions for API responses.

This module provides TypedDict definitions for API response structures,
improving type safety and IDE autocompletion over plain dict[str, Any].
"""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from typing_extensions import TypedDict

from tessera.models.enums import ContractStatus

_T = TypeVar("_T")


class PaginatedResponse(TypedDict, Generic[_T]):
    """Generic paginated response structure."""

    results: list[_T]
    total: int
    limit: int
    offset: int


class AssetSearchResult(TypedDict):
    """Single result from asset search."""

    id: str
    fqn: str
    owner_team_id: str
    owner_team_name: str
    environment: str


class AssetWithOwnerInfo(TypedDict, total=False):
    """Asset data enriched with owner team/user names.

    Extends the base Asset model with additional relationship data.
    Uses total=False for optional fields that may not always be present.
    """

    # Required fields (from Asset)
    id: UUID
    fqn: str
    owner_team_id: UUID
    environment: str
    resource_type: str
    guarantee_mode: str
    semver_mode: str
    created_at: datetime
    metadata: dict[str, object]

    # Optional enrichment fields
    owner_user_id: UUID | None
    owner_team_name: str | None
    owner_user_name: str | None
    owner_user_email: str | None
    active_contract_version: str | None


class ContractWithPublisherInfo(TypedDict, total=False):
    """Contract data enriched with publisher team/user names."""

    # Required fields (from Contract)
    id: UUID
    asset_id: UUID
    version: str
    schema_def: dict[str, object]
    schema_format: str
    compatibility_mode: str
    status: ContractStatus
    published_at: datetime
    published_by: UUID

    # Optional fields
    published_by_user_id: UUID | None
    guarantees: dict[str, object] | None

    # Enrichment fields
    published_by_team_name: str | None
    published_by_user_name: str | None


class ContractHistoryEntry(TypedDict, total=False):
    """Entry in contract history response."""

    id: str
    version: str
    status: str
    published_at: str
    published_by: str
    compatibility_mode: str
    change_type: str
    breaking_changes_count: int


class ContractHistoryResponse(TypedDict):
    """Response for contract history endpoint."""

    asset_id: str
    asset_fqn: str
    contracts: list[ContractHistoryEntry]


class SchemaDiffResponse(TypedDict):
    """Response for schema diff endpoint."""

    asset_id: str
    asset_fqn: str
    from_version: str
    to_version: str
    change_type: str
    is_compatible: bool
    breaking_changes: list[dict[str, object]]
    all_changes: list[dict[str, object]]
    compatibility_mode: str


class BulkAssignResponse(TypedDict, total=False):
    """Response for bulk asset assignment."""

    updated: int
    not_found: list[str]
    owner_user_id: str | None


class TeamSummary(TypedDict):
    """Summary of a team for nested responses."""

    id: str
    name: str


class ReassignAssetsResponse(TypedDict, total=False):
    """Response for reassigning assets between teams."""

    reassigned: int
    source_team: TeamSummary
    target_team: TeamSummary
    asset_ids: list[str]


class ImpactedConsumer(TypedDict):
    """Consumer impacted by a breaking change."""

    team_id: UUID
    team_name: str
    pinned_version: str | None


class VersionSuggestionDict(TypedDict):
    """Version suggestion as returned by API."""

    suggested_version: str
    current_version: str | None
    change_type: str
    reason: str
    is_first_contract: bool


class ContractPublishResponse(TypedDict, total=False):
    """Response from contract publishing endpoint.

    The response structure varies based on the action taken:
    - published: New contract was published
    - force_published: Breaking change was force-published
    - proposal_created: Breaking change requires consumer acknowledgment
    - version_required: Version suggestion returned (semver_mode=suggest)
    """

    action: str
    contract: dict[str, object]
    proposal: dict[str, object]
    change_type: str
    breaking_changes: list[dict[str, object]]
    message: str
    warning: str
    version_auto_generated: bool
    schema_converted_from: str
    audit_warning: str
    version_suggestion: VersionSuggestionDict


class GuaranteeFailureCount(TypedDict):
    """Count of failures for a specific guarantee."""

    guarantee_id: str
    failure_count: int


class LastRunSummary(TypedDict):
    """Summary of the most recent audit run."""

    id: str
    status: str
    run_at: str
    triggered_by: str
    guarantees_failed: int
