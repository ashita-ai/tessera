"""Alembic environment configuration."""

import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from tessera.db.models import Base

# Load environment variables
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with environment variable if set
database_url = os.environ.get("DATABASE_URL")
if database_url:
    # Convert async URL to sync for Alembic if needed
    if database_url.startswith("postgresql+asyncpg"):
        database_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def _is_sync_url(url: str) -> bool:
    """Return True if the URL uses a synchronous driver (e.g. plain sqlite)."""
    return url.startswith("sqlite:///") or url.startswith("postgresql+psycopg2")


def run_migrations_sync() -> None:
    """Run migrations with a synchronous engine (SQLite, psycopg2)."""
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = config.get_main_option("sqlalchemy.url") or ""
    if _is_sync_url(url):
        run_migrations_sync()
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
