"""Repo models."""

import re
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# Branch names must match git's ref format rules (no .., no leading -,
# alphanumeric plus . / _ -)
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/ -]*$")


class RepoCreate(BaseModel):
    """Fields for registering a repository."""

    name: str = Field(..., min_length=1, max_length=200)
    git_url: str = Field(..., min_length=1, max_length=500)
    owner_team_id: UUID
    default_branch: str = Field("main", min_length=1, max_length=100)
    spec_paths: list[str] = Field(default_factory=list)
    codeowners_path: str | None = Field(None, max_length=200)
    sync_enabled: bool = True
    git_token: str | None = Field(None, max_length=500)
    ssh_key: str | None = None

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
    def validate_git_url(cls, v: str) -> str:
        """Validate git URL format and strip whitespace."""
        v = v.strip()
        if not v:
            raise ValueError("Git URL cannot be empty or whitespace only")
        if not (v.startswith("https://") or v.startswith("git@")):
            raise ValueError("Git URL must start with 'https://' or 'git@'")
        return v

    @field_validator("default_branch")
    @classmethod
    def validate_default_branch(cls, v: str) -> str:
        """Validate branch name to prevent git argument injection."""
        v = v.strip()
        if not v:
            raise ValueError("Branch name cannot be empty")
        if not _BRANCH_RE.match(v):
            raise ValueError(
                "Branch name must start with an alphanumeric character "
                "and contain only alphanumeric characters, '.', '/', '_', or '-'"
            )
        if ".." in v:
            raise ValueError("Branch name must not contain '..'")
        return v

    @field_validator("spec_paths")
    @classmethod
    def validate_spec_paths(cls, v: list[str]) -> list[str]:
        """Reject spec_paths containing path traversal components."""
        for path in v:
            parts = PurePosixPath(path).parts
            if ".." in parts:
                raise ValueError(f"spec_paths must not contain '..' components: {path!r}")
        return v


class RepoUpdate(BaseModel):
    """Fields for updating a repository (mutable fields only)."""

    default_branch: str | None = Field(None, min_length=1, max_length=100)
    spec_paths: list[str] | None = None
    codeowners_path: str | None = Field(None, max_length=200)
    sync_enabled: bool | None = None
    git_token: str | None = Field(None, max_length=500)
    ssh_key: str | None = None

    @field_validator("default_branch")
    @classmethod
    def validate_default_branch(cls, v: str | None) -> str | None:
        """Validate branch name to prevent git argument injection."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Branch name cannot be empty")
        if not _BRANCH_RE.match(v):
            raise ValueError(
                "Branch name must start with an alphanumeric character "
                "and contain only alphanumeric characters, '.', '/', '_', or '-'"
            )
        if ".." in v:
            raise ValueError("Branch name must not contain '..'")
        return v

    @field_validator("spec_paths")
    @classmethod
    def validate_spec_paths(cls, v: list[str] | None) -> list[str] | None:
        """Reject spec_paths containing path traversal components."""
        if v is None:
            return v
        for path in v:
            parts = PurePosixPath(path).parts
            if ".." in parts:
                raise ValueError(f"spec_paths must not contain '..' components: {path!r}")
        return v


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
    # Never expose plaintext credentials — only report whether they are set.
    git_token: str | None = Field(None, exclude=True)
    ssh_key: str | None = Field(None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_git_token(self) -> bool:
        """Whether a per-repo git token is configured."""
        return self.git_token is not None and len(self.git_token) > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_ssh_key(self) -> bool:
        """Whether a per-repo SSH deploy key is configured."""
        return self.ssh_key is not None and len(self.ssh_key) > 0


class SyncEvent(BaseModel):
    """Sync event response entity — one record per sync execution."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repo_id: UUID
    success: bool
    commit_sha: str | None = None
    specs_found: int = 0
    contracts_published: int = 0
    proposals_created: int = 0
    services_created: int = 0
    assets_created: int = 0
    assets_updated: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
    triggered_by: str = "worker"
    created_at: datetime
