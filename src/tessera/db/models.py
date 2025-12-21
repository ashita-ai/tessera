"""SQLAlchemy database models."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tessera.models.enums import (
    AcknowledgmentResponseType,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    DependencyType,
    ProposalStatus,
    RegistrationStatus,
)


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class TeamDB(Base):
    """Team database model."""

    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_team")


class AssetDB(Base):
    """Asset database model."""

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fqn: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    owner_team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    owner_team: Mapped["TeamDB"] = relationship(back_populates="assets")
    contracts: Mapped[list["ContractDB"]] = relationship(back_populates="asset")
    proposals: Mapped[list["ProposalDB"]] = relationship(back_populates="asset")


class ContractDB(Base):
    """Contract database model."""

    __tablename__ = "contracts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_def: Mapped[dict[str, Any]] = mapped_column("schema", JSON, nullable=False)
    compatibility_mode: Mapped[CompatibilityMode] = mapped_column(
        Enum(CompatibilityMode), default=CompatibilityMode.BACKWARD
    )
    guarantees: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.ACTIVE
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    published_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="contracts")
    registrations: Mapped[list["RegistrationDB"]] = relationship(back_populates="contract")


class RegistrationDB(Base):
    """Registration database model."""

    __tablename__ = "registrations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    contract_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("contracts.id"), nullable=False, index=True
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    pinned_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus), default=RegistrationStatus.ACTIVE
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    contract: Mapped["ContractDB"] = relationship(back_populates="registrations")


class ProposalDB(Base):
    """Proposal database model."""

    __tablename__ = "proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    proposed_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(Enum(ChangeType), nullable=False)
    breaking_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.PENDING
    )
    proposed_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="proposals")
    acknowledgments: Mapped[list["AcknowledgmentDB"]] = relationship(back_populates="proposal")


class AcknowledgmentDB(Base):
    """Acknowledgment database model."""

    __tablename__ = "acknowledgments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("proposals.id"), nullable=False)
    consumer_team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False)
    response: Mapped[AcknowledgmentResponseType] = mapped_column(
        Enum(AcknowledgmentResponseType), nullable=False
    )
    migration_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    proposal: Mapped["ProposalDB"] = relationship(back_populates="acknowledgments")


class AssetDependencyDB(Base):
    """Asset-to-asset dependency for upstream lineage tracking."""

    __tablename__ = "dependencies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dependent_asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    dependency_asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType), default=DependencyType.CONSUMES
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEventDB(Base):
    """Audit event database model (append-only)."""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class APIKeyDB(Base):
    """API key database model."""

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # argon2 hashes are ~100 chars
    key_prefix: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # indexed for prefix-based lookup
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    team: Mapped["TeamDB"] = relationship()
