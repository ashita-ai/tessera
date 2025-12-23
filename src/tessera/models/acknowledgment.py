"""Acknowledgment models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tessera.models.enums import AcknowledgmentResponseType


class AcknowledgmentBase(BaseModel):
    """Base acknowledgment fields."""

    response: AcknowledgmentResponseType
    migration_deadline: datetime | None = None
    notes: str | None = Field(None, max_length=2000)


class AcknowledgmentCreate(AcknowledgmentBase):
    """Fields for creating an acknowledgment."""

    consumer_team_id: UUID
    acknowledged_by_user_id: UUID | None = None


class AcknowledgmentResponse(AcknowledgmentBase):
    """Response model for acknowledgment (used in API responses)."""

    pass


class Acknowledgment(AcknowledgmentBase):
    """Acknowledgment entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proposal_id: UUID
    consumer_team_id: UUID
    acknowledged_by_user_id: UUID | None = None
    responded_at: datetime
