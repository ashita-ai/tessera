"""Tests for /api/v1/api-keys endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAPIKeyCreate:
    """Tests for POST /api/v1/api-keys."""

    async def test_create_api_key_success(self, client: AsyncClient):
        """Create an API key successfully."""
        # First create a team
        team_resp = await client.post("/api/v1/teams", json={"name": "api-key-team"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # Create API key
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "test-key",
                "team_id": team_id,
                "scopes": ["read", "write"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-key"
        assert data["team_id"] == team_id
        assert "key" in data  # Raw key only returned on creation
        assert data["key"].startswith("tess_")

    async def test_create_api_key_team_not_found(self, client: AsyncClient):
        """Create API key for nonexistent team fails."""
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "orphan-key",
                "team_id": "00000000-0000-0000-0000-000000000000",
                "scopes": ["read"],
            },
        )
        assert resp.status_code == 404


class TestAPIKeyList:
    """Tests for GET /api/v1/api-keys."""

    async def test_list_api_keys(self, client: AsyncClient):
        """List API keys."""
        # Create a team and API key
        team_resp = await client.post("/api/v1/teams", json={"name": "list-keys-team"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/api-keys",
            json={"name": "list-key-1", "team_id": team_id, "scopes": ["read"]},
        )

        # List keys
        resp = await client.get("/api/v1/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        # Raw key should not be included in list response
        for key in data["keys"]:
            assert "key" not in key or key.get("key") is None

    async def test_list_api_keys_by_team(self, client: AsyncClient):
        """List API keys filtered by team."""
        # Create two teams
        team1_resp = await client.post("/api/v1/teams", json={"name": "keys-team-1"})
        team1_id = team1_resp.json()["id"]
        team2_resp = await client.post("/api/v1/teams", json={"name": "keys-team-2"})
        team2_id = team2_resp.json()["id"]

        # Create keys for each team
        await client.post(
            "/api/v1/api-keys",
            json={"name": "team1-key", "team_id": team1_id, "scopes": ["read"]},
        )
        await client.post(
            "/api/v1/api-keys",
            json={"name": "team2-key", "team_id": team2_id, "scopes": ["read"]},
        )

        # List keys for team1 only
        resp = await client.get(f"/api/v1/api-keys?team_id={team1_id}")
        assert resp.status_code == 200
        data = resp.json()
        # All returned keys should belong to team1
        for key in data["keys"]:
            assert key["team_id"] == team1_id

    async def test_list_api_keys_include_revoked(self, client: AsyncClient):
        """List API keys including revoked ones."""
        # Create team and key
        team_resp = await client.post("/api/v1/teams", json={"name": "revoked-team"})
        team_id = team_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/api-keys",
            json={"name": "revoke-me-key", "team_id": team_id, "scopes": ["read"]},
        )
        key_id = create_resp.json()["id"]

        # Revoke the key
        await client.delete(f"/api/v1/api-keys/{key_id}")

        # List without revoked - should not include revoked key
        resp = await client.get(f"/api/v1/api-keys?team_id={team_id}")
        assert resp.status_code == 200
        data = resp.json()
        key_ids = [k["id"] for k in data["keys"]]
        assert key_id not in key_ids

        # List with revoked included
        resp = await client.get(f"/api/v1/api-keys?team_id={team_id}&include_revoked=true")
        assert resp.status_code == 200
        data = resp.json()
        key_ids = [k["id"] for k in data["keys"]]
        assert key_id in key_ids


class TestAPIKeyGet:
    """Tests for GET /api/v1/api-keys/{key_id}."""

    async def test_get_api_key(self, client: AsyncClient):
        """Get an API key by ID."""
        # Create team and key
        team_resp = await client.post("/api/v1/teams", json={"name": "get-key-team"})
        team_id = team_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/api-keys",
            json={"name": "get-me-key", "team_id": team_id, "scopes": ["read", "write"]},
        )
        key_id = create_resp.json()["id"]

        # Get the key
        resp = await client.get(f"/api/v1/api-keys/{key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == key_id
        assert data["name"] == "get-me-key"
        # Raw key should not be included in get response
        assert "key" not in data or data.get("key") is None

    async def test_get_api_key_not_found(self, client: AsyncClient):
        """Get nonexistent API key returns 404."""
        resp = await client.get("/api/v1/api-keys/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestAPIKeyRevoke:
    """Tests for DELETE /api/v1/api-keys/{key_id}."""

    async def test_revoke_api_key(self, client: AsyncClient):
        """Revoke an API key."""
        # Create team and key
        team_resp = await client.post("/api/v1/teams", json={"name": "revoke-key-team"})
        team_id = team_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/api-keys",
            json={"name": "to-be-revoked", "team_id": team_id, "scopes": ["read"]},
        )
        key_id = create_resp.json()["id"]

        # Revoke the key
        resp = await client.delete(f"/api/v1/api-keys/{key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == key_id
        assert data["revoked_at"] is not None

    async def test_revoke_api_key_not_found(self, client: AsyncClient):
        """Revoke nonexistent API key returns 404."""
        resp = await client.delete("/api/v1/api-keys/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
