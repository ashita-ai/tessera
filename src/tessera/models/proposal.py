"""Proposal models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.models.enums import ChangeType, ProposalStatus


class BreakingChange(BaseModel):
    """A specific breaking change in a proposal."""

    type: str = Field(..., description="Type of change (e.g., 'dropped_column', 'type_change')")
    column: str | None = None
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)


class AffectedAsset(BaseModel):
    """An asset affected by a proposal via lineage."""

    asset_id: str = Field(..., description="ID of the affected downstream asset")
    asset_fqn: str = Field(..., description="FQN of the affected downstream asset")
    owner_team_id: str = Field(..., description="Team ID that owns this asset")
    owner_team_name: str | None = Field(None, description="Team name that owns this asset")
    owner_user_id: str | None = Field(None, description="Individual user ID that owns this asset")
    owner_user_name: str | None = Field(
        None, description="Individual user name that owns this asset"
    )


class AffectedTeam(BaseModel):
    """A team affected by a proposal via lineage (owning downstream assets)."""

    team_id: str = Field(..., description="ID of the affected team")
    team_name: str = Field(..., description="Name of the affected team")
    assets: list[str] = Field(
        default_factory=list, description="Asset IDs owned by this team that are affected"
    )


class Objection(BaseModel):
    """An objection filed by an affected team."""

    team_id: str = Field(..., description="ID of the team that objected")
    team_name: str = Field(..., description="Name of the team that objected")
    reason: str = Field(..., description="Reason for the objection")
    objected_at: datetime = Field(..., description="When the objection was filed")
    objected_by_user_id: str | None = Field(None, description="User ID who filed the objection")
    objected_by_user_name: str | None = Field(None, description="User name who filed the objection")


class ObjectionCreate(BaseModel):
    """Request body for filing an objection to a proposal."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Reason for objecting to this proposal",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Strip whitespace and validate reason."""
        v = v.strip()
        if not v:
            raise ValueError("Reason cannot be empty or whitespace only")
        return v


class ProposalBase(BaseModel):
    """Base proposal fields."""

    proposed_schema: dict[str, object] = Field(..., description="Proposed JSON Schema")


class ProposalCreate(ProposalBase):
    """Fields for creating a proposal."""

    pass


class Proposal(ProposalBase):
    """Proposal entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    change_type: ChangeType
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    proposed_by: UUID
    proposed_by_user_id: UUID | None = None
    proposed_at: datetime
    resolved_at: datetime | None = None
    expires_at: datetime | None = None
    auto_expire: bool = False

    # Affected parties discovered via lineage (not registered consumers)
    affected_teams: list[AffectedTeam] = Field(
        default_factory=list,
        description="Teams owning downstream assets affected by this change",
    )
    affected_assets: list[AffectedAsset] = Field(
        default_factory=list,
        description="Downstream assets that depend on this asset",
    )
    objections: list[Objection] = Field(
        default_factory=list,
        description="Objections filed by affected teams (non-blocking)",
    )
    has_objections: bool = Field(
        default=False,
        description="True if any affected teams have objected",
    )

    def model_post_init(self, __context: object) -> None:
        """Compute has_objections from objections list."""
        object.__setattr__(self, "has_objections", len(self.objections) > 0)
