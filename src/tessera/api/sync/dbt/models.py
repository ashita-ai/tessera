"""Pydantic request/response models for dbt sync endpoints."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DbtManifestRequest(BaseModel):
    """Request body for dbt manifest impact check."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    owner_team_id: UUID = Field(..., description="Team ID to use for new assets")


class DbtManifestUploadRequest(BaseModel):
    """Request body for uploading a dbt manifest with conflict handling."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    owner_team_id: UUID | None = Field(
        None,
        description="Default team ID. Overridden by meta.tessera.owner_team.",
    )
    conflict_mode: str = Field(
        default="ignore",
        description="'overwrite', 'ignore', or 'fail' on conflict",
    )
    auto_publish_contracts: bool = Field(
        default=False,
        description="Automatically publish initial contracts for new assets with column schemas",
    )
    auto_delete: bool = Field(
        default=False,
        description="Soft-delete dbt-managed assets missing from manifest (i.e. removed models)",
    )
    auto_create_proposals: bool = Field(
        default=False,
        description="Auto-create proposals for breaking schema changes on existing contracts",
    )
    auto_register_consumers: bool = Field(
        default=False,
        description="Register consumers from meta.tessera.consumers and refs",
    )
    infer_consumers_from_refs: bool = Field(
        default=True,
        description="Infer consumer relationships from dbt ref() dependencies (depends_on)",
    )


class DbtImpactResult(BaseModel):
    """Impact analysis result for a single dbt model."""

    fqn: str
    node_id: str
    has_contract: bool
    safe_to_publish: bool
    change_type: str | None = None
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class DbtImpactResponse(BaseModel):
    """Response from dbt manifest impact analysis."""

    status: str
    total_models: int
    models_with_contracts: int
    breaking_changes_count: int
    results: list[DbtImpactResult]


class DbtDiffItem(BaseModel):
    """A single change detected in dbt manifest."""

    fqn: str
    node_id: str
    change_type: str  # 'new', 'modified', 'deleted', 'unchanged'
    owner_team: str | None = None
    consumers_declared: int = 0
    consumers_from_refs: int = 0
    has_schema: bool = False
    schema_change_type: str | None = None  # 'none', 'compatible', 'breaking'
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class DbtDiffResponse(BaseModel):
    """Response from dbt manifest diff (CI preview)."""

    status: str  # 'clean', 'changes_detected', 'breaking_changes_detected'
    summary: dict[str, int]  # {'new': N, 'modified': M, 'deleted': D, 'breaking': B}
    blocking: bool  # True if CI should fail
    models: list[DbtDiffItem]
    warnings: list[str] = Field(default_factory=list)
    meta_errors: list[str] = Field(default_factory=list)  # Missing teams, etc.


class DbtDiffRequest(BaseModel):
    """Request body for dbt manifest diff (CI preview)."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    fail_on_breaking: bool = Field(
        default=True,
        description="Return blocking=true if any breaking changes are detected",
    )
