"""Add audit_runs table for data quality tracking.

Revision ID: 029
Revises: 028
Create Date: 2026-04-04

Records the results of quality checks (test suites, monitoring probes,
CI pipelines) against contract guarantees. Enables the Write-Audit-Publish
pattern and runtime enforcement tracking.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "029"
down_revision: str = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"
    fk_prefix = f"{schema}." if schema else ""

    if not _is_sqlite():
        op.execute("CREATE TYPE auditrunstatus AS ENUM " "('passed', 'failed', 'partial')")

    op.create_table(
        "audit_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey(f"{fk_prefix}assets.id"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey(f"{fk_prefix}contracts.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(50)
            if _is_sqlite()
            else sa.Enum(
                "passed",
                "failed",
                "partial",
                name="auditrunstatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("guarantees_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("guarantees_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("guarantees_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("run_id", sa.String(255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )

    op.create_index("ix_audit_runs_asset_id", "audit_runs", ["asset_id"], schema=schema)
    op.create_index("ix_audit_runs_contract_id", "audit_runs", ["contract_id"], schema=schema)
    op.create_index("ix_audit_runs_status", "audit_runs", ["status"], schema=schema)
    op.create_index("ix_audit_runs_triggered_by", "audit_runs", ["triggered_by"], schema=schema)
    op.create_index("ix_audit_runs_run_id", "audit_runs", ["run_id"], schema=schema)
    op.create_index("ix_audit_runs_run_at", "audit_runs", ["run_at"], schema=schema)


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"
    op.drop_table("audit_runs", schema=schema)
    if not _is_sqlite():
        op.execute("DROP TYPE IF EXISTS auditrunstatus")
