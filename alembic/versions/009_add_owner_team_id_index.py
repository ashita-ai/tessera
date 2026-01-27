"""Add index on assets.owner_team_id foreign key.

Revision ID: 009
Revises: 008
Create Date: 2026-01-27

This column is used in every team-scoped query (auth checks, asset listing,
ownership validation) but was missing an explicit index. The ORM model now
declares index=True, and this migration adds it for existing databases.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add index on assets.owner_team_id."""
    if _is_sqlite():
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_assets_owner_team_id " "ON assets (owner_team_id)"
        )
    else:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_assets_owner_team_id " "ON assets (owner_team_id)"
        )


def downgrade() -> None:
    """Remove index on assets.owner_team_id."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS ix_assets_owner_team_id")
    else:
        op.execute("DROP INDEX IF EXISTS ix_assets_owner_team_id")
