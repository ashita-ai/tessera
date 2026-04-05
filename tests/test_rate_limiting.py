"""Tests for rate limiting enforcement."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import TeamDB
from tessera.main import app
from tessera.models.api_key import APIKeyCreate
from tessera.models.enums import APIKeyScope
from tessera.services.auth import create_api_key


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Client with rate limiting enabled and low thresholds for testing."""
    from tessera.config import settings
    from tessera.db import database

    original_rate_limit_enabled = settings.rate_limit_enabled
    original_rate_limit_read = settings.rate_limit_read
    original_rate_limit_auth = settings.rate_limit_auth

    settings.rate_limit_enabled = True
    settings.rate_limit_read = "2/minute"
    settings.rate_limit_auth = "100/minute"

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    settings.rate_limit_enabled = original_rate_limit_enabled
    settings.rate_limit_read = original_rate_limit_read
    settings.rate_limit_auth = original_rate_limit_auth


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

    async def test_retry_after_reflects_rate_limit_window(
        self, session: AsyncSession, client: AsyncClient
    ):
        """Retry-After header should reflect the configured rate limit window."""
        team, key = await create_team_and_key(session, "retry-after-team", [APIKeyScope.READ])
        headers = {"Authorization": f"Bearer {key}"}

        # Exhaust the limit (2/minute)
        await client.get("/api/v1/assets", headers=headers)
        await client.get("/api/v1/assets", headers=headers)

        # Third request triggers 429
        response = await client.get("/api/v1/assets", headers=headers)
        assert response.status_code == 429
        retry_after = int(response.headers["Retry-After"])
        # The configured limit is "2/minute" → 60-second window
        assert 1 <= retry_after <= 60

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
