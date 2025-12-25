"""Tests for list registrations endpoint."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AssetDB, Base, ContractDB, RegistrationDB, TeamDB
from tessera.main import app
from tessera.models.enums import RegistrationStatus

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


class TestRegistrationsList:
    """Tests for GET /api/v1/registrations."""

    async def test_list_registrations_basic(self, session: AsyncSession, client: AsyncClient):
        team = TeamDB(name="consumer")
        session.add(team)
        await session.flush()

        # Create some registrations
        # We need a contract first
        asset = AssetDB(fqn="db.table", owner_team_id=team.id)
        session.add(asset)
        await session.flush()

        contract = ContractDB(
            asset_id=asset.id, version="1.0.0", schema_def={"type": "object"}, published_by=team.id
        )
        session.add(contract)
        await session.flush()

        reg1 = RegistrationDB(
            contract_id=contract.id, consumer_team_id=team.id, status=RegistrationStatus.ACTIVE
        )
        session.add(reg1)
        await session.flush()

        response = await client.get("/api/v1/registrations")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["consumer_team_id"] == str(team.id)

    async def test_list_registrations_filters(self, session: AsyncSession, client: AsyncClient):
        team1 = TeamDB(name="consumer1")
        team2 = TeamDB(name="consumer2")
        session.add_all([team1, team2])
        await session.flush()

        asset = AssetDB(fqn="db.table", owner_team_id=team1.id)
        session.add(asset)
        await session.flush()

        contract = ContractDB(
            asset_id=asset.id, version="1.0.0", schema_def={"type": "object"}, published_by=team1.id
        )
        session.add(contract)
        await session.flush()

        reg1 = RegistrationDB(
            contract_id=contract.id, consumer_team_id=team1.id, status=RegistrationStatus.ACTIVE
        )
        reg2 = RegistrationDB(
            contract_id=contract.id, consumer_team_id=team2.id, status=RegistrationStatus.MIGRATING
        )
        session.add_all([reg1, reg2])
        await session.flush()

        # Filter by consumer_team_id
        response = await client.get(
            "/api/v1/registrations", params={"consumer_team_id": str(team1.id)}
        )
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["consumer_team_id"] == str(team1.id)

        # Filter by status
        response = await client.get("/api/v1/registrations", params={"status": "migrating"})
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["status"] == "migrating"
