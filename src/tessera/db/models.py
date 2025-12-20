"""SQLAlchemy database models."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
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


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class TeamDB(Base):
    """Team database model."""

    __tablename__ = "teams"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_team")


class AssetDB(Base):
    """Asset database model."""

    __tablename__ = "assets"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fqn: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    owner_team_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.teams.id"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    owner_team: Mapped["TeamDB"] = relationship(back_populates="assets")
    contracts: Mapped[list["ContractDB"]] = relationship(back_populates="asset")
    proposals: Mapped[list["ProposalDB"]] = relationship(back_populates="asset")


class ContractDB(Base):
    """Contract database model."""

    __tablename__ = "contracts"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.assets.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_def: Mapped[dict] = mapped_column("schema", JSON, nullable=False)
    compatibility_mode: Mapped[CompatibilityMode] = mapped_column(
        Enum(CompatibilityMode), default=CompatibilityMode.BACKWARD
    )
    guarantees: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.ACTIVE
    )
    published_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="contracts")
    registrations: Mapped[list["RegistrationDB"]] = relationship(back_populates="contract")


class RegistrationDB(Base):
    """Registration database model."""

    __tablename__ = "registrations"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    contract_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.contracts.id"), nullable=False
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.teams.id"), nullable=False
    )
    pinned_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus), default=RegistrationStatus.ACTIVE
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    contract: Mapped["ContractDB"] = relationship(back_populates="registrations")


class ProposalDB(Base):
    """Proposal database model."""

    __tablename__ = "proposals"
    __table_args__ = {"schema": "workflow"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.assets.id"), nullable=False
    )
    proposed_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(Enum(ChangeType), nullable=False)
    breaking_changes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.PENDING
    )
    proposed_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="proposals")
    acknowledgments: Mapped[list["AcknowledgmentDB"]] = relationship(back_populates="proposal")


class AcknowledgmentDB(Base):
    """Acknowledgment database model."""

    __tablename__ = "acknowledgments"
    __table_args__ = {"schema": "workflow"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow.proposals.id"), nullable=False
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.teams.id"), nullable=False
    )
    response: Mapped[AcknowledgmentResponseType] = mapped_column(
        Enum(AcknowledgmentResponseType), nullable=False
    )
    migration_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    proposal: Mapped["ProposalDB"] = relationship(back_populates="acknowledgments")


class AssetDependencyDB(Base):
    """Asset-to-asset dependency for upstream lineage tracking."""

    __tablename__ = "dependencies"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dependent_asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.assets.id"), nullable=False
    )
    dependency_asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.assets.id"), nullable=False
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType), default=DependencyType.CONSUMES
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEventDB(Base):
    """Audit event database model (append-only)."""

    __tablename__ = "events"
    __table_args__ = {"schema": "audit"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
