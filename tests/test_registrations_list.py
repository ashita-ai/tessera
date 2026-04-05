"""Tests for list registrations endpoint."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AssetDB, ContractDB, RegistrationDB, TeamDB
from tessera.models.enums import RegistrationStatus


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
