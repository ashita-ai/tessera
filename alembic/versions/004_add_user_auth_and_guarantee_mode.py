"""Add user auth fields and asset guarantee_mode.

Revision ID: 004
Revises: 5302d2ccc2e1
Create Date: 2025-12-23 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "5302d2ccc2e1"
branch_labels = None
depends_on = None


def upgrade():
    # Add guarantee_mode to assets with default 'notify'
    op.add_column(
        "assets",
        sa.Column(
            "guarantee_mode",
            sa.String(length=50),
            nullable=False,
            server_default="notify",
        ),
    )

    # Add auth columns to users
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=50),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notification_preferences",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade():
    op.drop_column("users", "notification_preferences")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
    op.drop_column("assets", "guarantee_mode")
