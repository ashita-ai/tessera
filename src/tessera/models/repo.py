"""Repo models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepoCreate(BaseModel):
    """Fields for registering a repository."""

    name: str = Field(..., min_length=1, max_length=200)
    git_url: str = Field(..., min_length=1, max_length=500)
    owner_team_id: UUID
    default_branch: str = Field("main", min_length=1, max_length=100)
    spec_paths: list[str] = Field(default_factory=list)
    codeowners_path: str | None = Field(None, max_length=200)
    sync_enabled: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Strip whitespace from name."""
        v = v.strip()
        if not v:
            raise ValueError("Repo name cannot be empty or whitespace only")
        return v

    @field_validator("git_url")
    @classmethod
    def strip_git_url(cls, v: str) -> str:
        """Strip whitespace from git URL."""
        v = v.strip()
        if not v:
            raise ValueError("Git URL cannot be empty or whitespace only")
        return v


class RepoUpdate(BaseModel):
    """Fields for updating a repository (mutable fields only)."""

    default_branch: str | None = Field(None, min_length=1, max_length=100)
    spec_paths: list[str] | None = None
    codeowners_path: str | None = Field(None, max_length=200)
    sync_enabled: bool | None = None


class Repo(BaseModel):
    """Repo response entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    git_url: str
    default_branch: str
    spec_paths: list[str]
    owner_team_id: UUID
    sync_enabled: bool
    codeowners_path: str | None = None
    last_synced_at: datetime | None = None
    last_synced_commit: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
