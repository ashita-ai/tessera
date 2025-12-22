"""add_soft_deletes

Revision ID: 5302d2ccc2e1
Revises: 003
Create Date: 2025-12-21 15:50:21.967812

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5302d2ccc2e1"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("teams", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_teams_deleted_at", "teams", ["deleted_at"])
    op.add_column("assets", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_assets_deleted_at", "assets", ["deleted_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_assets_deleted_at", table_name="assets")
    op.drop_column("assets", "deleted_at")
    op.drop_index("ix_teams_deleted_at", table_name="teams")
    op.drop_column("teams", "deleted_at")
