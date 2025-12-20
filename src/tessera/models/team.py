"""Team models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TeamBase(BaseModel):
    """Base team fields."""

    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeamCreate(TeamBase):
    """Fields for creating a team."""

    pass


class TeamUpdate(BaseModel):
    """Fields for updating a team."""

    name: str | None = Field(None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None


class Team(TeamBase):
    """Team entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
