"""Team models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.config import settings

# Team name pattern: alphanumeric, underscores, hyphens, spaces
TEAM_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\- ]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


class TeamBase(BaseModel):
    """Base team fields."""

    name: str = Field(..., min_length=1, max_length=settings.max_team_name_length)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_and_strip_name(cls, v: str) -> str:
        """Strip whitespace and validate team name format."""
        v = v.strip()
        if not v:
            raise ValueError("Team name cannot be empty or whitespace only")
        if not TEAM_NAME_PATTERN.match(v):
            raise ValueError(
                "Team name must start and end with alphanumeric characters "
                "and contain only letters, numbers, underscores, hyphens, and spaces"
            )
        return v


class TeamCreate(TeamBase):
    """Fields for creating a team."""

    pass


class TeamUpdate(BaseModel):
    """Fields for updating a team."""

    name: str | None = Field(None, min_length=1, max_length=settings.max_team_name_length)
    metadata: dict[str, Any] | None = None


class Team(BaseModel):
    """Team entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
