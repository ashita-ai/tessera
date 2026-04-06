"""Add description column to assets table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable description column to assets."""
    op.add_column("assets", sa.Column("description", sa.String(2000), nullable=True))


def downgrade() -> None:
    """Remove description column from assets."""
    op.drop_column("assets", "description")
