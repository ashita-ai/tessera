"""Add soft delete support to dependencies.

Revision ID: 012
Revises: 011
Create Date: 2026-02-15

Dependencies previously used hard delete, which destroyed lineage data
and left no audit trail. This migration adds a deleted_at column to enable
soft deletes consistent with teams, assets, users, and registrations.

Also adds composite indexes on (source_asset_id, deleted_at) and
(target_asset_id, deleted_at) to support filtered lineage queries.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add deleted_at column and indexes to dependencies."""
    if _is_sqlite():
        with op.batch_alter_table("dependencies") as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_deleted_at ON dependencies (deleted_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_source_deleted "
            "ON dependencies (dependent_asset_id, deleted_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_target_deleted "
            "ON dependencies (dependency_asset_id, deleted_at)"
        )
    else:
        op.add_column(
            "dependencies",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_deleted_at ON dependencies (deleted_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_source_deleted "
            "ON dependencies (dependent_asset_id, deleted_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_dependencies_target_deleted "
            "ON dependencies (dependency_asset_id, deleted_at)"
        )


def downgrade() -> None:
    """Remove deleted_at column and indexes from dependencies."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS ix_dependencies_target_deleted")
        op.execute("DROP INDEX IF EXISTS ix_dependencies_source_deleted")
        op.execute("DROP INDEX IF EXISTS ix_dependencies_deleted_at")
        with op.batch_alter_table("dependencies") as batch_op:
            batch_op.drop_column("deleted_at")
    else:
        op.execute("DROP INDEX IF EXISTS ix_dependencies_target_deleted")
        op.execute("DROP INDEX IF EXISTS ix_dependencies_source_deleted")
        op.execute("DROP INDEX IF EXISTS ix_dependencies_deleted_at")
        op.drop_column("dependencies", "deleted_at")
