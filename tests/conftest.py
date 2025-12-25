"""Pytest fixtures for Tessera tests."""

import os
from collections.abc import AsyncGenerator
from typing import Any

# IMPORTANT: Set environment variables BEFORE importing tessera modules
# This ensures settings are loaded with test configuration
from dotenv import load_dotenv

load_dotenv()

# Disable auth for tests by default (individual auth tests can override)
# Must be set before importing any tessera modules
os.environ["AUTH_DISABLED"] = "true"
# Disable rate limiting for tests by default
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Disable Redis for tests by default (faster, tests should mock Redis when needed)
if "REDIS_URL" not in os.environ:
    os.environ["REDIS_URL"] = ""

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tessera.db.models import Base  # noqa: E402
from tessera.main import app  # noqa: E402

# Support both PostgreSQL and SQLite
# SQLite: DATABASE_URL=sqlite+aiosqlite:///./test.db or sqlite+aiosqlite:///:memory:
# PostgreSQL: DATABASE_URL=postgresql+asyncpg://user:pass@host/db
# Default to SQLite for fast tests - override with DATABASE_URL env var if needed
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",  # Default to in-memory SQLite for fast tests
)
# Ensure DATABASE_URL is set for tests if not already set
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    connect_args = {}
    if _USE_SQLITE:
        # SQLite needs check_same_thread=False for async
        connect_args = {"check_same_thread": False}

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args=connect_args,
    )
    yield engine
    await engine.dispose()


def create_tables(connection):
    """Create all tables, dropping existing ones first to ensure fresh schema."""
    # Drop all tables first to ensure we have a clean schema
    # This is important for PostgreSQL where schema might be stale
    if not _USE_SQLITE:
        # Drop all tables with CASCADE first
        Base.metadata.drop_all(connection)
    Base.metadata.create_all(connection, checkfirst=True)


def drop_tables(connection):
    """Drop all tables."""
    # For PostgreSQL, drop with CASCADE to handle type dependencies
    if not _USE_SQLITE:
        # Drop all tables with CASCADE to handle dependencies
        from sqlalchemy import inspect

        inspector = inspect(connection)
        tables = inspector.get_table_names(schema="core")
        tables.extend(inspector.get_table_names(schema="workflow"))
        tables.extend(inspector.get_table_names(schema="audit"))
        for table in tables:
            try:
                connection.execute(text(f'DROP TABLE IF EXISTS core."{table}" CASCADE'))
            except Exception:
                pass
            try:
                connection.execute(text(f'DROP TABLE IF EXISTS workflow."{table}" CASCADE'))
            except Exception:
                pass
            try:
                connection.execute(text(f'DROP TABLE IF EXISTS audit."{table}" CASCADE'))
            except Exception:
                pass
        # Also drop types that might have dependencies
        try:
            connection.execute(text("DROP TYPE IF EXISTS dependencytype CASCADE"))
        except Exception:
            pass
    Base.metadata.drop_all(connection)


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create tables and provide a test session."""
    async with test_engine.begin() as conn:
        if not _USE_SQLITE:
            # PostgreSQL: Create schemas
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(create_tables)

    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()

    # Clean up tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(drop_tables)


@pytest.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with isolated database and auth disabled."""
    from tessera.config import settings
    from tessera.db import database

    # Disable auth for general tests
    original_auth_disabled = settings.auth_disabled
    settings.auth_disabled = True

    # Create schemas and tables
    async with test_engine.begin() as conn:
        if not _USE_SQLITE:
            # PostgreSQL: Create schemas
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(create_tables)

    # Create session maker for this engine
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Override the get_session dependency
    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[database.get_session] = get_test_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()

    # Restore original auth setting
    settings.auth_disabled = original_auth_disabled

    # Clean up tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(drop_tables)


# Sample data factories


def make_team(name: str = "test-team", **kwargs) -> dict[str, Any]:
    """Create team request data."""
    return {"name": name, **kwargs}


def make_asset(fqn: str, owner_team_id: str, **kwargs) -> dict[str, Any]:
    """Create asset request data."""
    return {"fqn": fqn, "owner_team_id": owner_team_id, **kwargs}


def make_schema(**properties) -> dict[str, Any]:
    """Create a JSON schema with given properties."""
    return {
        "type": "object",
        "properties": {name: {"type": typ} for name, typ in properties.items()},
        "required": list(properties.keys()),
    }


def make_contract(version: str, schema: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Create contract request data."""
    return {
        "version": version,
        "schema": schema,
        "compatibility_mode": kwargs.get("compatibility_mode", "backward"),
        **kwargs,
    }
