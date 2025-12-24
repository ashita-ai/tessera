"""Comprehensive tests for authorization gaps and resource-level permissions."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AssetDB, Base, ContractDB, ProposalDB, TeamDB
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

    original_auth_disabled = settings.auth_disabled
    settings.auth_disabled = False

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    settings.auth_disabled = original_auth_disabled


async def create_team_and_key(session: AsyncSession, name: str, scopes: list[APIKeyScope]):
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()

    key_data = APIKeyCreate(name=f"{name}-key", team_id=team.id, scopes=scopes)
    api_key = await create_api_key(session, key_data)
    return team, api_key.key


class TestResourceLevelAuth:
    """Tests for team-level ownership checks."""

    async def test_producer_cannot_mutate_other_team_asset(
        self, session: AsyncSession, client: AsyncClient
    ):
        team1, key1 = await create_team_and_key(
            session, "team1", [APIKeyScope.READ, APIKeyScope.WRITE]
        )
        team2, _ = await create_team_and_key(
            session, "team2", [APIKeyScope.READ, APIKeyScope.WRITE]
        )

        # Create asset for team2
        asset = AssetDB(fqn="team2.asset", owner_team_id=team2.id)
        session.add(asset)
        await session.flush()

        # Team1 tries to update Team2's asset
        response = await client.patch(
            f"/api/v1/assets/{asset.id}",
            json={"fqn": "stolen.asset"},
            headers={"Authorization": f"Bearer {key1}"},
        )
        assert response.status_code == 403
        error_msg = response.json()["error"]["message"]
        # Improved error message includes team names for better debugging
        assert "Cannot update asset" in error_msg
        assert "team2" in error_msg
        assert "team1" in error_msg

    async def test_consumer_cannot_acknowledge_for_other_team(
        self, session: AsyncSession, client: AsyncClient
    ):
        team1, key1 = await create_team_and_key(
            session, "team1", [APIKeyScope.READ, APIKeyScope.WRITE]
        )
        team2, _ = await create_team_and_key(
            session, "team2", [APIKeyScope.READ, APIKeyScope.WRITE]
        )

        # Create asset for the proposal (required for FK constraint)
        asset = AssetDB(fqn="team2.proposal-asset", owner_team_id=team2.id)
        session.add(asset)
        await session.flush()

        # Create proposal
        proposal = ProposalDB(
            asset_id=asset.id,
            proposed_schema={"type": "object"},
            change_type="major",
            proposed_by=team2.id,
        )
        session.add(proposal)
        await session.flush()

        # Team1 tries to acknowledge on behalf of Team2
        response = await client.post(
            f"/api/v1/proposals/{proposal.id}/acknowledge",
            json={"consumer_team_id": str(team2.id), "response": "approved"},
            headers={"Authorization": f"Bearer {key1}"},
        )
        assert response.status_code == 403
        assert "on behalf of your own team" in response.json()["error"]["message"]

    async def test_registration_must_match_auth_team(
        self, session: AsyncSession, client: AsyncClient
    ):
        team1, key1 = await create_team_and_key(
            session, "team1", [APIKeyScope.READ, APIKeyScope.WRITE]
        )
        team2, _ = await create_team_and_key(
            session, "team2", [APIKeyScope.READ, APIKeyScope.WRITE]
        )

        # Create asset for the contract (required for FK constraint)
        asset = AssetDB(fqn="team2.contract-asset", owner_team_id=team2.id)
        session.add(asset)
        await session.flush()

        # Create contract
        contract = ContractDB(
            asset_id=asset.id, version="1.0.0", schema_def={"type": "object"}, published_by=team2.id
        )
        session.add(contract)
        await session.flush()

        # Team1 tries to register Team2 for a contract
        response = await client.post(
            "/api/v1/registrations",
            params={"contract_id": str(contract.id)},
            json={"consumer_team_id": str(team2.id)},
            headers={"Authorization": f"Bearer {key1}"},
        )
        assert response.status_code == 403
        assert "on behalf of your own team" in response.json()["error"]["message"]

    async def test_admin_bypass_resource_checks(self, session: AsyncSession, client: AsyncClient):
        admin_team, admin_key = await create_team_and_key(session, "admin", [APIKeyScope.ADMIN])
        team2, _ = await create_team_and_key(
            session, "team2", [APIKeyScope.READ, APIKeyScope.WRITE]
        )

        # Create asset for team2
        asset = AssetDB(fqn="team2.asset", owner_team_id=team2.id)
        session.add(asset)
        await session.flush()

        # Admin updates Team2's asset
        response = await client.patch(
            f"/api/v1/assets/{asset.id}",
            json={"fqn": "admin.override"},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert response.status_code == 200
        assert response.json()["fqn"] == "admin.override"


class TestScopeRestrictions:
    """Tests for RequiredRead/Write/Admin scope enforcement."""

    async def test_read_scope_required_for_get(self, session: AsyncSession, client: AsyncClient):
        # Create key with NO scopes
        team, key = await create_team_and_key(session, "no-scope", [])

        response = await client.get("/api/v1/assets", headers={"Authorization": f"Bearer {key}"})
        assert response.status_code == 403
        assert "requires the 'read' scope" in response.json()["error"]["message"]

    async def test_write_scope_required_for_post(self, session: AsyncSession, client: AsyncClient):
        # Create key with only READ scope
        team, key = await create_team_and_key(session, "read-only", [APIKeyScope.READ])

        response = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.asset", "owner_team_id": str(team.id)},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 403
        assert "requires the 'write' scope" in response.json()["error"]["message"]

    async def test_admin_scope_required_for_sync(self, session: AsyncSession, client: AsyncClient):
        # Create key with WRITE scope (but not ADMIN)
        team, key = await create_team_and_key(
            session, "writer", [APIKeyScope.READ, APIKeyScope.WRITE]
        )

        # /sync/dbt requires admin scope
        response = await client.post(
            f"/api/v1/sync/dbt?manifest_path=/tmp/test.json&owner_team_id={team.id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 403
        assert "requires the 'admin' scope" in response.json()["error"]["message"]
