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

    async def test_update_team_put(self, client: AsyncClient):
        """Update a team using PUT."""
        team_resp = await client.post("/api/v1/teams", json={"name": "put-team"})
        team_id = team_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/teams/{team_id}",
            json={"name": "put-team-updated"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "put-team-updated"

    async def test_update_team_not_found(self, client: AsyncClient):
        """Updating nonexistent team should 404."""
        resp = await client.patch(
            "/api/v1/teams/00000000-0000-0000-0000-000000000000",
            json={"name": "new-name"},
        )
        assert resp.status_code == 404

    async def test_update_team_metadata(self, client: AsyncClient):
        """Update a team's metadata."""
        team_resp = await client.post("/api/v1/teams", json={"name": "meta-team"})
        team_id = team_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/teams/{team_id}",
            json={"metadata": {"slack_channel": "#data-team"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["slack_channel"] == "#data-team"

    async def test_list_teams_with_name_filter(self, client: AsyncClient):
        """List teams with name filter."""
        await client.post("/api/v1/teams", json={"name": "alpha-team"})
        await client.post("/api/v1/teams", json={"name": "beta-team"})
        await client.post("/api/v1/teams", json={"name": "gamma-squad"})

        resp = await client.get("/api/v1/teams?name=team")
        assert resp.status_code == 200
        data = resp.json()
        # Should match alpha-team and beta-team but not gamma-squad
        names = [t["name"] for t in data["results"]]
        assert "alpha-team" in names
        assert "beta-team" in names

    async def test_list_teams_with_pagination(self, client: AsyncClient):
        """List teams with pagination."""
        for i in range(5):
            await client.post("/api/v1/teams", json={"name": f"page-team-{i}"})

        resp = await client.get("/api/v1/teams?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert data["total"] >= 5

    async def test_list_teams_with_asset_count(self, client: AsyncClient):
        """List teams includes asset count."""
        team_resp = await client.post("/api/v1/teams", json={"name": "asset-count-team"})
        team_id = team_resp.json()["id"]

        # Create an asset for the team
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.asset_count_test",
                "owner_team_id": team_id,
            },
        )

        resp = await client.get("/api/v1/teams")
        assert resp.status_code == 200
        teams = resp.json()["results"]
        team = next(t for t in teams if t["id"] == team_id)
        assert team["asset_count"] == 1


class TestDeleteTeam:
    """Tests for DELETE /api/v1/teams/{team_id}."""

    async def test_delete_team_success(self, client: AsyncClient):
        """Delete a team with no assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "delete-me"})
        team_id = team_resp.json()["id"]

        resp = await client.delete(f"/api/v1/teams/{team_id}")
        assert resp.status_code == 204

        # Verify team is soft deleted (not found via regular get)
        get_resp = await client.get(f"/api/v1/teams/{team_id}")
        assert get_resp.status_code == 404

    async def test_delete_team_not_found(self, client: AsyncClient):
        """Delete nonexistent team returns 404."""
        resp = await client.delete("/api/v1/teams/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_delete_team_with_assets_fails(self, client: AsyncClient):
        """Delete team with assets fails without force flag."""
        team_resp = await client.post("/api/v1/teams", json={"name": "has-assets"})
        team_id = team_resp.json()["id"]

        # Create an asset for the team
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.blocking_asset",
                "owner_team_id": team_id,
            },
        )

        resp = await client.delete(f"/api/v1/teams/{team_id}")
        assert resp.status_code == 409
        data = resp.json()
        # HTTPException is wrapped by error handler into {"error": {...}} format
        assert data["error"]["code"] == "TEAM_HAS_ASSETS"
        assert "asset" in data["error"]["message"].lower()

    async def test_delete_team_with_assets_force(self, client: AsyncClient):
        """Delete team with assets succeeds with force=true."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-delete"})
        team_id = team_resp.json()["id"]

        # Create an asset for the team
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.force_delete_asset",
                "owner_team_id": team_id,
            },
        )

        resp = await client.delete(f"/api/v1/teams/{team_id}?force=true")
        assert resp.status_code == 204


class TestRestoreTeam:
    """Tests for POST /api/v1/teams/{team_id}/restore."""

    async def test_restore_team_success(self, client: AsyncClient):
        """Restore a soft-deleted team."""
        team_resp = await client.post("/api/v1/teams", json={"name": "restore-me"})
        team_id = team_resp.json()["id"]

        # Delete the team
        await client.delete(f"/api/v1/teams/{team_id}")

        # Verify deleted
        get_resp = await client.get(f"/api/v1/teams/{team_id}")
        assert get_resp.status_code == 404

        # Restore the team
        restore_resp = await client.post(f"/api/v1/teams/{team_id}/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["name"] == "restore-me"

        # Verify accessible again
        get_resp = await client.get(f"/api/v1/teams/{team_id}")
        assert get_resp.status_code == 200

    async def test_restore_team_not_found(self, client: AsyncClient):
        """Restore nonexistent team returns 404."""
        resp = await client.post("/api/v1/teams/00000000-0000-0000-0000-000000000000/restore")
        assert resp.status_code == 404

    async def test_restore_active_team_returns_team(self, client: AsyncClient):
        """Restoring an already-active team returns the team unchanged."""
        team_resp = await client.post("/api/v1/teams", json={"name": "already-active"})
        team_id = team_resp.json()["id"]

        # Restore without deleting first
        restore_resp = await client.post(f"/api/v1/teams/{team_id}/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["name"] == "already-active"


class TestListTeamMembers:
    """Tests for GET /api/v1/teams/{team_id}/members."""

    async def test_list_members_empty(self, client: AsyncClient):
        """List members of team with no members."""
        team_resp = await client.post("/api/v1/teams", json={"name": "empty-team"})
        team_id = team_resp.json()["id"]

        resp = await client.get(f"/api/v1/teams/{team_id}/members")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_list_members_with_users(self, client: AsyncClient):
        """List members of team with users."""
        team_resp = await client.post("/api/v1/teams", json={"name": "members-team"})
        team_id = team_resp.json()["id"]

        # Create users in the team
        await client.post(
            "/api/v1/users",
            json={"email": "alice@example.com", "name": "Alice", "team_id": team_id},
        )
        await client.post(
            "/api/v1/users",
            json={"email": "bob@example.com", "name": "Bob", "team_id": team_id},
        )

        resp = await client.get(f"/api/v1/teams/{team_id}/members")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        names = [u["name"] for u in data["results"]]
        assert "Alice" in names
        assert "Bob" in names

    async def test_list_members_pagination(self, client: AsyncClient):
        """List members with pagination."""
        team_resp = await client.post("/api/v1/teams", json={"name": "paginated-team"})
        team_id = team_resp.json()["id"]

        # Create 5 users (names must be valid per validation rules)
        import uuid

        suffix = str(uuid.uuid4())[:8]
        names = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
        for i, name in enumerate(names):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "email": f"{name.lower()}-{suffix}@example.com",
                    "name": name,
                    "team_id": team_id,
                },
            )
            assert resp.status_code == 201, f"Failed to create user: {resp.json()}"

        resp = await client.get(f"/api/v1/teams/{team_id}/members?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2

    async def test_list_members_team_not_found(self, client: AsyncClient):
        """List members of nonexistent team returns 404."""
        resp = await client.get("/api/v1/teams/00000000-0000-0000-0000-000000000000/members")
        assert resp.status_code == 404


class TestReassignTeamAssets:
    """Tests for POST /api/v1/teams/{team_id}/reassign-assets."""

    async def test_reassign_all_assets(self, client: AsyncClient):
        """Reassign all assets from one team to another."""
        # Create source and target teams
        source_resp = await client.post("/api/v1/teams", json={"name": "source-team"})
        source_id = source_resp.json()["id"]
        target_resp = await client.post("/api/v1/teams", json={"name": "target-team"})
        target_id = target_resp.json()["id"]

        # Create assets for source team
        asset1_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.reassign1", "owner_team_id": source_id},
        )
        asset1_id = asset1_resp.json()["id"]
        asset2_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.reassign2", "owner_team_id": source_id},
        )
        asset2_id = asset2_resp.json()["id"]

        # Reassign all assets
        resp = await client.post(
            f"/api/v1/teams/{source_id}/reassign-assets",
            json={"target_team_id": target_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reassigned"] == 2
        assert data["source_team"]["id"] == source_id
        assert data["target_team"]["id"] == target_id
        assert asset1_id in data["asset_ids"]
        assert asset2_id in data["asset_ids"]

        # Verify assets now belong to target team
        asset_resp = await client.get(f"/api/v1/assets/{asset1_id}")
        assert asset_resp.json()["owner_team_id"] == target_id

    async def test_reassign_specific_assets(self, client: AsyncClient):
        """Reassign specific assets by ID."""
        # Create teams
        source_resp = await client.post("/api/v1/teams", json={"name": "source-specific"})
        source_id = source_resp.json()["id"]
        target_resp = await client.post("/api/v1/teams", json={"name": "target-specific"})
        target_id = target_resp.json()["id"]

        # Create 3 assets
        asset1_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.specific1", "owner_team_id": source_id},
        )
        asset1_id = asset1_resp.json()["id"]
        await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.specific2", "owner_team_id": source_id},
        )
        asset3_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.specific3", "owner_team_id": source_id},
        )
        asset3_id = asset3_resp.json()["id"]

        # Reassign only 2 specific assets
        resp = await client.post(
            f"/api/v1/teams/{source_id}/reassign-assets",
            json={"target_team_id": target_id, "asset_ids": [asset1_id, asset3_id]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reassigned"] == 2

    async def test_reassign_no_assets(self, client: AsyncClient):
        """Reassign from team with no assets."""
        source_resp = await client.post("/api/v1/teams", json={"name": "empty-source"})
        source_id = source_resp.json()["id"]
        target_resp = await client.post("/api/v1/teams", json={"name": "empty-target"})
        target_id = target_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/teams/{source_id}/reassign-assets",
            json={"target_team_id": target_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reassigned"] == 0

    async def test_reassign_source_not_found(self, client: AsyncClient):
        """Reassign from nonexistent source team."""
        target_resp = await client.post("/api/v1/teams", json={"name": "valid-target"})
        target_id = target_resp.json()["id"]

        resp = await client.post(
            "/api/v1/teams/00000000-0000-0000-0000-000000000000/reassign-assets",
            json={"target_team_id": target_id},
        )
        assert resp.status_code == 404

    async def test_reassign_target_not_found(self, client: AsyncClient):
        """Reassign to nonexistent target team."""
        source_resp = await client.post("/api/v1/teams", json={"name": "valid-source"})
        source_id = source_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/teams/{source_id}/reassign-assets",
            json={"target_team_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    async def test_reassign_same_team(self, client: AsyncClient):
        """Reassign to same team fails."""
        team_resp = await client.post("/api/v1/teams", json={"name": "same-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/teams/{team_id}/reassign-assets",
            json={"target_team_id": team_id},
        )
        assert resp.status_code == 400
        data = resp.json()
        # HTTPException is wrapped by error handler into {"error": {...}} format
        assert "same" in data["error"]["message"].lower()
