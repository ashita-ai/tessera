"""Add composite indexes for common query patterns.

Revision ID: 007
Revises: 006
Create Date: 2026-01-24

These indexes optimize frequently-used query patterns:
- Finding pending proposals for an asset
- Finding active contracts for an asset
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Create composite indexes for common query patterns."""
    if _is_sqlite():
        # SQLite syntax
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_proposal_asset_status "
            "ON proposals (asset_id, status)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_contract_asset_status "
            "ON contracts (asset_id, status)"
        )
    else:
        # PostgreSQL with schema
        schema = "core"
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_proposal_asset_status "
            f"ON {schema}.proposals (asset_id, status)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_contract_asset_status "
            f"ON {schema}.contracts (asset_id, status)"
        )


def downgrade() -> None:
    """Drop composite indexes."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS idx_proposal_asset_status")
        op.execute("DROP INDEX IF EXISTS idx_contract_asset_status")
    else:
        schema = "core"
        op.execute(f"DROP INDEX IF EXISTS {schema}.idx_proposal_asset_status")
        op.execute(f"DROP INDEX IF EXISTS {schema}.idx_contract_asset_status")
