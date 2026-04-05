"""Add syncs_seen to dependencies and sync_count to otel_sync_configs.

Revision ID: 029
Revises: 028
Create Date: 2026-04-05

Enables proper confidence scoring per spec 007. The confidence formula's
consistency component requires tracking how many distinct sync runs have
observed each dependency edge (syncs_seen) against the total number of
syncs run by a config (sync_count).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "029"
down_revision: str = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.add_column(
        "dependencies",
        sa.Column("syncs_seen", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "otel_sync_configs",
        sa.Column("sync_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("otel_sync_configs", "sync_count")
    op.drop_column("dependencies", "syncs_seen")
