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

# PostgreSQL marker convention: tests requiring PostgreSQL-specific behavior
# (FOR UPDATE, CREATE SCHEMA, etc.) must use @pytest.mark.postgres.
# CI runs only marked tests on PostgreSQL; everything else runs on SQLite.
# If you use @pytest.mark.skipif(_USE_SQLITE, ...), also add @pytest.mark.postgres.

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
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

    if _USE_SQLITE:
        # SQLite does not enforce FK constraints by default; enable them so
        # ON DELETE SET NULL / CASCADE behaves the same as PostgreSQL.
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    yield engine
    await engine.dispose()


def create_tables(connection):
    """Create all tables, dropping existing ones first to ensure fresh schema."""
    if not _USE_SQLITE:
        Base.metadata.drop_all(connection)
    Base.metadata.create_all(connection, checkfirst=True)


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create tables and provide a test session."""
    async with test_engine.begin() as conn:
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
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session(test_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Alias for test_session — many test files inject 'session' directly."""
    yield test_session


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client that shares the test session with the app."""
    from tessera.config import settings
    from tessera.db import database

    original_auth_disabled = settings.auth_disabled
    settings.auth_disabled = True

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    settings.auth_disabled = original_auth_disabled


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
