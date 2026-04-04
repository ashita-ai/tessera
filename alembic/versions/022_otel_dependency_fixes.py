"""Fix OTEL dependency unique constraint and add config scoping.

Revision ID: 022
Revises: 021
Create Date: 2026-04-04

Fixes two issues in the OTEL dependency discovery schema:

1. Adds ``source`` to the ``uq_dependency_edge`` unique constraint so that
   MANUAL and OTEL rows can coexist for the same (dependent, dependency, type)
   edge. This enables the reconciliation "both" bucket.

2. Adds ``otel_config_id`` FK on ``dependencies`` so that stale-marking is
   scoped to the config that discovered each dependency, preventing one
   config's sync from incorrectly marking another config's deps as stale.
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

    if _is_sqlite():
        # SQLite doesn't support ALTER TABLE DROP CONSTRAINT, so use batch mode
        with op.batch_alter_table("dependencies", schema=schema) as batch_op:
            batch_op.drop_constraint("uq_dependency_edge", type_="unique")
            batch_op.create_unique_constraint(
                "uq_dependency_edge",
                ["dependent_asset_id", "dependency_asset_id", "dependency_type", "source"],
            )
            batch_op.add_column(sa.Column("otel_config_id", sa.Uuid(), nullable=True))
    else:
        op.drop_constraint("uq_dependency_edge", "dependencies", type_="unique", schema=schema)
        op.create_unique_constraint(
            "uq_dependency_edge",
            "dependencies",
            ["dependent_asset_id", "dependency_asset_id", "dependency_type", "source"],
            schema=schema,
        )
        op.add_column(
            "dependencies",
            sa.Column(
                "otel_config_id",
                sa.Uuid(),
                sa.ForeignKey("otel_sync_configs.id"),
                nullable=True,
            ),
            schema=schema,
        )
        op.create_index(
            "idx_dependency_otel_config",
            "dependencies",
            ["otel_config_id"],
            schema=schema,
        )


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    if _is_sqlite():
        with op.batch_alter_table("dependencies", schema=schema) as batch_op:
            batch_op.drop_column("otel_config_id")
            batch_op.drop_constraint("uq_dependency_edge", type_="unique")
            batch_op.create_unique_constraint(
                "uq_dependency_edge",
                ["dependent_asset_id", "dependency_asset_id", "dependency_type"],
            )
    else:
        op.drop_index("idx_dependency_otel_config", table_name="dependencies", schema=schema)
        op.drop_column("dependencies", "otel_config_id", schema=schema)
        op.drop_constraint("uq_dependency_edge", "dependencies", type_="unique", schema=schema)
        op.create_unique_constraint(
            "uq_dependency_edge",
            "dependencies",
            ["dependent_asset_id", "dependency_asset_id", "dependency_type"],
            schema=schema,
        )
