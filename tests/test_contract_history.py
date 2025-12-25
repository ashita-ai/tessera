"""Tests for contract history and version diffing endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestContractHistory:
    """Tests for /api/v1/assets/{asset_id}/contracts/history endpoint."""

    async def test_get_contract_history_single_contract(self, client: AsyncClient):
        """Get history with a single contract shows initial change type."""
        team_resp = await client.post("/api/v1/teams", json={"name": "history-single"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "history.single.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(f"/api/v1/assets/{asset_id}/contracts/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_fqn"] == "history.single.table"
        assert len(data["contracts"]) == 1
        assert data["contracts"][0]["version"] == "1.0.0"
        assert data["contracts"][0]["change_type"] == "initial"
        assert data["contracts"][0]["breaking_changes_count"] == 0

    async def test_get_contract_history_multiple_versions(self, client: AsyncClient):
        """Get history with multiple versions shows change types."""
        team_resp = await client.post("/api/v1/teams", json={"name": "history-multi"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "history.multi.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create first version
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Add optional field (minor change)
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.1.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(f"/api/v1/assets/{asset_id}/contracts/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contracts"]) == 2
        # Most recent first
        assert data["contracts"][0]["version"] == "1.1.0"
        assert data["contracts"][0]["change_type"] == "minor"
        assert data["contracts"][1]["version"] == "1.0.0"
        assert data["contracts"][1]["change_type"] == "initial"

    async def test_get_contract_history_asset_not_found(self, client: AsyncClient):
        """History for nonexistent asset should 404."""
        resp = await client.get(
            "/api/v1/assets/00000000-0000-0000-0000-000000000000/contracts/history"
        )
        assert resp.status_code == 404


class TestContractDiff:
    """Tests for /api/v1/assets/{asset_id}/contracts/diff endpoint."""

    async def test_diff_compatible_versions(self, client: AsyncClient):
        """Diff between compatible versions shows no breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "diff-compat"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "diff.compat.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.1.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(
            f"/api/v1/assets/{asset_id}/contracts/diff?from_version=1.0.0&to_version=1.1.0"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_version"] == "1.0.0"
        assert data["to_version"] == "1.1.0"
        assert data["is_compatible"] is True
        assert data["change_type"] == "minor"
        assert len(data["breaking_changes"]) == 0
        assert len(data["all_changes"]) > 0

    async def test_diff_breaking_versions(self, client: AsyncClient):
        """Diff between breaking versions shows breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "diff-break"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "diff.break.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "email": {"type": "string"}},
                    "required": ["id", "email"],
                },
                "compatibility_mode": "backward",
            },
        )

        # Force publish breaking change to create v2
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}&force=true",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(
            f"/api/v1/assets/{asset_id}/contracts/diff?from_version=1.0.0&to_version=2.0.0"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_compatible"] is False
        assert data["change_type"] == "major"
        assert len(data["breaking_changes"]) > 0

    async def test_diff_from_version_not_found(self, client: AsyncClient):
        """Diff with invalid from_version should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "diff-notfound-from"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "diff.notfound.from", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object"},
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(
            f"/api/v1/assets/{asset_id}/contracts/diff?from_version=0.0.0&to_version=1.0.0"
        )
        assert resp.status_code == 404

    async def test_diff_to_version_not_found(self, client: AsyncClient):
        """Diff with invalid to_version should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "diff-notfound-to"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "diff.notfound.to", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object"},
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(
            f"/api/v1/assets/{asset_id}/contracts/diff?from_version=1.0.0&to_version=2.0.0"
        )
        assert resp.status_code == 404

    async def test_diff_asset_not_found(self, client: AsyncClient):
        """Diff for nonexistent asset should 404."""
        resp = await client.get(
            "/api/v1/assets/00000000-0000-0000-0000-000000000000/contracts/diff"
            "?from_version=1.0.0&to_version=2.0.0"
        )
        assert resp.status_code == 404


class TestDuplicateFQN:
    """Tests for duplicate FQN handling."""

    async def test_create_duplicate_fqn_fails(self, client: AsyncClient):
        """Creating an asset with duplicate FQN should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dup-fqn-team"})
        team_id = team_resp.json()["id"]

        # Create first asset
        resp1 = await client.post(
            "/api/v1/assets", json={"fqn": "duplicate.fqn.table", "owner_team_id": team_id}
        )
        assert resp1.status_code == 201

        # Try to create duplicate
        resp2 = await client.post(
            "/api/v1/assets", json={"fqn": "duplicate.fqn.table", "owner_team_id": team_id}
        )
        assert resp2.status_code == 409


class TestListAssetsFiltering:
    """Tests for asset list filtering."""

    async def test_list_assets_filter_by_fqn(self, client: AsyncClient):
        """Filter assets by FQN pattern."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fqn-filter"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/assets", json={"fqn": "fqnfilter.analytics.table1", "owner_team_id": team_id}
        )
        await client.post(
            "/api/v1/assets", json={"fqn": "fqnfilter.analytics.table2", "owner_team_id": team_id}
        )
        await client.post(
            "/api/v1/assets", json={"fqn": "fqnfilter.other.table", "owner_team_id": team_id}
        )

        resp = await client.get("/api/v1/assets?fqn=analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert all("analytics" in r["fqn"] for r in data["results"])

    async def test_list_assets_empty_result(self, client: AsyncClient):
        """Filter that matches nothing returns empty list."""
        resp = await client.get("/api/v1/assets?fqn=nonexistent_very_unique_pattern_xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0
