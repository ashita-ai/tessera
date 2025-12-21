"""Tests for /api/v1/teams endpoints."""

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


class TestTeamsAPI:
    """Tests for /api/v1/teams endpoints."""

    async def test_create_team(self, client: AsyncClient):
        """Create a team."""
        resp = await client.post("/api/v1/teams", json={"name": "data-platform"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "data-platform"
        assert "id" in data

    async def test_create_duplicate_team_fails(self, client: AsyncClient):
        """Creating a team with duplicate name should fail."""
        await client.post("/api/v1/teams", json={"name": "unique-team"})
        resp = await client.post("/api/v1/teams", json={"name": "unique-team"})
        assert resp.status_code == 409

    async def test_list_teams(self, client: AsyncClient):
        """List all teams."""
        await client.post("/api/v1/teams", json={"name": "team-1"})
        await client.post("/api/v1/teams", json={"name": "team-2"})
        resp = await client.get("/api/v1/teams")
        assert resp.status_code == 200
        teams = resp.json()
        assert len(teams) >= 2

    async def test_get_team(self, client: AsyncClient):
        """Get a team by ID."""
        create_resp = await client.post("/api/v1/teams", json={"name": "get-test"})
        team_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/teams/{team_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-test"

    async def test_get_nonexistent_team(self, client: AsyncClient):
        """Getting a nonexistent team should 404."""
        resp = await client.get("/api/v1/teams/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_update_team(self, client: AsyncClient):
        """Update a team."""
        team_resp = await client.post("/api/v1/teams", json={"name": "update-me-team"})
        team_id = team_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/teams/{team_id}",
            json={"name": "updated-team-name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "updated-team-name"

    async def test_update_team_not_found(self, client: AsyncClient):
        """Updating nonexistent team should 404."""
        resp = await client.patch(
            "/api/v1/teams/00000000-0000-0000-0000-000000000000",
            json={"name": "new-name"},
        )
        assert resp.status_code == 404
