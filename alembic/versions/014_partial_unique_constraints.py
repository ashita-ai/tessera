"""Convert global unique constraints to partial unique indexes.

Revision ID: 014
Revises: 013
Create Date: 2026-02-15

Tables with soft-delete (deleted_at) have global unique constraints that
prevent re-creating a record after it has been soft-deleted.  For example,
soft-deleting a team named "analytics" and then creating a new team with
the same name would fail.

This migration converts 4 unique constraints to partial unique indexes
with ``WHERE deleted_at IS NULL`` so that uniqueness is only enforced
among live (non-deleted) rows.

PostgreSQL only — SQLite does not support partial indexes via ALTER TABLE
and cannot drop named constraints.  The global constraints created by
``create_all`` in SQLite tests remain unchanged.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint_name, columns, partial_index_name)
_CONSTRAINTS = [
    (
        "registrations",
        "uq_registration_contract_consumer",
        "contract_id, consumer_team_id",
        "uq_registration_contract_consumer_live",
    ),
    (
        "assets",
        "uq_asset_fqn_environment",
        "fqn, environment",
        "uq_asset_fqn_environment_live",
    ),
    (
        "dependencies",
        "uq_dependency_edge",
        "dependent_asset_id, dependency_asset_id, dependency_type",
        "uq_dependency_edge_live",
    ),
    (
        "teams",
        "teams_name_key",
        "name",
        "uq_teams_name_live",
    ),
]


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Replace global unique constraints with partial unique indexes."""
    if _is_sqlite():
        # SQLite: no-op. Global constraints from create_all remain.
        return

    for table, constraint, columns, partial_idx in _CONSTRAINTS:
        # Drop the global constraint first
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        # Create partial unique index on live rows only
        op.execute(
            f"CREATE UNIQUE INDEX {partial_idx} "
            f"ON {table} ({columns}) "
            f"WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    """Restore global unique constraints from partial indexes."""
    if _is_sqlite():
        return

    for table, constraint, columns, partial_idx in _CONSTRAINTS:
        # Drop partial index
        op.execute(f"DROP INDEX IF EXISTS {partial_idx}")
        # Re-create global constraint
        op.execute(f"ALTER TABLE {table} " f"ADD CONSTRAINT {constraint} UNIQUE ({columns})")
