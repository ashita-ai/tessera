"""Add trigram indexes for search performance.

Revision ID: 006
Revises: 005
Create Date: 2025-12-29
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    """Create trigram indexes for ILIKE search."""
    if _is_sqlite():
        return

    schema = "core"
    schema_prefix = f"{schema}."

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_teams_name_trgm "
        f"ON {schema_prefix}teams USING gin (name gin_trgm_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_users_name_trgm "
        f"ON {schema_prefix}users USING gin (name gin_trgm_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_users_email_trgm "
        f"ON {schema_prefix}users USING gin (email gin_trgm_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_assets_fqn_trgm "
        f"ON {schema_prefix}assets USING gin (fqn gin_trgm_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_contracts_version_trgm "
        f"ON {schema_prefix}contracts USING gin (version gin_trgm_ops)"
    )


def downgrade() -> None:
    """Drop trigram indexes."""
    if _is_sqlite():
        return

    schema = "core"
    schema_prefix = f"{schema}."

    op.execute(f"DROP INDEX IF EXISTS {schema_prefix}ix_contracts_version_trgm")
    op.execute(f"DROP INDEX IF EXISTS {schema_prefix}ix_assets_fqn_trgm")
    op.execute(f"DROP INDEX IF EXISTS {schema_prefix}ix_users_email_trgm")
    op.execute(f"DROP INDEX IF EXISTS {schema_prefix}ix_users_name_trgm")
    op.execute(f"DROP INDEX IF EXISTS {schema_prefix}ix_teams_name_trgm")
