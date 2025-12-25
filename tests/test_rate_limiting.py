"""Tests for rate limiting enforcement."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import Base, TeamDB
from tessera.main import app
from tessera.models.api_key import APIKeyCreate
from tessera.models.enums import APIKeyScope
from tessera.services.auth import create_api_key

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


@pytest.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from tessera.config import settings
    from tessera.db import database

    # Enable rate limiting for tests
    original_rate_limit_enabled = settings.rate_limit_enabled
    original_rate_limit_read = settings.rate_limit_read

    settings.rate_limit_enabled = True
    settings.rate_limit_read = "2/minute"  # Low limit for testing

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    settings.rate_limit_enabled = original_rate_limit_enabled
    settings.rate_limit_read = original_rate_limit_read


async def create_team_and_key(session: AsyncSession, name: str, scopes: list[APIKeyScope]):
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()

    key_data = APIKeyCreate(name=f"{name}-key", team_id=team.id, scopes=scopes)
    api_key = await create_api_key(session, key_data)
    return team, api_key.key


class TestRateLimiting:
    """Tests for rate limit enforcement."""

    async def test_rate_limit_exceeded(self, session: AsyncSession, client: AsyncClient):
        team, key = await create_team_and_key(session, "rate-limit-team", [APIKeyScope.READ])
        headers = {"Authorization": f"Bearer {key}"}

        # First request - success
        response = await client.get("/api/v1/assets", headers=headers)
        assert response.status_code == 200

        # Second request - success
        response = await client.get("/api/v1/assets", headers=headers)
        assert response.status_code == 200

        # Third request - rate limit exceeded
        response = await client.get("/api/v1/assets", headers=headers)
        assert response.status_code == 429
        # Check for Retry-After header (required by TODO.md)
        assert "Retry-After" in response.headers
        assert "Too Many Requests" in response.text or "RATE_LIMIT_EXCEEDED" in response.text

    async def test_rate_limit_disabled(self, session: AsyncSession):
        """Test that rate limiting can be disabled."""
        from tessera.config import settings
        from tessera.db import database

        # Disable rate limiting
        original_rate_limit_enabled = settings.rate_limit_enabled
        settings.rate_limit_enabled = False

        team, key = await create_team_and_key(session, "no-limit-team", [APIKeyScope.READ])
        headers = {"Authorization": f"Bearer {key}"}

        async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
            yield session

        app.dependency_overrides[database.get_session] = get_test_session

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Make many requests - should all succeed when rate limiting is disabled
                for i in range(10):
                    response = await client.get("/api/v1/assets", headers=headers)
                    assert (
                        response.status_code == 200
                    ), f"Request {i + 1} should succeed when rate limiting is disabled"
        finally:
            app.dependency_overrides.clear()
            settings.rate_limit_enabled = original_rate_limit_enabled
