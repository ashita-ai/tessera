"""Add schema_format to contracts table.

Revision ID: 005
Revises: 004
Create Date: 2025-12-28 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    # Add schema_format to contracts with default 'json_schema'
    # Existing contracts are JSON Schema format (the original format)
    op.add_column(
        "contracts",
        sa.Column(
            "schema_format",
            sa.String(length=50),
            nullable=False,
            server_default="json_schema",
        ),
    )


def downgrade():
    op.drop_column("contracts", "schema_format")
