"""User models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from tessera.models.enums import UserRole

# Name pattern: letters, spaces, hyphens, apostrophes
NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z'\- ]*[a-zA-Z]$|^[a-zA-Z]$")


class UserBase(BaseModel):
    """Base user fields."""

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_and_strip_name(cls, v: str) -> str:
        """Strip whitespace and validate name format."""
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty or whitespace only")
        if not NAME_PATTERN.match(v):
            raise ValueError(
                "Name must start and end with letters "
                "and contain only letters, spaces, hyphens, and apostrophes"
            )
        return v


class UserCreate(UserBase):
    """Fields for creating a user."""

    team_id: UUID | None = None
    password: str | None = Field(None, min_length=4, max_length=128)
    role: UserRole = UserRole.USER


class UserUpdate(BaseModel):
    """Fields for updating a user."""

    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    team_id: UUID | None = None
    password: str | None = Field(None, min_length=4, max_length=128)
    role: UserRole | None = None
    notification_preferences: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class User(BaseModel):
    """User entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    role: UserRole = UserRole.USER
    team_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    notification_preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    deactivated_at: datetime | None = None


class UserWithTeam(User):
    """User with team name for display."""

    team_name: str | None = None
