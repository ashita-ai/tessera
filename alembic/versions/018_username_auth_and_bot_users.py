"""Switch auth to username-based, add bot user support, link API keys to users.

Revision ID: 018
Revises: 017
Create Date: 2026-04-01

Adds:
- UserDB.username (unique, not null): Primary login identifier
- UserDB.user_type (not null, default 'human'): HUMAN or BOT
- Makes UserDB.email nullable (bots don't need emails)
- APIKeyDB.user_id (nullable FK to users): Optional user assignment

Backfill: Existing users get their email prefix as username.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Check if we're running against SQLite."""
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # 1. Add username column (nullable initially for backfill)
    op.add_column(
        "users",
        sa.Column("username", sa.String(255), nullable=True),
        schema=schema,
    )

    # 2. Add user_type column with server default
    op.add_column(
        "users",
        sa.Column("user_type", sa.String(20), nullable=False, server_default="human"),
        schema=schema,
    )

    # 3. Backfill username from email (take the part before @)
    bind = op.get_bind()
    if _is_sqlite():
        # SQLite doesn't have split_part, use substr + instr
        bind.execute(
            sa.text(
                "UPDATE users SET username = LOWER(SUBSTR(email, 1, INSTR(email, '@') - 1)) "
                "WHERE username IS NULL"
            )
        )
    else:
        bind.execute(
            sa.text(
                "UPDATE users SET username = LOWER(SPLIT_PART(email, '@', 1)) "
                "WHERE username IS NULL"
            )
        )

    # Handle potential duplicates from backfill by appending a suffix
    # (e.g., two users with alice@foo.com and alice@bar.com)
    if _is_sqlite():
        bind.execute(
            sa.text(
                "UPDATE users SET username = username || '-' "
                "|| LOWER(SUBSTR(HEX(RANDOMBLOB(3)), 1, 6)) "
                "WHERE rowid NOT IN ("
                "  SELECT MIN(rowid) FROM users GROUP BY username"
                ")"
            )
        )
    else:
        bind.execute(
            sa.text(
                "UPDATE users SET username = username || '-' || SUBSTR(MD5(RANDOM()::TEXT), 1, 6) "
                "WHERE id NOT IN ("
                "  SELECT DISTINCT ON (username) id FROM users ORDER BY username, created_at"
                ")"
            )
        )

    # 4. Make username non-nullable and unique
    op.alter_column("users", "username", nullable=False, schema=schema)

    if _is_sqlite():
        # SQLite: create unique index (can't add unique constraint after table creation)
        op.create_index("ix_users_username", "users", ["username"], unique=True)
    else:
        op.create_unique_constraint("uq_users_username", "users", ["username"], schema=schema)

    # 5. Make email nullable
    op.alter_column("users", "email", nullable=True, schema=schema)

    # 6. Add user_id FK to api_keys
    op.add_column(
        "api_keys",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        schema=schema,
    )

    if not _is_sqlite():
        op.create_foreign_key(
            "fk_api_keys_user_id",
            "api_keys",
            "users",
            ["user_id"],
            ["id"],
            source_schema=schema,
            referent_schema=schema,
        )

    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], schema=schema)


def downgrade() -> None:
    schema = None if _is_sqlite() else "core"

    # Remove api_keys.user_id
    op.drop_index("ix_api_keys_user_id", table_name="api_keys", schema=schema)
    if not _is_sqlite():
        op.drop_constraint("fk_api_keys_user_id", "api_keys", type_="foreignkey", schema=schema)
    op.drop_column("api_keys", "user_id", schema=schema)

    # Make email non-nullable again
    op.alter_column("users", "email", nullable=False, schema=schema)

    # Drop username
    if _is_sqlite():
        op.drop_index("ix_users_username", table_name="users")
    else:
        op.drop_constraint("uq_users_username", "users", type_="unique", schema=schema)
    op.drop_column("users", "username", schema=schema)

    # Drop user_type
    op.drop_column("users", "user_type", schema=schema)
