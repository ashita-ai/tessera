"""Schema hardening: updated_at, audit indexes, FKs, timezone fix.

Revision ID: 013
Revises: 012
Create Date: 2026-02-15

Additive-only changes:

1. Add ``updated_at`` column (nullable, onupdate) to 7 mutable models:
   assets, teams, users, contracts, registrations, proposals, api_keys.
   Immutable tables (audit_events, acknowledgments, dependencies,
   webhook_deliveries, audit_runs) are intentionally excluded.

2. Add indexes on audit_events for time-range and actor queries:
   - occurred_at (B-tree for range scans)
   - actor_id (equality lookups)
   - (entity_type, occurred_at) composite for filtered time-range queries

3. Add FK constraints (PostgreSQL only) on contracts.published_by and
   proposals.proposed_by pointing to teams.id.  SQLite cannot add FKs
   after table creation, and tests use create_all which picks up the
   model-level ForeignKey already.

4. Fix DateTime columns created by migration 001 from TIMESTAMP to
   TIMESTAMPTZ (PostgreSQL only).  The ALTER uses ``USING col AT TIME
   ZONE 'UTC'`` so existing naive timestamps are correctly reinterpreted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that get updated_at
_MUTABLE_TABLES = [
    "assets",
    "teams",
    "users",
    "contracts",
    "registrations",
    "proposals",
    "api_keys",
]

# Columns from migration 001 that were created as TIMESTAMP (no timezone).
# Format: (table_name, column_name)
_TIMESTAMP_COLUMNS = [
    ("teams", "created_at"),
    ("assets", "created_at"),
    ("contracts", "published_at"),
    ("registrations", "registered_at"),
    ("registrations", "acknowledged_at"),
    ("dependencies", "created_at"),
    ("proposals", "proposed_at"),
    ("proposals", "resolved_at"),
    ("acknowledgments", "migration_deadline"),
    ("acknowledgments", "responded_at"),
    ("audit_events", "occurred_at"),
]


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add updated_at columns, audit indexes, FK constraints, and fix timezone."""
    is_sqlite = _is_sqlite()

    # 1. Add updated_at to mutable tables
    if is_sqlite:
        for table in _MUTABLE_TABLES:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
                )
    else:
        for table in _MUTABLE_TABLES:
            op.add_column(
                table,
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )

    # 2. Audit indexes (both dialects)
    op.create_index(
        "ix_audit_events_occurred_at",
        "audit_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_audit_events_actor_id",
        "audit_events",
        ["actor_id"],
    )
    op.create_index(
        "ix_audit_events_entity_type_occurred_at",
        "audit_events",
        ["entity_type", "occurred_at"],
    )

    # 3. FK constraints (PostgreSQL only — SQLite can't add FKs post-creation)
    if not is_sqlite:
        op.execute(
            "ALTER TABLE contracts "
            "ADD CONSTRAINT fk_contracts_published_by_teams "
            "FOREIGN KEY (published_by) REFERENCES teams(id)"
        )
        op.execute(
            "ALTER TABLE proposals "
            "ADD CONSTRAINT fk_proposals_proposed_by_teams "
            "FOREIGN KEY (proposed_by) REFERENCES teams(id)"
        )

    # 4. Fix TIMESTAMP → TIMESTAMPTZ (PostgreSQL only)
    if not is_sqlite:
        for table, column in _TIMESTAMP_COLUMNS:
            op.execute(
                f"ALTER TABLE {table} "
                f"ALTER COLUMN {column} "
                f"TYPE TIMESTAMPTZ USING {column} AT TIME ZONE 'UTC'"
            )


def downgrade() -> None:
    """Reverse schema hardening changes."""
    is_sqlite = _is_sqlite()

    # 4. Revert TIMESTAMPTZ → TIMESTAMP (PostgreSQL only)
    if not is_sqlite:
        for table, column in _TIMESTAMP_COLUMNS:
            op.execute(
                f"ALTER TABLE {table} "
                f"ALTER COLUMN {column} "
                f"TYPE TIMESTAMP USING {column} AT TIME ZONE 'UTC'"
            )

    # 3. Drop FK constraints (PostgreSQL only)
    if not is_sqlite:
        op.execute(
            "ALTER TABLE proposals " "DROP CONSTRAINT IF EXISTS fk_proposals_proposed_by_teams"
        )
        op.execute(
            "ALTER TABLE contracts " "DROP CONSTRAINT IF EXISTS fk_contracts_published_by_teams"
        )

    # 2. Drop audit indexes
    op.drop_index("ix_audit_events_entity_type_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")

    # 1. Drop updated_at columns
    if is_sqlite:
        for table in reversed(_MUTABLE_TABLES):
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column("updated_at")
    else:
        for table in reversed(_MUTABLE_TABLES):
            op.drop_column(table, "updated_at")
