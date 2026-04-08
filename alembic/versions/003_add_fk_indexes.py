"""Add indexes on contracts.published_by and proposals.proposed_by.

Revision ID: 003
Revises: 002
Create Date: 2026-04-08

These foreign key columns are used in audit queries and team-scoped
lookups but were missing indexes, causing full table scans at scale.

See: https://github.com/ashita-ai/tessera/issues/383

Note: dependencies.dependency_asset_id was already indexed in 001
(ix_dependencies_dependency_asset_id and idx_dependency_target_active).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add indexes on published_by and proposed_by FK columns."""
    op.create_index("ix_contracts_published_by", "contracts", ["published_by"])
    op.create_index("ix_proposals_proposed_by", "proposals", ["proposed_by"])


def downgrade() -> None:
    """Remove published_by and proposed_by indexes."""
    op.drop_index("ix_proposals_proposed_by", table_name="proposals")
    op.drop_index("ix_contracts_published_by", table_name="contracts")
