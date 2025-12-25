"""Tests for recursive impact analysis."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AssetDB, AssetDependencyDB, Base, ContractDB, RegistrationDB, TeamDB
from tessera.main import app
from tessera.models.enums import DependencyType, RegistrationStatus

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


class TestRecursiveImpact:
    """Tests for recursive impact analysis."""

    async def test_recursive_impact_depth_3(self, session: AsyncSession, client: AsyncClient):
        # Setup: Team -> Asset A -> Asset B -> Asset C -> Team Consumer
        team = TeamDB(name="producer-team")
        consumer_team = TeamDB(name="consumer-team")
        session.add_all([team, consumer_team])
        await session.flush()

        asset_a = AssetDB(fqn="asset.a", owner_team_id=team.id)
        asset_b = AssetDB(fqn="asset.b", owner_team_id=team.id)
        asset_c = AssetDB(fqn="asset.c", owner_team_id=team.id)
        session.add_all([asset_a, asset_b, asset_c])
        await session.flush()

        # Dependencies: B depends on A, C depends on B
        dep_ba = AssetDependencyDB(
            dependent_asset_id=asset_b.id,
            dependency_asset_id=asset_a.id,
            dependency_type=DependencyType.TRANSFORMS,
        )
        dep_cb = AssetDependencyDB(
            dependent_asset_id=asset_c.id,
            dependency_asset_id=asset_b.id,
            dependency_type=DependencyType.TRANSFORMS,
        )
        session.add_all([dep_ba, dep_cb])

        # Active contract for A
        contract_a = ContractDB(
            asset_id=asset_a.id,
            version="1.0.0",
            schema_def={"type": "object", "properties": {"id": {"type": "integer"}}},
            published_by=team.id,
        )
        # Active contract for C
        contract_c = ContractDB(
            asset_id=asset_c.id,
            version="1.0.0",
            schema_def={"type": "object"},
            published_by=team.id,
        )
        session.add_all([contract_a, contract_c])
        await session.flush()

        # Registration for C
        reg_c = RegistrationDB(
            contract_id=contract_c.id,
            consumer_team_id=consumer_team.id,
            status=RegistrationStatus.ACTIVE,
        )
        session.add(reg_c)
        await session.flush()

        # Analyze impact of breaking change on A
        proposed_schema = {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        }  # Breaking change

        response = await client.post(f"/api/v1/assets/{asset_a.id}/impact", json=proposed_schema)

        assert response.status_code == 200
        data = response.json()

        # Should see asset B and C in impacted_assets
        impacted_asset_fqns = [a["fqn"] for a in data["impacted_assets"]]
        assert "asset.b" in impacted_asset_fqns
        assert "asset.c" in impacted_asset_fqns

        # Should see consumer_team in impacted_consumers (via C)
        impacted_team_names = [t["team_name"] for t in data["impacted_consumers"]]
        assert "consumer-team" in impacted_team_names

    async def test_circular_dependency_safety(self, session: AsyncSession, client: AsyncClient):
        # Setup: A -> B -> A (Circular)
        team = TeamDB(name="producer-team")
        session.add(team)
        await session.flush()

        asset_a = AssetDB(fqn="asset.a", owner_team_id=team.id)
        asset_b = AssetDB(fqn="asset.b", owner_team_id=team.id)
        session.add_all([asset_a, asset_b])
        await session.flush()

        dep_ab = AssetDependencyDB(
            dependent_asset_id=asset_b.id,
            dependency_asset_id=asset_a.id,
            dependency_type=DependencyType.TRANSFORMS,
        )
        dep_ba = AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_b.id,
            dependency_type=DependencyType.TRANSFORMS,
        )
        session.add_all([dep_ab, dep_ba])

        contract_a = ContractDB(
            asset_id=asset_a.id,
            version="1.0.0",
            schema_def={"type": "object"},
            published_by=team.id,
        )
        session.add(contract_a)
        await session.flush()

        # This should not hang or crash
        response = await client.post(
            f"/api/v1/assets/{asset_a.id}/impact",
            json={"type": "object", "properties": {"new": {"type": "string"}}},
        )
        assert response.status_code == 200
