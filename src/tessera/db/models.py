"""SQLAlchemy database models."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tessera.models.enums import (
    AcknowledgmentResponseType,
    AuditRunStatus,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    DependencyType,
    GuaranteeMode,
    ProposalStatus,
    RegistrationStatus,
    ResourceType,
    UserRole,
    WebhookDeliveryStatus,
)


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class UserDB(Base):
    """User database model - individual people who own assets."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    team_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=True, index=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    team: Mapped["TeamDB | None"] = relationship(back_populates="members")
    owned_assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_user")


class TeamDB(Base):
    """Team database model - groups of users for backup notifications."""

    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    members: Mapped[list["UserDB"]] = relationship(back_populates="team")
    assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_team")


class AssetDB(Base):
    """Asset database model."""

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fqn: Mapped[str] = mapped_column(String(1000), nullable=False)
    owner_team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(
        String(50), nullable=False, default="production", index=True
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType), default=ResourceType.UNKNOWN, nullable=False, index=True
    )
    guarantee_mode: Mapped[GuaranteeMode] = mapped_column(
        Enum(GuaranteeMode), default=GuaranteeMode.NOTIFY
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (UniqueConstraint("fqn", "environment", name="uq_asset_fqn_environment"),)

    # Relationships
    owner_team: Mapped["TeamDB"] = relationship(back_populates="assets")
    owner_user: Mapped["UserDB | None"] = relationship(back_populates="owned_assets")
    contracts: Mapped[list["ContractDB"]] = relationship(back_populates="asset")
    proposals: Mapped[list["ProposalDB"]] = relationship(back_populates="asset")


class ContractDB(Base):
    """Contract database model."""

    __tablename__ = "contracts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_def: Mapped[dict[str, Any]] = mapped_column("schema", JSON, nullable=False)
    compatibility_mode: Mapped[CompatibilityMode] = mapped_column(
        Enum(CompatibilityMode), default=CompatibilityMode.BACKWARD
    )
    guarantees: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.ACTIVE, index=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    published_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)  # Team ID
    published_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )  # Individual who published

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="contracts")
    registrations: Mapped[list["RegistrationDB"]] = relationship(back_populates="contract")
    published_by_user: Mapped["UserDB | None"] = relationship()


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
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    proposed_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_guarantees: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    change_type: Mapped[ChangeType] = mapped_column(Enum(ChangeType), nullable=False)
    breaking_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    guarantee_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.PENDING, index=True
    )
    proposed_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)  # Team ID
    proposed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )  # Individual who proposed
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    asset: Mapped["AssetDB"] = relationship(back_populates="proposals")
    acknowledgments: Mapped[list["AcknowledgmentDB"]] = relationship(back_populates="proposal")
    proposed_by_user: Mapped["UserDB | None"] = relationship()


class AcknowledgmentDB(Base):
    """Acknowledgment database model."""

    __tablename__ = "acknowledgments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("proposals.id"), nullable=False, index=True
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )  # Individual who acknowledged
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
    acknowledged_by_user: Mapped["UserDB | None"] = relationship()


class AssetDependencyDB(Base):
    """Asset-to-asset dependency for upstream lineage tracking."""

    __tablename__ = "dependencies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dependent_asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    dependency_asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType), default=DependencyType.CONSUMES
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEventDB(Base):
    """Audit event database model (append-only)."""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
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


class WebhookDeliveryDB(Base):
    """Webhook delivery tracking for reliability and debugging."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        Enum(WebhookDeliveryStatus), default=WebhookDeliveryStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRunDB(Base):
    """Audit run tracking for WAP (Write-Audit-Publish) integration.

    Records the results of data quality checks (dbt tests, Great Expectations, etc.)
    against contract guarantees. Enables runtime enforcement tracking.
    """

    __tablename__ = "audit_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    contract_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("contracts.id"), nullable=True, index=True
    )
    status: Mapped[AuditRunStatus] = mapped_column(Enum(AuditRunStatus), nullable=False, index=True)
    guarantees_checked: Mapped[int] = mapped_column(Integer, default=0)
    guarantees_passed: Mapped[int] = mapped_column(Integer, default=0)
    guarantees_failed: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # "dbt_test", "great_expectations", "soda", "manual"
    run_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )  # External run ID for correlation (e.g., dbt invocation_id)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )  # Failed test details, error messages
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    # Relationships
    asset: Mapped["AssetDB"] = relationship()
    contract: Mapped["ContractDB | None"] = relationship()
