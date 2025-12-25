"""Tests for environment support in assets."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AssetDB, Base, TeamDB
from tessera.main import app

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

    original_auth_disabled = settings.auth_disabled
    settings.auth_disabled = True  # Disable auth for simpler setup

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    settings.auth_disabled = original_auth_disabled


class TestAssetEnvironments:
    """Tests for environment support in assets."""

    async def test_create_asset_with_environment(self, session: AsyncSession, client: AsyncClient):
        team = TeamDB(name="team1")
        session.add(team)
        await session.flush()

        response = await client.post(
            "/api/v1/assets",
            json={"fqn": "dev.asset", "owner_team_id": str(team.id), "environment": "dev"},
        )
        assert response.status_code == 201
        assert response.json()["environment"] == "dev"

    async def test_list_assets_filter_by_environment(
        self, session: AsyncSession, client: AsyncClient
    ):
        team = TeamDB(name="team1")
        session.add(team)
        await session.flush()

        # Create assets in different environments
        asset_prod = AssetDB(fqn="prod.asset", owner_team_id=team.id, environment="production")
        asset_dev = AssetDB(fqn="dev.asset", owner_team_id=team.id, environment="dev")
        session.add_all([asset_prod, asset_dev])
        await session.flush()

        # Filter by environment=production
        response = await client.get("/api/v1/assets", params={"environment": "production"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["environment"] == "production"

        # Filter by environment=dev
        response = await client.get("/api/v1/assets", params={"environment": "dev"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["environment"] == "dev"

    async def test_search_assets_filter_by_environment(
        self, session: AsyncSession, client: AsyncClient
    ):
        team = TeamDB(name="team1")
        session.add(team)
        await session.flush()

        asset_prod = AssetDB(
            fqn="analytics.orders", owner_team_id=team.id, environment="production"
        )
        asset_dev = AssetDB(fqn="analytics.orders", owner_team_id=team.id, environment="dev")
        session.add_all([asset_prod, asset_dev])
        await session.flush()

        response = await client.get(
            "/api/v1/assets/search", params={"q": "orders", "environment": "production"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["environment"] == "production"
