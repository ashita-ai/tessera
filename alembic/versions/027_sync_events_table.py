"""Add sync_events table for tracking repo sync history.

Revision ID: 027
Revises: 026
Create Date: 2026-04-04

Records the outcome of each repo sync (manual or worker-triggered) so
operators can inspect sync history and debug failures without trawling
server logs.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "027"
down_revision: str = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    op.create_table(
        "sync_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("repo_id", sa.Uuid(), sa.ForeignKey("repos.id"), nullable=False, index=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("specs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_published", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proposals_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("services_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assets_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assets_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("triggered_by", sa.String(20), nullable=False, server_default="'worker'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )

    # Index for efficient "latest event for repo" queries
    op.create_index(
        "ix_sync_events_repo_created",
        "sync_events",
        ["repo_id", "created_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    op.drop_index("ix_sync_events_repo_created", table_name="sync_events", schema=schema)
    op.drop_table("sync_events", schema=schema)
