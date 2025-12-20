"""Pytest fixtures for Tessera tests."""

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import Base
from tessera.main import app


# Load .env to get database URL
from dotenv import load_dotenv
load_dotenv()

# Support both PostgreSQL and SQLite
# SQLite: DATABASE_URL=sqlite+aiosqlite:///./test.db or sqlite+aiosqlite:///:memory:
# PostgreSQL: DATABASE_URL=postgresql+asyncpg://user:pass@host/db
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///:memory:"  # Default to in-memory SQLite for fast tests
)

_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio for async tests."""
    return "asyncio"


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
    """Create all tables, checking if they exist first."""
    Base.metadata.create_all(connection, checkfirst=True)


def drop_tables(connection):
    """Drop all tables."""
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
    """Create a test client with isolated database."""
    from tessera.db import database

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
        "properties": {
            name: {"type": typ} for name, typ in properties.items()
        },
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
