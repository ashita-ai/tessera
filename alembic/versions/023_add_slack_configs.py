"""Add slack_configs table for per-team Slack notification configuration.

Revision ID: 023
Revises: 022
Create Date: 2026-04-04

Part of ADR-014 Phase 3 (Slack integration). Creates the ``slack_configs``
table for team-scoped Slack notification preferences with webhook URL or
bot token delivery and event type filtering.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "023"
down_revision: str = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"
    fk_prefix = f"{schema}." if schema else ""

    op.create_table(
        "slack_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "team_id",
            sa.Uuid(),
            sa.ForeignKey(f"{fk_prefix}teams.id"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.String(100), nullable=False),
        sa.Column("channel_name", sa.String(200), nullable=True),
        sa.Column("webhook_url", sa.String(500), nullable=True),
        sa.Column("bot_token", sa.String(500), nullable=True),
        sa.Column(
            "notify_on",
            sa.JSON(),
            nullable=False,
            server_default='["proposal_created", "proposal_resolved", "force_publish"]',
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1") if _is_sqlite() else sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )

    op.create_index(
        "ix_slack_configs_team_id",
        "slack_configs",
        ["team_id"],
        schema=schema,
    )

    # Unique constraint: one config per (team, channel)
    table_ref = f"{schema}.slack_configs" if schema else "slack_configs"
    op.execute(
        f"CREATE UNIQUE INDEX uq_slack_configs_team_channel "
        f"ON {table_ref} (team_id, channel_id)"
    )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"
    op.drop_table("slack_configs", schema=schema)
