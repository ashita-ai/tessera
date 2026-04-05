"""Fix otel_config_id FK to SET NULL on delete.

Revision ID: 025
Revises: 024
Create Date: 2026-04-04

Without ON DELETE SET NULL, deleting an otel_sync_configs row while
dependencies reference it raises IntegrityError (500 in production).
The column is nullable, so SET NULL is the correct semantic: keep the
dependency row, clear the config reference.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "025"
down_revision: str = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    if _is_sqlite():
        # SQLite recreates the table in batch mode; the new FK definition
        # replaces the old one automatically.
        with op.batch_alter_table("dependencies", schema=schema) as batch_op:
            batch_op.drop_constraint("fk_dependencies_otel_config_id", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_dependencies_otel_config_id",
                "otel_sync_configs",
                ["otel_config_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        # PostgreSQL: drop the unnamed FK that Alembic auto-generated in 022,
        # then re-add with ON DELETE SET NULL.
        op.drop_constraint(
            "dependencies_otel_config_id_fkey",
            "dependencies",
            type_="foreignkey",
            schema=schema,
        )
        op.create_foreign_key(
            "dependencies_otel_config_id_fkey",
            "dependencies",
            "otel_sync_configs",
            ["otel_config_id"],
            ["id"],
            ondelete="SET NULL",
            source_schema=schema,
            referent_schema=schema,
        )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    if _is_sqlite():
        with op.batch_alter_table("dependencies", schema=schema) as batch_op:
            batch_op.drop_constraint("fk_dependencies_otel_config_id", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_dependencies_otel_config_id",
                "otel_sync_configs",
                ["otel_config_id"],
                ["id"],
            )
    else:
        op.drop_constraint(
            "dependencies_otel_config_id_fkey",
            "dependencies",
            type_="foreignkey",
            schema=schema,
        )
        op.create_foreign_key(
            "dependencies_otel_config_id_fkey",
            "dependencies",
            "otel_sync_configs",
            ["otel_config_id"],
            ["id"],
            source_schema=schema,
            referent_schema=schema,
        )
