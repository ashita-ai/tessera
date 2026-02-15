"""Add unique constraints to prevent duplicate registrations, acknowledgments, and dependencies.

Revision ID: 010
Revises: 009
Create Date: 2026-02-11

Adds three unique constraints to enforce data integrity:
- registrations(contract_id, consumer_team_id)
- acknowledgments(proposal_id, consumer_team_id)
- dependencies(dependent_asset_id, dependency_asset_id, dependency_type)

Note: If existing data contains duplicates, this migration will fail.
Clean up duplicate rows before running.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Add unique constraints to registrations, acknowledgments, and dependencies."""
    if _is_sqlite():
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_contract_consumer "
            "ON registrations (contract_id, consumer_team_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_acknowledgment_proposal_consumer "
            "ON acknowledgments (proposal_id, consumer_team_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_dependency_edge "
            "ON dependencies (dependent_asset_id, dependency_asset_id, dependency_type)"
        )
    else:
        op.create_unique_constraint(
            "uq_registration_contract_consumer",
            "registrations",
            ["contract_id", "consumer_team_id"],
        )
        op.create_unique_constraint(
            "uq_acknowledgment_proposal_consumer",
            "acknowledgments",
            ["proposal_id", "consumer_team_id"],
        )
        op.create_unique_constraint(
            "uq_dependency_edge",
            "dependencies",
            ["dependent_asset_id", "dependency_asset_id", "dependency_type"],
        )


def downgrade() -> None:
    """Remove unique constraints."""
    if _is_sqlite():
        op.execute("DROP INDEX IF EXISTS uq_registration_contract_consumer")
        op.execute("DROP INDEX IF EXISTS uq_acknowledgment_proposal_consumer")
        op.execute("DROP INDEX IF EXISTS uq_dependency_edge")
    else:
        op.drop_constraint("uq_registration_contract_consumer", "registrations", type_="unique")
        op.drop_constraint("uq_acknowledgment_proposal_consumer", "acknowledgments", type_="unique")
        op.drop_constraint("uq_dependency_edge", "dependencies", type_="unique")
