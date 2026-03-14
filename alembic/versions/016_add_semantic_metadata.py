"""Add semantic metadata columns to assets and contracts.

Revision ID: 016
Revises: 015
Create Date: 2026-03-13

Adds:
- AssetDB.tags: JSON column for free-form labels (e.g., ["pii", "financial"])
- ContractDB.field_descriptions: JSON column mapping JSON path -> description
- ContractDB.field_tags: JSON column mapping JSON path -> list of tags
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add semantic metadata columns."""
    op.add_column("assets", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))
    op.add_column(
        "contracts",
        sa.Column("field_descriptions", sa.JSON(), nullable=True, server_default="{}"),
    )
    op.add_column(
        "contracts",
        sa.Column("field_tags", sa.JSON(), nullable=True, server_default="{}"),
    )


def downgrade() -> None:
    """Remove semantic metadata columns."""
    op.drop_column("contracts", "field_tags")
    op.drop_column("contracts", "field_descriptions")
    op.drop_column("assets", "tags")
