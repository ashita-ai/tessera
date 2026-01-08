"""API key models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.models.enums import APIKeyScope


class APIKeyCreate(BaseModel):
    """Request model for creating an API key."""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Human-readable name for the key"
    )
    team_id: UUID = Field(..., description="Team this key belongs to")
    scopes: list[APIKeyScope] = Field(
        default=[APIKeyScope.READ, APIKeyScope.WRITE],
        description="Permission scopes for this key",
    )
    expires_at: datetime | None = Field(None, description="Optional expiration time")

    @field_validator("name")
    @classmethod
    def validate_and_strip_name(cls, v: str) -> str:
        """Strip whitespace and validate API key name."""
        v = v.strip()
        if not v:
            raise ValueError("API key name cannot be empty or whitespace only")
        return v


class APIKeyCreated(BaseModel):
    """Response model when an API key is created (includes the raw key)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str = Field(..., description="The API key (only shown once)")
    key_prefix: str = Field(..., description="Key prefix for identification")
    name: str
    team_id: UUID
    scopes: list[APIKeyScope]
    created_at: datetime
    expires_at: datetime | None = None


class APIKey(BaseModel):
    """API key entity (without the raw key)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_prefix: str
    name: str
    team_id: UUID
    scopes: list[APIKeyScope]
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Check if the key is active (not revoked and not expired)."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            return datetime.now(self.expires_at.tzinfo) < self.expires_at
        return True


class APIKeyList(BaseModel):
    """Response model for listing API keys."""

    keys: list[APIKey]
