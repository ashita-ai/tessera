"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2024-12-20

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


def upgrade() -> None:
    """Create initial schema."""
    if not _is_sqlite():
        # PostgreSQL: Create schemas
        op.execute("CREATE SCHEMA IF NOT EXISTS core")
        op.execute("CREATE SCHEMA IF NOT EXISTS workflow")
        op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    schema = None if _is_sqlite() else "core"
    workflow_schema = None if _is_sqlite() else "workflow"
    audit_schema = None if _is_sqlite() else "audit"

    # Teams table
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        schema=schema,
    )

    # Assets table
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fqn", sa.String(1000), nullable=False, unique=True),
        sa.Column(
            "owner_team_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}teams.id"),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        schema=schema,
    )
    # Index for FQN lookups
    op.create_index("ix_assets_fqn", "assets", ["fqn"], schema=schema)

    # Contracts table
    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}assets.id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column(
            "compatibility_mode",
            sa.Enum(
                "backward",
                "forward",
                "full",
                "none",
                name="compatibilitymode",
                schema=schema,
            ),
            nullable=False,
        ),
        sa.Column("guarantees", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "deprecated", "retired", name="contractstatus", schema=schema),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        schema=schema,
    )
    # Index for finding active contracts by asset
    op.create_index("ix_contracts_asset_status", "contracts", ["asset_id", "status"], schema=schema)
    # Unique constraint for version per asset
    op.create_unique_constraint("uq_contracts_asset_version", "contracts", ["asset_id", "version"], schema=schema)

    # Registrations table
    op.create_table(
        "registrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}contracts.id"),
            nullable=False,
        ),
        sa.Column(
            "consumer_team_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}teams.id"),
            nullable=False,
        ),
        sa.Column("pinned_version", sa.String(50), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "migrating", "inactive", name="registrationstatus", schema=schema),
            nullable=False,
        ),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        schema=schema,
    )
    # Index for finding registrations by contract
    op.create_index("ix_registrations_contract_status", "registrations", ["contract_id", "status"], schema=schema)

    # Dependencies table
    op.create_table(
        "dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dependent_asset_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}assets.id"),
            nullable=False,
        ),
        sa.Column(
            "dependency_asset_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}assets.id"),
            nullable=False,
        ),
        sa.Column(
            "dependency_type",
            sa.Enum("consumes", "references", "transforms", name="dependencytype", schema=schema),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        schema=schema,
    )

    # Proposals table (workflow schema)
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}assets.id"),
            nullable=False,
        ),
        sa.Column("proposed_schema", sa.JSON(), nullable=False),
        sa.Column(
            "change_type",
            sa.Enum("patch", "minor", "major", name="changetype", schema=workflow_schema),
            nullable=False,
        ),
        sa.Column("breaking_changes", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "withdrawn",
                name="proposalstatus",
                schema=workflow_schema,
            ),
            nullable=False,
        ),
        sa.Column("proposed_by", sa.Uuid(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        schema=workflow_schema,
    )
    # Index for finding proposals by asset and status
    op.create_index("ix_proposals_asset_status", "proposals", ["asset_id", "status"], schema=workflow_schema)

    # Acknowledgments table (workflow schema)
    op.create_table(
        "acknowledgments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Uuid(),
            sa.ForeignKey(f"{workflow_schema + '.' if workflow_schema else ''}proposals.id"),
            nullable=False,
        ),
        sa.Column(
            "consumer_team_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}teams.id"),
            nullable=False,
        ),
        sa.Column(
            "response",
            sa.Enum(
                "approved",
                "blocked",
                "migrating",
                name="acknowledgmentresponsetype",
                schema=workflow_schema,
            ),
            nullable=False,
        ),
        sa.Column("migration_deadline", sa.DateTime(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        schema=workflow_schema,
    )

    # Audit events table (audit schema)
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        schema=audit_schema,
    )
    # Index for querying events by entity
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"], schema=audit_schema)


def downgrade() -> None:
    """Drop all tables and schemas."""
    is_sqlite = _is_sqlite()
    schema = None if is_sqlite else "core"
    workflow_schema = None if is_sqlite else "workflow"
    audit_schema = None if is_sqlite else "audit"

    # Drop indexes first
    op.drop_index("ix_events_entity", table_name="events", schema=audit_schema)
    op.drop_index("ix_proposals_asset_status", table_name="proposals", schema=workflow_schema)
    op.drop_index("ix_registrations_contract_status", table_name="registrations", schema=schema)
    op.drop_constraint("uq_contracts_asset_version", "contracts", schema=schema, type_="unique")
    op.drop_index("ix_contracts_asset_status", table_name="contracts", schema=schema)
    op.drop_index("ix_assets_fqn", table_name="assets", schema=schema)

    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table("events", schema=audit_schema)
    op.drop_table("acknowledgments", schema=workflow_schema)
    op.drop_table("proposals", schema=workflow_schema)
    op.drop_table("dependencies", schema=schema)
    op.drop_table("registrations", schema=schema)
    op.drop_table("contracts", schema=schema)
    op.drop_table("assets", schema=schema)
    op.drop_table("teams", schema=schema)

    if not is_sqlite:
        # PostgreSQL: Drop schemas
        op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
        op.execute("DROP SCHEMA IF EXISTS workflow CASCADE")
        op.execute("DROP SCHEMA IF EXISTS core CASCADE")
