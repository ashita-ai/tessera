"""Initial schema — all tables, columns, indexes, and constraints.

Revision ID: 001
Revises:
Create Date: 2026-04-05

This is a squashed migration that replaces the original 001–027 chain.
It creates every table to match ``src/tessera/db/models.py`` exactly.
All tables live in the ``public`` schema (no core/workflow/audit namespaces).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


# ---------------------------------------------------------------------------
# Enum value lists — must match tessera.models.enums exactly.
# ---------------------------------------------------------------------------
_COMPATIBILITY_MODE = ("backward", "forward", "full", "none")
_CONTRACT_STATUS = ("active", "deprecated", "retired")
_REGISTRATION_STATUS = ("active", "migrating", "inactive")
_CHANGE_TYPE = ("patch", "minor", "major")
_PROPOSAL_STATUS = ("pending", "approved", "published", "rejected", "withdrawn", "expired")
_ACK_RESPONSE = ("approved", "blocked", "migrating")
_DEPENDENCY_TYPE = ("consumes", "references", "transforms")
_GUARANTEE_MODE = ("notify", "strict", "ignore")
_SEMVER_MODE = ("auto", "suggest", "enforce")
_RESOURCE_TYPE = (
    "api_endpoint",
    "graphql_query",
    "grpc_service",
    "model",
    "source",
    "seed",
    "snapshot",
    "other",
)
_SCHEMA_FORMAT = ("json_schema", "avro")
_USER_ROLE = ("admin", "team_admin", "user")
_USER_TYPE = ("human", "bot")
_WEBHOOK_STATUS = ("pending", "delivered", "failed", "dead_lettered")
_AUDIT_RUN_STATUS = ("passed", "failed", "partial")
_DEPENDENCY_SOURCE = ("manual", "otel", "inferred")
_INFERRED_DEP_STATUS = ("pending", "confirmed", "rejected", "expired")
_OTEL_BACKEND = ("jaeger", "tempo", "datadog")


def upgrade() -> None:
    """Create all tables, indexes, and constraints."""

    # ── 1. teams ──────────────────────────────────────────────────────────
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_teams_deleted_at", "teams", ["deleted_at"])
    op.create_index(
        "uq_team_name_active",
        "teams",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    # ── 2. users ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "user_type",
            sa.Enum(*_USER_TYPE, name="usertype"),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column(
            "role",
            sa.Enum(*_USER_ROLE, name="userrole"),
            nullable=False,
        ),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("notification_preferences", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_team_id", "users", ["team_id"])
    op.create_index("ix_users_deactivated_at", "users", ["deactivated_at"])

    # ── 3. repos ──────────────────────────────────────────────────────────
    op.create_table(
        "repos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("git_url", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(100), nullable=False),
        sa.Column("spec_paths", sa.JSON(), nullable=False),
        sa.Column("owner_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("codeowners_path", sa.String(200), nullable=True),
        sa.Column("git_token", sa.String(500), nullable=True),
        sa.Column("ssh_key", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_commit", sa.String(40), nullable=True),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_repos_owner_team_id", "repos", ["owner_team_id"])
    op.create_index("ix_repos_deleted_at", "repos", ["deleted_at"])
    op.create_index(
        "uq_repo_name_active",
        "repos",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_repo_git_url_active",
        "repos",
        ["git_url"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    # ── 4. services ───────────────────────────────────────────────────────
    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("repo_id", sa.Uuid(), sa.ForeignKey("repos.id"), nullable=False),
        sa.Column("root_path", sa.String(500), nullable=False),
        sa.Column("otel_service_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_services_repo_id", "services", ["repo_id"])
    op.create_index("ix_services_deleted_at", "services", ["deleted_at"])
    op.create_index(
        "uq_service_name_repo_active",
        "services",
        ["name", "repo_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    # ── 5. assets ─────────────────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fqn", sa.String(1000), nullable=False),
        sa.Column("owner_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("services.id"), nullable=True),
        sa.Column("environment", sa.String(50), nullable=False),
        sa.Column(
            "resource_type",
            sa.Enum(*_RESOURCE_TYPE, name="resourcetype"),
            nullable=False,
        ),
        sa.Column(
            "guarantee_mode",
            sa.Enum(*_GUARANTEE_MODE, name="guaranteemode"),
            nullable=False,
        ),
        sa.Column(
            "semver_mode",
            sa.Enum(*_SEMVER_MODE, name="semvermode"),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("fqn", "environment", name="uq_asset_fqn_environment"),
    )
    op.create_index("ix_assets_owner_team_id", "assets", ["owner_team_id"])
    op.create_index("ix_assets_owner_user_id", "assets", ["owner_user_id"])
    op.create_index("ix_assets_service_id", "assets", ["service_id"])
    op.create_index("ix_assets_environment", "assets", ["environment"])
    op.create_index("ix_assets_resource_type", "assets", ["resource_type"])
    op.create_index("ix_assets_deleted_at", "assets", ["deleted_at"])
    op.create_index("idx_asset_team_active", "assets", ["owner_team_id", "deleted_at"])
    op.create_index("idx_asset_env_active", "assets", ["environment", "deleted_at"])

    # ── 6. contracts ──────────────────────────────────────────────────────
    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column(
            "schema_format",
            sa.Enum(*_SCHEMA_FORMAT, name="schemaformat"),
            nullable=False,
        ),
        sa.Column(
            "compatibility_mode",
            sa.Enum(*_COMPATIBILITY_MODE, name="compatibilitymode"),
            nullable=False,
        ),
        sa.Column("guarantees", sa.JSON(), nullable=True),
        sa.Column("field_descriptions", sa.JSON(), nullable=False),
        sa.Column("field_tags", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_CONTRACT_STATUS, name="contractstatus"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("asset_id", "version", name="uq_contracts_asset_version"),
    )
    op.create_index("ix_contracts_asset_id", "contracts", ["asset_id"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_published_at", "contracts", ["published_at"])
    op.create_index("ix_contracts_published_by_user_id", "contracts", ["published_by_user_id"])
    op.create_index("idx_contract_asset_status", "contracts", ["asset_id", "status"])

    # ── 7. registrations ──────────────────────────────────────────────────
    op.create_table(
        "registrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("consumer_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("pinned_version", sa.String(50), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_REGISTRATION_STATUS, name="registrationstatus"),
            nullable=False,
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "contract_id", "consumer_team_id", name="uq_registration_contract_consumer"
        ),
    )
    op.create_index("ix_registrations_contract_id", "registrations", ["contract_id"])
    op.create_index("ix_registrations_consumer_team_id", "registrations", ["consumer_team_id"])
    op.create_index("ix_registrations_registered_at", "registrations", ["registered_at"])
    op.create_index("ix_registrations_deleted_at", "registrations", ["deleted_at"])
    op.create_index(
        "idx_registration_contract_active", "registrations", ["contract_id", "deleted_at"]
    )
    op.create_index(
        "idx_registration_team_active", "registrations", ["consumer_team_id", "deleted_at"]
    )

    # ── 8. proposals ──────────────────────────────────────────────────────
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("proposed_schema", sa.JSON(), nullable=False),
        sa.Column("proposed_guarantees", sa.JSON(), nullable=True),
        sa.Column(
            "change_type",
            sa.Enum(*_CHANGE_TYPE, name="changetype"),
            nullable=False,
        ),
        sa.Column("breaking_changes", sa.JSON(), nullable=False),
        sa.Column("guarantee_changes", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_PROPOSAL_STATUS, name="proposalstatus"),
            nullable=False,
        ),
        sa.Column("proposed_by", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("proposed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_expire", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("affected_teams", sa.JSON(), nullable=False),
        sa.Column("affected_assets", sa.JSON(), nullable=False),
        sa.Column("objections", sa.JSON(), nullable=False),
    )
    op.create_index("ix_proposals_asset_id", "proposals", ["asset_id"])
    op.create_index("ix_proposals_status", "proposals", ["status"])
    op.create_index("ix_proposals_proposed_by_user_id", "proposals", ["proposed_by_user_id"])
    op.create_index("ix_proposals_proposed_at", "proposals", ["proposed_at"])
    op.create_index("ix_proposals_expires_at", "proposals", ["expires_at"])
    op.create_index("idx_proposal_asset_status", "proposals", ["asset_id", "status"])
    op.create_index(
        "uq_one_pending_proposal_per_asset",
        "proposals",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    # ── 9. acknowledgments ────────────────────────────────────────────────
    op.create_table(
        "acknowledgments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("consumer_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "response",
            sa.Enum(*_ACK_RESPONSE, name="acknowledgmentresponsetype"),
            nullable=False,
        ),
        sa.Column("migration_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "proposal_id", "consumer_team_id", name="uq_acknowledgment_proposal_consumer"
        ),
    )
    op.create_index("ix_acknowledgments_proposal_id", "acknowledgments", ["proposal_id"])
    op.create_index("ix_acknowledgments_consumer_team_id", "acknowledgments", ["consumer_team_id"])
    op.create_index(
        "ix_acknowledgments_acknowledged_by_user_id",
        "acknowledgments",
        ["acknowledged_by_user_id"],
    )

    # ── 10. otel_sync_configs ─────────────────────────────────────────────
    op.create_table(
        "otel_sync_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "backend_type",
            sa.Enum(*_OTEL_BACKEND, name="otelbackendtype"),
            nullable=False,
        ),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("auth_header", sa.String(500), nullable=True),
        sa.Column("lookback_seconds", sa.Integer(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("min_call_count", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sync_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_otel_config_name",
        "otel_sync_configs",
        ["name"],
        unique=True,
    )
    op.create_index("ix_otel_sync_configs_deleted_at", "otel_sync_configs", ["deleted_at"])

    # ── 11. dependencies ──────────────────────────────────────────────────
    op.create_table(
        "dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dependent_asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("dependency_asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column(
            "dependency_type",
            sa.Enum(*_DEPENDENCY_TYPE, name="dependencytype"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(*_DEPENDENCY_SOURCE, name="dependencysource"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=True),
        sa.Column("syncs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "otel_config_id",
            sa.Uuid(),
            sa.ForeignKey("otel_sync_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "dependent_asset_id",
            "dependency_asset_id",
            "dependency_type",
            "source",
            name="uq_dependency_edge",
        ),
    )
    op.create_index("ix_dependencies_dependent_asset_id", "dependencies", ["dependent_asset_id"])
    op.create_index("ix_dependencies_dependency_asset_id", "dependencies", ["dependency_asset_id"])
    op.create_index("ix_dependencies_source", "dependencies", ["source"])
    op.create_index("idx_dependency_source", "dependencies", ["source"])
    op.create_index("ix_dependencies_deleted_at", "dependencies", ["deleted_at"])
    op.create_index("ix_dependencies_otel_config_id", "dependencies", ["otel_config_id"])
    op.create_index(
        "idx_dependency_target_active",
        "dependencies",
        ["dependency_asset_id", "deleted_at"],
    )

    # ── 12. audit_events ──────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="human"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index(
        "ix_audit_events_entity_type_occurred_at",
        "audit_events",
        ["entity_type", "occurred_at"],
    )

    # ── 13. api_keys ──────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=True),
        sa.Column("agent_framework", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_team_id", "api_keys", ["team_id"])
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    # ── 14. webhook_deliveries ────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_WEBHOOK_STATUS, name="webhookdeliverystatus"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_deliveries_event_type", "webhook_deliveries", ["event_type"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index("ix_webhook_deliveries_created_at", "webhook_deliveries", ["created_at"])

    # ── 15. audit_runs ────────────────────────────────────────────────────
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_AUDIT_RUN_STATUS, name="auditrunstatus"),
            nullable=False,
        ),
        sa.Column("guarantees_checked", sa.Integer(), nullable=False),
        sa.Column("guarantees_passed", sa.Integer(), nullable=False),
        sa.Column("guarantees_failed", sa.Integer(), nullable=False),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("run_id", sa.String(255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_runs_asset_id", "audit_runs", ["asset_id"])
    op.create_index("ix_audit_runs_contract_id", "audit_runs", ["contract_id"])
    op.create_index("ix_audit_runs_status", "audit_runs", ["status"])
    op.create_index("ix_audit_runs_triggered_by", "audit_runs", ["triggered_by"])
    op.create_index("ix_audit_runs_run_id", "audit_runs", ["run_id"])
    op.create_index("ix_audit_runs_run_at", "audit_runs", ["run_at"])

    # ── 16. slack_configs ─────────────────────────────────────────────────
    op.create_table(
        "slack_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("channel_id", sa.String(100), nullable=False),
        sa.Column("channel_name", sa.String(200), nullable=True),
        sa.Column("webhook_url", sa.String(500), nullable=True),
        sa.Column("bot_token", sa.String(500), nullable=True),
        sa.Column("notify_on", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("team_id", "channel_id", name="uq_slack_configs_team_channel"),
    )
    op.create_index("ix_slack_configs_team_id", "slack_configs", ["team_id"])
    op.create_index("ix_slack_configs_deleted_at", "slack_configs", ["deleted_at"])

    # ── 17. inferred_dependencies ─────────────────────────────────────────
    op.create_table(
        "inferred_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("consumer_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "dependency_type",
            sa.Enum(*_DEPENDENCY_TYPE, name="dependencytype", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_INFERRED_DEP_STATUS, name="inferreddependencystatus"),
            nullable=False,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "promoted_registration_id",
            sa.Uuid(),
            sa.ForeignKey("registrations.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "asset_id", "consumer_team_id", "source", name="uq_inferred_dep_asset_team_source"
        ),
    )
    op.create_index("ix_inferred_dependencies_asset_id", "inferred_dependencies", ["asset_id"])
    op.create_index(
        "ix_inferred_dependencies_consumer_team_id",
        "inferred_dependencies",
        ["consumer_team_id"],
    )
    op.create_index("ix_inferred_dependencies_status", "inferred_dependencies", ["status"])

    # ── 18. sync_events ───────────────────────────────────────────────────
    op.create_table(
        "sync_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("repo_id", sa.Uuid(), sa.ForeignKey("repos.id"), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("specs_found", sa.Integer(), nullable=False),
        sa.Column("contracts_published", sa.Integer(), nullable=False),
        sa.Column("proposals_created", sa.Integer(), nullable=False),
        sa.Column("services_created", sa.Integer(), nullable=False),
        sa.Column("assets_created", sa.Integer(), nullable=False),
        sa.Column("assets_updated", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("triggered_by", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sync_events_repo_id", "sync_events", ["repo_id"])
    op.create_index("ix_sync_events_repo_created", "sync_events", ["repo_id", "created_at"])


def downgrade() -> None:
    """Drop all tables and enum types."""
    # Drop tables in reverse FK dependency order.
    tables = [
        "sync_events",
        "inferred_dependencies",
        "slack_configs",
        "audit_runs",
        "webhook_deliveries",
        "api_keys",
        "audit_events",
        "dependencies",
        "otel_sync_configs",
        "acknowledgments",
        "proposals",
        "registrations",
        "contracts",
        "assets",
        "services",
        "repos",
        "users",
        "teams",
    ]
    for table in tables:
        op.drop_table(table)

    # On PostgreSQL, drop the enum types created by sa.Enum().
    if not _is_sqlite():
        enum_types = [
            "compatibilitymode",
            "contractstatus",
            "registrationstatus",
            "changetype",
            "proposalstatus",
            "acknowledgmentresponsetype",
            "dependencytype",
            "guaranteemode",
            "semvermode",
            "resourcetype",
            "schemaformat",
            "userrole",
            "usertype",
            "webhookdeliverystatus",
            "auditrunstatus",
            "inferreddependencystatus",
            "otelbackendtype",
            "dependencysource",
        ]
        for enum_type in enum_types:
            op.execute(f"DROP TYPE IF EXISTS {enum_type}")
