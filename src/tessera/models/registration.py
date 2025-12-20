"""Registration models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tessera.models.enums import RegistrationStatus


class RegistrationBase(BaseModel):
    """Base registration fields."""

    pinned_version: str | None = Field(
        None,
        pattern=r"^\d+\.\d+\.\d+$",
        description="Pinned version (null = track latest compatible)",
    )


class RegistrationCreate(RegistrationBase):
    """Fields for creating a registration."""

    consumer_team_id: UUID


class RegistrationUpdate(BaseModel):
    """Fields for updating a registration."""

    pinned_version: str | None = None
    status: RegistrationStatus | None = None


class Registration(RegistrationBase):
    """Registration entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    consumer_team_id: UUID
    status: RegistrationStatus = RegistrationStatus.ACTIVE
    registered_at: datetime
    acknowledged_at: datetime | None = None
