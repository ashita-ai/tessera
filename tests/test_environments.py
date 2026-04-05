"""Tests for environment support in assets."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AssetDB, TeamDB


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
