from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AssetDB, ContractDB, RegistrationDB, TeamDB
from tessera.main import app
from tessera.models.api_key import APIKeyCreate
from tessera.models.enums import APIKeyScope, ContractStatus, RegistrationStatus
from tessera.services.auth import create_api_key
from tessera.services.batch import fetch_team_names


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Auth-enabled client sharing the test session for soft delete verification."""
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


@pytest.mark.asyncio
async def test_soft_delete_asset(session: AsyncSession, client: AsyncClient):
    # 1. Create a team and asset
    team, key = await create_team_and_key(
        session, "delete-team", [APIKeyScope.READ, APIKeyScope.WRITE]
    )

    asset = AssetDB(fqn="delete.me", owner_team_id=team.id, environment="production")
    session.add(asset)
    await session.commit()
    asset_id = asset.id

    # 2. Delete the asset
    response = await client.delete(
        f"/api/v1/assets/{asset_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 204

    # 3. Verify it's hidden from list
    response = await client.get("/api/v1/assets", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assets = response.json()["results"]
    assert not any(a["id"] == str(asset_id) for a in assets)

    # 4. Verify it's hidden from search
    response = await client.get(
        "/api/v1/assets/search", params={"q": "delete"}, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0

    # 5. Verify it's hidden from GET by ID
    response = await client.get(
        f"/api/v1/assets/{asset_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 404

    # 6. Verify it's still in the DB but with deleted_at set
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    db_asset = result.scalar_one()
    assert db_asset.deleted_at is not None


@pytest.mark.asyncio
async def test_restore_asset(session: AsyncSession, client: AsyncClient):
    # 1. Create and soft-delete an asset
    admin_team, admin_key = await create_team_and_key(session, "admin", [APIKeyScope.ADMIN])
    team, key = await create_team_and_key(session, "user", [APIKeyScope.READ, APIKeyScope.WRITE])

    asset = AssetDB(
        fqn="restore.me",
        owner_team_id=team.id,
        environment="production",
        deleted_at=datetime.now(UTC),
    )
    session.add(asset)
    await session.commit()
    asset_id = asset.id

    # 2. Restore the asset (admin only)
    response = await client.post(
        f"/api/v1/assets/{asset_id}/restore", headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    assert response.json()["fqn"] == "restore.me"

    # 3. Verify it's visible again
    response = await client.get(
        f"/api/v1/assets/{asset_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200

    # 4. Verify deleted_at is None in DB
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    db_asset = result.scalar_one()
    assert db_asset.deleted_at is None


@pytest.mark.asyncio
async def test_soft_delete_team(session: AsyncSession, client: AsyncClient):
    # 1. Create a team
    admin_team, admin_key = await create_team_and_key(session, "admin", [APIKeyScope.ADMIN])
    team, _ = await create_team_and_key(session, "delete-me-team", [APIKeyScope.READ])
    team_id = team.id

    # 2. Delete the team (admin only)
    response = await client.delete(
        f"/api/v1/teams/{team_id}", headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 204

    # 3. Verify it's hidden from list
    response = await client.get("/api/v1/teams", headers={"Authorization": f"Bearer {admin_key}"})
    assert response.status_code == 200
    teams = response.json()["results"]
    assert not any(t["id"] == str(team_id) for t in teams)

    # 4. Verify it's hidden from GET by ID
    response = await client.get(
        f"/api/v1/teams/{team_id}", headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_restore_team(session: AsyncSession, client: AsyncClient):
    # 1. Create and soft-delete a team
    admin_team, admin_key = await create_team_and_key(session, "admin", [APIKeyScope.ADMIN])

    team = TeamDB(name="Restore Team", deleted_at=datetime.now(UTC))
    session.add(team)
    await session.commit()
    team_id = team.id

    # 2. Restore the team
    response = await client.post(
        f"/api/v1/teams/{team_id}/restore", headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200

    # 3. Verify it's visible again
    response = await client.get(
        f"/api/v1/teams/{team_id}", headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_fetch_team_names_excludes_deleted(session: AsyncSession):
    """fetch_team_names should not return soft-deleted teams."""
    team_active = TeamDB(name="active-team")
    team_deleted = TeamDB(name="deleted-team", deleted_at=datetime.now(UTC))
    session.add_all([team_active, team_deleted])
    await session.flush()

    names = await fetch_team_names(session, [team_active.id, team_deleted.id])
    assert team_active.id in names
    assert team_deleted.id not in names
    assert names[team_active.id] == "active-team"


@pytest.mark.asyncio
async def test_lineage_excludes_deleted_asset(session: AsyncSession, client: AsyncClient):
    """Lineage endpoint should return 404 for soft-deleted assets."""
    team, key = await create_team_and_key(
        session, "lineage-team", [APIKeyScope.READ, APIKeyScope.WRITE]
    )
    asset = AssetDB(
        fqn="lineage.deleted",
        owner_team_id=team.id,
        environment="production",
        deleted_at=datetime.now(UTC),
    )
    session.add(asset)
    await session.flush()

    response = await client.get(
        f"/api/v1/assets/{asset.id}/lineage",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lineage_excludes_deleted_registrations(session: AsyncSession, client: AsyncClient):
    """Lineage downstream should not include soft-deleted registrations."""
    team, key = await create_team_and_key(
        session, "lineage-reg-team", [APIKeyScope.READ, APIKeyScope.WRITE]
    )
    consumer_team = TeamDB(name="consumer-team")
    session.add(consumer_team)
    await session.flush()

    asset = AssetDB(fqn="lineage.reg.test", owner_team_id=team.id, environment="production")
    session.add(asset)
    await session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object"},
        compatibility_mode="backward",
        status=ContractStatus.ACTIVE,
        published_by=team.id,
    )
    session.add(contract)
    await session.flush()

    # Create one active and one deleted registration
    reg_active = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer_team.id,
        status=RegistrationStatus.ACTIVE,
    )
    reg_deleted = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=team.id,
        status=RegistrationStatus.ACTIVE,
        deleted_at=datetime.now(UTC),
    )
    session.add_all([reg_active, reg_deleted])
    await session.flush()

    response = await client.get(
        f"/api/v1/assets/{asset.id}/lineage",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 200
    data = response.json()
    # Only the active registration should appear in downstream
    downstream_team_ids = [d["team_id"] for d in data.get("downstream", [])]
    assert str(consumer_team.id) in downstream_team_ids
    assert str(team.id) not in downstream_team_ids
