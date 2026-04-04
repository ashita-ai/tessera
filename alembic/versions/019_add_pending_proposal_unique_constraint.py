"""Add partial unique index to prevent duplicate pending proposals.

Revision ID: 019
Revises: 018
Create Date: 2026-04-04

Without this index, two concurrent breaking-change publishes can both see
"no pending proposal" (FOR UPDATE acquires no lock when no row exists) and
both create one. The partial unique index ensures at most one pending
proposal per asset at the database level.

Important: Alembic migration 001 created the ``proposalstatus`` enum with
lowercase values (``'pending'``), so the WHERE clause here uses lowercase.
The SQLAlchemy model's ``create_all()`` path uses uppercase member names
(``'PENDING'``) — the model's ``__table_args__`` handles that separately.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Create partial unique index on proposals for at-most-one pending per asset."""
    if _is_sqlite():
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_pending_proposal_per_asset "
            "ON proposals (asset_id) "
            "WHERE status = 'pending'"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_pending_proposal_per_asset "
            "ON proposals (asset_id) "
            "WHERE status = 'pending'::proposalstatus"
        )


def downgrade() -> None:
    """Drop the partial unique index."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS uq_one_pending_proposal_per_asset")
    else:
        op.execute("DROP INDEX IF EXISTS uq_one_pending_proposal_per_asset")
