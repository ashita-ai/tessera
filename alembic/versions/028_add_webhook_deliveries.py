"""Add webhook_deliveries table for delivery tracking.

Revision ID: 028
Revises: 027
Create Date: 2026-04-04

Tracks outgoing webhook delivery attempts so operators can debug
delivery failures and monitor reliability without trawling logs.
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
    schema = None if _is_sqlite() else "core"

    if not _is_sqlite():
        op.execute(
            "CREATE TYPE webhookdeliverystatus AS ENUM " "('pending', 'delivered', 'failed')"
        )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column(
            "status",
            sa.String(50)
            if _is_sqlite()
            else sa.Enum(
                "pending",
                "delivered",
                "failed",
                name="webhookdeliverystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )

    op.create_index(
        "ix_webhook_deliveries_event_type",
        "webhook_deliveries",
        ["event_type"],
        schema=schema,
    )
    op.create_index(
        "ix_webhook_deliveries_status",
        "webhook_deliveries",
        ["status"],
        schema=schema,
    )
    op.create_index(
        "ix_webhook_deliveries_created_at",
        "webhook_deliveries",
        ["created_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"
    op.drop_table("webhook_deliveries", schema=schema)
    if not _is_sqlite():
        op.execute("DROP TYPE IF EXISTS webhookdeliverystatus")
