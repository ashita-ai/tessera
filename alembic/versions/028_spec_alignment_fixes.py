"""Align models with ADR-014/Spec 006/ADR-002: remove services.owner_team_id,
add repos.poll_interval_seconds and repos.last_sync_error, add soft delete
to slack_configs and otel_sync_configs.

Revision ID: 028
Revises: 027
Create Date: 2026-04-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    # 1. Add poll_interval_seconds and last_sync_error to repos
    op.add_column(
        "repos",
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.add_column("repos", sa.Column("last_sync_error", sa.Text(), nullable=True))

    # 2. Add soft delete columns
    op.add_column(
        "slack_configs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "otel_sync_configs", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "otel_sync_configs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    # 3. Add indexes for soft delete filtering
    op.create_index("ix_slack_configs_deleted_at", "slack_configs", ["deleted_at"])
    op.create_index("ix_otel_sync_configs_deleted_at", "otel_sync_configs", ["deleted_at"])

    # 4. Remove owner_team_id from services
    # Drop the index first, then the FK constraint, then the column
    if not _is_sqlite():
        op.drop_index("ix_services_owner_team_id", table_name="services")
        op.drop_constraint("services_owner_team_id_fkey", "services", type_="foreignkey")
        op.drop_column("services", "owner_team_id")
    else:
        # SQLite doesn't support DROP COLUMN well before 3.35.0
        # Use batch mode for SQLite
        with op.batch_alter_table("services") as batch_op:
            batch_op.drop_column("owner_team_id")


def downgrade() -> None:
    # Re-add owner_team_id to services (non-nullable, so needs a default for existing rows)
    if not _is_sqlite():
        # Add as nullable first, then backfill, then make non-nullable
        op.add_column("services", sa.Column("owner_team_id", sa.Uuid(), nullable=True))
        # Backfill from repo's owner_team_id
        op.execute(
            "UPDATE services SET owner_team_id = repos.owner_team_id "
            "FROM repos WHERE services.repo_id = repos.id"
        )
        op.alter_column("services", "owner_team_id", nullable=False)
        op.create_foreign_key(
            "services_owner_team_id_fkey", "services", "teams", ["owner_team_id"], ["id"]
        )
        op.create_index("ix_services_owner_team_id", "services", ["owner_team_id"])
    else:
        pass  # SQLite downgrade not fully supported

    # Remove soft delete columns
    op.drop_index("ix_otel_sync_configs_deleted_at", table_name="otel_sync_configs")
    op.drop_index("ix_slack_configs_deleted_at", table_name="slack_configs")
    op.drop_column("otel_sync_configs", "deleted_at")
    op.drop_column("otel_sync_configs", "updated_at")
    op.drop_column("slack_configs", "deleted_at")

    # Remove repo columns
    op.drop_column("repos", "last_sync_error")
    op.drop_column("repos", "poll_interval_seconds")
