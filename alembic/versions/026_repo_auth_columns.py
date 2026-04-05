"""Add per-repo git_token and ssh_key columns.

Revision ID: 026
Revises: 025
Create Date: 2026-04-04

Adds optional authentication columns to repos so each repository can
have its own git token (for HTTPS) or SSH deploy key, instead of
relying solely on the global TESSERA_GIT_TOKEN setting.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "026"
down_revision: str = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    if _is_sqlite():
        with op.batch_alter_table("repos", schema=schema) as batch_op:
            batch_op.add_column(sa.Column("git_token", sa.String(500), nullable=True))
            batch_op.add_column(sa.Column("ssh_key", sa.Text(), nullable=True))
    else:
        op.add_column("repos", sa.Column("git_token", sa.String(500), nullable=True), schema=schema)
        op.add_column("repos", sa.Column("ssh_key", sa.Text(), nullable=True), schema=schema)


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    if _is_sqlite():
        with op.batch_alter_table("repos", schema=schema) as batch_op:
            batch_op.drop_column("ssh_key")
            batch_op.drop_column("git_token")
    else:
        op.drop_column("repos", "ssh_key", schema=schema)
        op.drop_column("repos", "git_token", schema=schema)
