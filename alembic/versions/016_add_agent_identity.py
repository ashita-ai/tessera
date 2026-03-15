"""Add agent identity columns to API keys and audit events.

Revision ID: 016
Revises: 015
Create Date: 2026-03-13

Adds:
- APIKeyDB.agent_name (nullable): Human-readable agent name
- APIKeyDB.agent_framework (nullable): Framework identifier
- AuditEventDB.actor_type (non-null, default 'human'): 'human' or 'agent'

A key is an "agent key" when agent_name IS NOT NULL. Existing keys remain
human keys. actor_type is populated automatically from the API key used
in the request.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # Add agent columns to api_keys
    op.add_column(
        "api_keys",
        sa.Column("agent_name", sa.String(255), nullable=True),
        schema=schema,
    )
    op.add_column(
        "api_keys",
        sa.Column("agent_framework", sa.String(100), nullable=True),
        schema=schema,
    )

    # Add actor_type to audit_events with server default
    op.add_column(
        "audit_events",
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="human"),
        schema=schema,
    )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    op.drop_column("audit_events", "actor_type", schema=schema)
    op.drop_column("api_keys", "agent_framework", schema=schema)
    op.drop_column("api_keys", "agent_name", schema=schema)
