"""SQLAlchemy database models.

Cascade Policy
--------------
No cascade deletes are configured on any relationship. This is intentional:

- **Audit immutability**: Audit events, contracts, proposals, and acknowledgments
  must survive parent deletion to preserve the full paper trail.
- **Soft delete strategy**: Teams, assets, and users use soft delete
  (``deleted_at`` / ``deactivated_at``). Queries filter these out rather than
  destroying rows.
- **FK integrity**: PostgreSQL FK constraints prevent accidental hard deletes
  of referenced rows. Any hard delete of a parent would raise
  ``IntegrityError``, which is the desired behavior.

Audit Table Immutability
------------------------
``audit_events`` is append-only by application convention **and** by database
constraint. A partial unique index (``uq_one_pending_proposal_per_asset``)
prevents duplicate pending proposals. In production, REVOKE DELETE and UPDATE
on the ``audit_events`` table from the application role to enforce immutability
at the database level::

    REVOKE DELETE, UPDATE ON audit_events FROM tessera_app;

If a cleanup job is ever needed for truly orphaned records, it should be
implemented as a separate maintenance task with explicit audit logging.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from tessera.models.enums import (
    AcknowledgmentResponseType,
    AuditRunStatus,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    DependencySource,
    DependencyType,
    GuaranteeMode,
    InferredDependencyStatus,
    OtelBackendType,
    ProposalStatus,
    RegistrationStatus,
    ResourceType,
    SchemaFormat,
    SemverMode,
    UserRole,
    UserType,
    WebhookDeliveryStatus,
)


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class UserDB(Base):
    """User database model - humans and bots who own assets."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_type: Mapped[UserType] = mapped_column(
        Enum(UserType), default=UserType.HUMAN, nullable=False
    )
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
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    team: Mapped["TeamDB | None"] = relationship(back_populates="members")
    owned_assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_user")
    api_keys: Mapped[list["APIKeyDB"]] = relationship(back_populates="user")


class TeamDB(Base):
    """Team database model - groups of users for backup notifications."""

    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        # Only enforce name uniqueness among non-deleted teams. This allows
        # recreating a team with the same name after the original is soft-deleted.
        Index(
            "uq_team_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    # Relationships
    members: Mapped[list["UserDB"]] = relationship(back_populates="team")
    assets: Mapped[list["AssetDB"]] = relationship(back_populates="owner_team")
    repos: Mapped[list["RepoDB"]] = relationship(back_populates="owner_team")
    services: Mapped[list["ServiceDB"]] = relationship(back_populates="owner_team")


class RepoDB(Base):
    """Repository database model.

    A git repository owned by a team. Repos are the unit of git operations
    (clone, fetch, poll) and CODEOWNERS parsing. Hierarchy: Team → Repo → Service → Asset.
    """

    __tablename__ = "repos"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    git_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    spec_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    owner_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    codeowners_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ssh_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        Index(
            "uq_repo_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_repo_git_url_active",
            "git_url",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    # Relationships
    owner_team: Mapped["TeamDB"] = relationship(back_populates="repos", lazy="selectin")
    services: Mapped[list["ServiceDB"]] = relationship(back_populates="repo")


class ServiceDB(Base):
    """Service database model.

    A deployable unit within a repository. A single-service repo has one service
    with ``root_path = '/'``. A monorepo has multiple services, each with a
    distinct root path. Hierarchy: Team → Repo → Service → Asset.
    """

    __tablename__ = "services"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    repo_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("repos.id"), nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(String(500), nullable=False, default="/")
    otel_service_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        Index(
            "uq_service_name_repo_active",
            "name",
            "repo_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    # Relationships
    repo: Mapped["RepoDB"] = relationship(back_populates="services", lazy="selectin")
    owner_team: Mapped["TeamDB"] = relationship(back_populates="services", lazy="selectin")
    assets: Mapped[list["AssetDB"]] = relationship(back_populates="service")


class AssetDB(Base):
    """Asset database model."""

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fqn: Mapped[str] = mapped_column(String(1000), nullable=False)
    owner_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    service_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("services.id"), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(
        String(50), nullable=False, default="production", index=True
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType), default=ResourceType.OTHER, nullable=False, index=True
    )
    guarantee_mode: Mapped[GuaranteeMode] = mapped_column(
        Enum(GuaranteeMode), default=GuaranteeMode.NOTIFY
    )
    semver_mode: Mapped[SemverMode] = mapped_column(Enum(SemverMode), default=SemverMode.AUTO)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("fqn", "environment", name="uq_asset_fqn_environment"),
        # Composite indexes for common soft-delete filtered queries
        Index("idx_asset_team_active", "owner_team_id", "deleted_at"),
        Index("idx_asset_env_active", "environment", "deleted_at"),
    )

    # Relationships
    # Use selectin for owner_team since it's often needed for auth checks
    owner_team: Mapped["TeamDB"] = relationship(back_populates="assets", lazy="selectin")
    owner_user: Mapped["UserDB | None"] = relationship(back_populates="owned_assets")
    service: Mapped["ServiceDB | None"] = relationship(back_populates="assets")
    # Contracts and proposals use default lazy loading - use explicit options() when needed
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
    schema_format: Mapped[SchemaFormat] = mapped_column(
        Enum(SchemaFormat, values_callable=lambda x: [e.value for e in x]),
        default=SchemaFormat.JSON_SCHEMA,
        nullable=False,
    )
    compatibility_mode: Mapped[CompatibilityMode] = mapped_column(
        Enum(CompatibilityMode), default=CompatibilityMode.BACKWARD
    )
    guarantees: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    field_descriptions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    field_tags: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.ACTIVE, index=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    published_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False
    )  # Team ID
    published_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )  # Individual who published
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    # Composite index for finding active contracts by asset (common query pattern)
    __table_args__ = (
        Index("idx_contract_asset_status", "asset_id", "status"),
        UniqueConstraint("asset_id", "version", name="uq_contracts_asset_version"),
    )

    # Relationships
    # Use selectin for asset since contract details often need asset info
    asset: Mapped["AssetDB"] = relationship(back_populates="contracts", lazy="selectin")
    # Registrations use default lazy - use explicit options() for impact analysis
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
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "contract_id", "consumer_team_id", name="uq_registration_contract_consumer"
        ),
        # Composite index for counting active consumers per contract
        Index("idx_registration_contract_active", "contract_id", "deleted_at"),
        Index("idx_registration_team_active", "consumer_team_id", "deleted_at"),
    )

    # Relationships
    contract: Mapped["ContractDB"] = relationship(back_populates="registrations")
    consumer_team: Mapped["TeamDB"] = relationship(lazy="raise", foreign_keys=[consumer_team_id])


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
    proposed_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False
    )  # Team ID
    proposed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )  # Individual who proposed
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    auto_expire: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    # Affected parties discovered via lineage (not registered consumers)
    # Teams owning downstream assets that will be affected by this change
    affected_teams: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Downstream assets that depend on this asset and will be affected
    affected_assets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Objections filed by affected teams (non-blocking but visible)
    objections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    __table_args__ = (
        # Composite index for finding pending proposals by asset (common query pattern)
        Index("idx_proposal_asset_status", "asset_id", "status"),
        # Prevent duplicate pending proposals for the same asset. Without this,
        # two concurrent breaking-change publishes can both see "no pending proposal"
        # (FOR UPDATE acquires no lock when no row exists) and both create one.
        # Uses dialect-specific WHERE clauses so it works on both PostgreSQL and SQLite.
        Index(
            "uq_one_pending_proposal_per_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

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

    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "consumer_team_id", name="uq_acknowledgment_proposal_consumer"
        ),
    )

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
    source: Mapped[DependencySource] = mapped_column(
        Enum(DependencySource), nullable=False, default=DependencySource.MANUAL, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    otel_config_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("otel_sync_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    dependent_asset: Mapped["AssetDB"] = relationship(
        lazy="raise", foreign_keys=[dependent_asset_id]
    )
    dependency_asset: Mapped["AssetDB"] = relationship(
        lazy="raise", foreign_keys=[dependency_asset_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "dependent_asset_id",
            "dependency_asset_id",
            "dependency_type",
            "source",
            name="uq_dependency_edge",
        ),
        # Composite index for impact analysis: "what depends on this asset?"
        Index("idx_dependency_target_active", "dependency_asset_id", "deleted_at"),
        Index("idx_dependency_source", "source"),
    )


class AuditEventDB(Base):
    """Audit event database model (append-only).

    This table must be treated as immutable. Rows are never updated or deleted.
    In production, enforce this at the database level::

        REVOKE DELETE, UPDATE ON audit_events FROM tessera_app;

    No ``updated_at`` column exists by design — these records never change.
    """

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="human"
    )  # "human" or "agent"
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_events_entity_type_occurred_at", "entity_type", "occurred_at"),
    )


class APIKeyDB(Base):
    """API key database model."""

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # argon2 hashes are ~100 chars
    key_prefix: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # indexed for prefix-based lookup
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    agent_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Non-null → agent key
    agent_framework: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g., "claude-code", "langchain"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_agent(self) -> bool:
        """A key is an agent key when agent_name is set."""
        return self.agent_name is not None

    # Relationships
    team: Mapped["TeamDB"] = relationship()
    user: Mapped["UserDB | None"] = relationship(back_populates="api_keys")


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
    """Audit run tracking for contract guarantee verification.

    Records the results of quality checks (test suites, monitoring probes, etc.)
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
    )  # "test_suite", "monitoring_probe", "ci_pipeline", "manual"
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


class SlackConfigDB(Base):
    """Per-team Slack notification configuration.

    Each team can configure one Slack channel per (team, channel_id) pair
    with either an incoming webhook URL or a bot token for delivery.
    The ``notify_on`` column stores a JSON array of event type strings
    that this config should receive.
    """

    __tablename__ = "slack_configs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("teams.id"), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bot_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notify_on: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["proposal.created", "proposal.resolved", "force.publish"],
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("team_id", "channel_id", name="uq_slack_configs_team_channel"),
    )

    # Relationships
    team: Mapped["TeamDB"] = relationship(lazy="selectin")


class InferredDependencyDB(Base):
    """Inferred dependency discovered by mining audit signals.

    Rows are never hard-deleted. Rejected inferences keep status=REJECTED so
    future scans can skip the same (asset, team, source) tuple.
    """

    __tablename__ = "inferred_dependencies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType), default=DependencyType.CONSUMES
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[InferredDependencyStatus] = mapped_column(
        Enum(InferredDependencyStatus),
        default=InferredDependencyStatus.PENDING,
        index=True,
    )
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    promoted_registration_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("registrations.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "consumer_team_id",
            "source",
            name="uq_inferred_dep_asset_team_source",
        ),
    )


class OtelSyncConfigDB(Base):
    """Configuration for an OTEL trace backend used for dependency discovery.

    Each row represents a connection to an observability backend (Jaeger, Tempo,
    Datadog) that Tessera queries periodically to discover service-to-service
    dependency edges from trace data.
    """

    __tablename__ = "otel_sync_configs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    backend_type: Mapped[OtelBackendType] = mapped_column(Enum(OtelBackendType), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lookback_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    min_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    dependencies: Mapped[list["AssetDependencyDB"]] = relationship(
        lazy="raise", foreign_keys="AssetDependencyDB.otel_config_id"
    )

    __table_args__ = (
        Index(
            "uq_otel_config_name",
            "name",
            unique=True,
        ),
    )


class SyncEventDB(Base):
    """Record of a single repo sync execution.

    Tracks the outcome (success/failure), metrics (specs found, contracts
    published, etc.), and timing for each sync — whether triggered by the
    background worker or manually via the API.
    """

    __tablename__ = "sync_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    repo_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("repos.id"), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    specs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contracts_published: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposals_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    services_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assets_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assets_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False, default="worker")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_sync_events_repo_created", "repo_id", "created_at"),)

    # Relationships
    repo: Mapped["RepoDB"] = relationship(lazy="selectin")
