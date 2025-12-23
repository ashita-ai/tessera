"""Proposal models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tessera.models.enums import ChangeType, ProposalStatus


class BreakingChange(BaseModel):
    """A specific breaking change in a proposal."""

    type: str = Field(..., description="Type of change (e.g., 'dropped_column', 'type_change')")
    column: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ProposalBase(BaseModel):
    """Base proposal fields."""

    proposed_schema: dict[str, Any] = Field(..., description="Proposed JSON Schema")


class ProposalCreate(ProposalBase):
    """Fields for creating a proposal."""

    pass


class Proposal(ProposalBase):
    """Proposal entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    change_type: ChangeType
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    proposed_by: UUID
    proposed_by_user_id: UUID | None = None
    proposed_at: datetime
    resolved_at: datetime | None = None
