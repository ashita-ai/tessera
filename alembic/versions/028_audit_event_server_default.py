"""Add server_default to audit_events.occurred_at.

Revision ID: 028
Revises: 027
Create Date: 2026-04-05

Ensures occurred_at has a database-level default so non-ORM inserts
(raw SQL, bulk Core operations) produce a valid timestamp instead of NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028"
down_revision: str = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # SQLite doesn't support ALTER COLUMN; the Python-side default
        # and server_default in the model definition are sufficient for
        # new tables created via metadata.create_all (used in tests).
        return

    op.alter_column(
        "audit_events",
        "occurred_at",
        server_default=sa.func.now(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    if _is_sqlite():
        return

    op.alter_column(
        "audit_events",
        "occurred_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
