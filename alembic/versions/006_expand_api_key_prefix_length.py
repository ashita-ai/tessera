"""Expand api_keys.key_prefix length.

Revision ID: 006
Revises: 005
Create Date: 2025-01-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Expand key_prefix to fit longer prefixes."""
    if _is_sqlite():
        return

    op.alter_column(
        "api_keys",
        "key_prefix",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        schema="core",
    )


def downgrade() -> None:
    """Revert key_prefix length to previous size."""
    if _is_sqlite():
        return

    op.alter_column(
        "api_keys",
        "key_prefix",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        schema="core",
    )
