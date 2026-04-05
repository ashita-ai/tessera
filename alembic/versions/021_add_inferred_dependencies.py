"""Add inferred_dependencies table for passive dependency discovery.

Revision ID: 020
Revises: 019
Create Date: 2026-04-03

Stores dependencies inferred from audit signals (preflight.checked events).
No soft delete — rejected/expired rows stay for suppression logic.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "021"
down_revision: str = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Create inferred_dependencies table."""
    if not _is_sqlite():
        # Create enums for PostgreSQL
        op.execute(
            "CREATE TYPE inferreddependencystatus AS ENUM "
            "('pending', 'confirmed', 'rejected', 'expired')"
        )

    op.create_table(
        "inferred_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("consumer_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "dependency_type",
            sa.String(50)
            if _is_sqlite()
            else sa.Enum(
                "consumes",
                "references",
                "transforms",
                name="dependencytype",
                create_type=False,
            ),
            server_default="consumes",
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(50)
            if _is_sqlite()
            else sa.Enum(
                "pending",
                "confirmed",
                "rejected",
                "expired",
                name="inferreddependencystatus",
                create_type=False,
            ),
            server_default="pending",
        ),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "promoted_registration_id",
            sa.Uuid(),
            sa.ForeignKey("registrations.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "asset_id",
            "consumer_team_id",
            "source",
            name="uq_inferred_dep_asset_team_source",
        ),
    )

    op.create_index(
        "ix_inferred_dependencies_asset_id",
        "inferred_dependencies",
        ["asset_id"],
    )
    op.create_index(
        "ix_inferred_dependencies_consumer_team_id",
        "inferred_dependencies",
        ["consumer_team_id"],
    )
    op.create_index(
        "ix_inferred_dependencies_status",
        "inferred_dependencies",
        ["status"],
    )


def downgrade() -> None:
    """Drop inferred_dependencies table."""
    op.drop_table("inferred_dependencies")
    if not _is_sqlite():
        op.execute("DROP TYPE IF EXISTS inferreddependencystatus")
