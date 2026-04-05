"""Add otel_sync_configs table and extend dependencies with OTEL fields.

Revision ID: 022
Revises: 021
Create Date: 2026-04-04

Adds OTEL-based dependency discovery support (Spec-007, ADR-014 Phase 2):

- ``otel_sync_configs`` table: OTEL backend connection configs (Jaeger, Tempo, Datadog)
- ``dependencies.source``: how the dependency was discovered (manual, otel, inferred)
- ``dependencies.confidence``: 0.0-1.0 confidence score for discovered deps
- ``dependencies.last_observed_at``: when OTEL last observed this edge
- ``dependencies.call_count``: observed call count in the lookback window
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "022"
down_revision: str = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # ── New table: otel_sync_configs ──────────────────────────
    op.create_table(
        "otel_sync_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "backend_type",
            sa.String(50),
            nullable=False,
        ),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("auth_header", sa.String(500), nullable=True),
        sa.Column("lookback_seconds", sa.Integer(), nullable=False, server_default="86400"),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("min_call_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "uq_otel_config_name",
        "otel_sync_configs",
        ["name"],
        unique=True,
        schema=schema,
    )

    # ── Extend dependencies table ─────────────────────────────
    op.add_column(
        "dependencies",
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        schema=schema,
    )
    op.add_column(
        "dependencies",
        sa.Column("confidence", sa.Float(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "dependencies",
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "dependencies",
        sa.Column("call_count", sa.Integer(), nullable=True),
        schema=schema,
    )
    op.create_index(
        "idx_dependency_source",
        "dependencies",
        ["source"],
        schema=schema,
    )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    op.drop_index("idx_dependency_source", table_name="dependencies", schema=schema)
    op.drop_column("dependencies", "call_count", schema=schema)
    op.drop_column("dependencies", "last_observed_at", schema=schema)
    op.drop_column("dependencies", "confidence", schema=schema)
    op.drop_column("dependencies", "source", schema=schema)

    op.drop_index("uq_otel_config_name", table_name="otel_sync_configs", schema=schema)
    op.drop_table("otel_sync_configs", schema=schema)
