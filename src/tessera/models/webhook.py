"""Webhook event models."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class WebhookEventType(StrEnum):
    """Types of webhook events."""

    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_ACKNOWLEDGED = "proposal.acknowledged"
    PROPOSAL_APPROVED = "proposal.approved"
    PROPOSAL_REJECTED = "proposal.rejected"
    PROPOSAL_FORCE_APPROVED = "proposal.force_approved"
    PROPOSAL_WITHDRAWN = "proposal.withdrawn"
    CONTRACT_PUBLISHED = "contract.published"


class ImpactedConsumer(BaseModel):
    """Consumer impacted by a breaking change."""

    team_id: UUID
    team_name: str
    pinned_version: str | None = None


class BreakingChange(BaseModel):
    """A breaking change detected in a schema."""

    change_type: str
    path: str
    message: str
    details: dict[str, object] | None = None


class ProposalCreatedPayload(BaseModel):
    """Payload for proposal.created event."""

    proposal_id: UUID
    asset_id: UUID
    asset_fqn: str
    producer_team_id: UUID
    producer_team_name: str
    proposed_version: str
    breaking_changes: list[BreakingChange]
    impacted_consumers: list[ImpactedConsumer]


class AcknowledgmentPayload(BaseModel):
    """Payload for proposal.acknowledged event."""

    proposal_id: UUID
    asset_id: UUID
    asset_fqn: str
    consumer_team_id: UUID
    consumer_team_name: str
    response: str  # approved, blocked, migrating
    migration_deadline: datetime | None = None
    notes: str | None = None
    pending_count: int
    acknowledged_count: int


class ProposalStatusPayload(BaseModel):
    """Payload for proposal status changes (approved, rejected, force_approved)."""

    proposal_id: UUID
    asset_id: UUID
    asset_fqn: str
    status: str
    actor_team_id: UUID | None = None
    actor_team_name: str | None = None


class ContractPublishedPayload(BaseModel):
    """Payload for contract.published event."""

    contract_id: UUID
    asset_id: UUID
    asset_fqn: str
    version: str
    producer_team_id: UUID
    producer_team_name: str
    from_proposal_id: UUID | None = None


class WebhookEvent(BaseModel):
    """A webhook event to be delivered."""

    event: WebhookEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: (
        ProposalCreatedPayload
        | AcknowledgmentPayload
        | ProposalStatusPayload
        | ContractPublishedPayload
    )
