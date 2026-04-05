"""Migrate dependencies.source from varchar to native enum.

Revision ID: 030
Revises: 029
Create Date: 2026-04-05

Migration 023 added the ``source`` column as ``String(50)``, but the
SQLAlchemy model now declares it as ``Enum(DependencySource)``. On
PostgreSQL, the ORM expects a native enum type that was never created.
This migration bridges the gap: it creates the ``dependencysource`` enum,
converts existing varchar values, and alters the column type in-place.

SQLite stores enums as plain text so no schema change is needed there.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "030"
down_revision: str = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM_VALUES = ("manual", "otel", "inferred")


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        return

    schema = "core"
    qualified_table = f"{schema}.dependencies"

    op.execute(
        "CREATE TYPE dependencysource AS ENUM " f"({', '.join(repr(v) for v in _ENUM_VALUES)})"
    )

    op.execute(
        f"ALTER TABLE {qualified_table} "
        "ALTER COLUMN source TYPE dependencysource "
        "USING source::dependencysource"
    )


def downgrade() -> None:
    if _is_sqlite():
        return

    schema = "core"
    qualified_table = f"{schema}.dependencies"

    op.execute(
        f"ALTER TABLE {qualified_table} "
        "ALTER COLUMN source TYPE VARCHAR(50) "
        "USING source::text"
    )

    op.execute("DROP TYPE IF EXISTS dependencysource")
