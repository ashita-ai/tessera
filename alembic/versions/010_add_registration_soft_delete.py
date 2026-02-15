"""Add soft delete support to registrations.

Revision ID: 010
Revises: 009
Create Date: 2026-02-15

Registrations previously used hard delete, which destroyed relationship data
and broke the audit trail. This migration adds a deleted_at column to enable
soft deletes consistent with teams, assets, and users.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add deleted_at column and index to registrations."""
    if _is_sqlite():
        with op.batch_alter_table("registrations") as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_registrations_deleted_at ON registrations (deleted_at)"
        )
    else:
        op.add_column(
            "registrations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_registrations_deleted_at "
            "ON registrations (deleted_at)"
        )


def downgrade() -> None:
    """Remove deleted_at column from registrations."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS ix_registrations_deleted_at")
        with op.batch_alter_table("registrations") as batch_op:
            batch_op.drop_column("deleted_at")
    else:
        op.execute("DROP INDEX IF EXISTS ix_registrations_deleted_at")
        op.drop_column("registrations", "deleted_at")
