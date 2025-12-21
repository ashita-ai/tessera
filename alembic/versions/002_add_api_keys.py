"""Add API keys table.

Revision ID: 002
Revises: 001
Create Date: 2024-12-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add API keys table."""
    schema = None if _is_sqlite() else "core"

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "team_id",
            sa.Uuid(),
            sa.ForeignKey(f"{schema + '.' if schema else ''}teams.id"),
            nullable=False,
        ),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    # Index for key hash lookups (authentication)
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], schema=schema)
    # Index for team lookups (list keys by team)
    op.create_index("ix_api_keys_team_id", "api_keys", ["team_id"], schema=schema)


def downgrade() -> None:
    """Remove API keys table."""
    schema = None if _is_sqlite() else "core"

    op.drop_index("ix_api_keys_team_id", table_name="api_keys", schema=schema)
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys", schema=schema)
    op.drop_table("api_keys", schema=schema)
