"""Add repos and services tables, link assets to services.

Revision ID: 020
Revises: 019
Create Date: 2026-04-03

Establishes the Team → Repo → Service → Asset hierarchy (ADR-014, Phase 1).

Adds:
- ``repos`` table: git repositories owned by teams
- ``services`` table: deployable units within repos
- ``assets.service_id``: optional FK linking assets to services
- Partial unique indexes for soft-delete-safe uniqueness
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020"
down_revision: str = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # --- repos table ---
    op.create_table(
        "repos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("git_url", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(100), nullable=False, server_default="main"),
        sa.Column("spec_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("owner_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1") if _is_sqlite() else sa.text("true"),
        ),
        sa.Column("codeowners_path", sa.String(200), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_commit", sa.String(40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )

    op.create_index("ix_repos_owner_team_id", "repos", ["owner_team_id"], schema=schema)
    op.create_index("ix_repos_deleted_at", "repos", ["deleted_at"], schema=schema)

    # Partial unique indexes for soft-delete-safe uniqueness
    if _is_sqlite():
        op.execute(
            "CREATE UNIQUE INDEX uq_repo_name_active ON repos (name) " "WHERE deleted_at IS NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX uq_repo_git_url_active ON repos (git_url) "
            "WHERE deleted_at IS NULL"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_repo_name_active ON repos (name) " "WHERE deleted_at IS NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX uq_repo_git_url_active ON repos (git_url) "
            "WHERE deleted_at IS NULL"
        )

    # --- services table ---
    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("repo_id", sa.Uuid(), sa.ForeignKey("repos.id"), nullable=False),
        sa.Column("root_path", sa.String(500), nullable=False, server_default="/"),
        sa.Column("otel_service_name", sa.String(200), nullable=True),
        sa.Column("owner_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )

    op.create_index("ix_services_repo_id", "services", ["repo_id"], schema=schema)
    op.create_index("ix_services_owner_team_id", "services", ["owner_team_id"], schema=schema)
    op.create_index("ix_services_deleted_at", "services", ["deleted_at"], schema=schema)

    # Partial unique index: (name, repo_id) among non-deleted services
    if _is_sqlite():
        op.execute(
            "CREATE UNIQUE INDEX uq_service_name_repo_active "
            "ON services (name, repo_id) WHERE deleted_at IS NULL"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_service_name_repo_active "
            "ON services (name, repo_id) WHERE deleted_at IS NULL"
        )

    # --- assets.service_id FK ---
    op.add_column(
        "assets",
        sa.Column("service_id", sa.Uuid(), nullable=True),
        schema=schema,
    )

    if not _is_sqlite():
        op.create_foreign_key(
            "fk_assets_service_id",
            "assets",
            "services",
            ["service_id"],
            ["id"],
            source_schema=schema,
            referent_schema=schema,
        )

    op.create_index("ix_assets_service_id", "assets", ["service_id"], schema=schema)


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # Drop assets.service_id
    op.drop_index("ix_assets_service_id", table_name="assets", schema=schema)
    if not _is_sqlite():
        op.drop_constraint("fk_assets_service_id", "assets", type_="foreignkey", schema=schema)
    op.drop_column("assets", "service_id", schema=schema)

    # Drop services table (indexes dropped automatically with table)
    op.drop_table("services", schema=schema)

    # Drop repos table (indexes dropped automatically with table)
    op.drop_table("repos", schema=schema)
