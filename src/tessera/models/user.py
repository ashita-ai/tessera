"""User models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from tessera.models.enums import UserRole, UserType

# Username pattern: alphanumeric, hyphens, underscores, dots. No spaces.
USERNAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,253}[a-zA-Z0-9]$|^[a-zA-Z]$")

# Name pattern: letters, spaces, hyphens, apostrophes
NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z'\- ]*[a-zA-Z]$|^[a-zA-Z]$")


class UserBase(BaseModel):
    """Base user fields."""

    username: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    user_type: UserType = UserType.HUMAN
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("username")
    @classmethod
    def validate_and_normalize_username(cls, v: str) -> str:
        """Normalize to lowercase and validate username format."""
        v = v.strip().lower()
        if not v:
            raise ValueError("Username cannot be empty or whitespace only")
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must start with a letter, end with a letter or digit, "
                "and contain only letters, digits, hyphens, underscores, and dots"
            )
        return v

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
    password: str | None = Field(None, min_length=8, max_length=128)
    role: UserRole = UserRole.USER

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr | None) -> str | None:
        """Normalize email to lowercase and strip whitespace."""
        if v is None:
            return None
        return v.lower().strip()

    @model_validator(mode="after")
    def validate_bot_constraints(self) -> "UserCreate":
        """Bots must not have passwords; humans should not lack one."""
        if self.user_type == UserType.BOT and self.password is not None:
            raise ValueError("Bot users cannot have passwords — they authenticate via API keys")
        return self


class UserUpdate(BaseModel):
    """Fields for updating a user."""

    username: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    user_type: UserType | None = None
    team_id: UUID | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    role: UserRole | None = None
    notification_preferences: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("username")
    @classmethod
    def validate_and_normalize_username(cls, v: str | None) -> str | None:
        """Normalize to lowercase and validate username format."""
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            raise ValueError("Username cannot be empty or whitespace only")
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must start with a letter, end with a letter or digit, "
                "and contain only letters, digits, hyphens, underscores, and dots"
            )
        return v

    @model_validator(mode="after")
    def validate_bot_constraints(self) -> "UserUpdate":
        """Prevent setting a password on a bot user via update."""
        if self.user_type == UserType.BOT and self.password is not None:
            raise ValueError("Bot users cannot have passwords — they authenticate via API keys")
        return self


class User(BaseModel):
    """User entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str | None = None
    name: str
    user_type: UserType = UserType.HUMAN
    role: UserRole = UserRole.USER
    team_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    notification_preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None
    deactivated_at: datetime | None = None


class UserWithTeam(User):
    """User with team name for display."""

    team_name: str | None = None
