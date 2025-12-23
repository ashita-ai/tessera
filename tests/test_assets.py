"""Tests for /api/v1/assets endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAssetsAPI:
    """Tests for /api/v1/assets endpoints."""

    async def test_create_asset(self, client: AsyncClient):
        """Create an asset."""
        team_resp = await client.post("/api/v1/teams", json={"name": "asset-owner"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "warehouse.schema.table", "owner_team_id": team_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fqn"] == "warehouse.schema.table"
        assert data["owner_team_id"] == team_id

    async def test_create_asset_invalid_owner(self, client: AsyncClient):
        """Creating an asset with nonexistent owner should fail."""
        resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "test.table",
                "owner_team_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.status_code == 404

    async def test_list_assets(self, client: AsyncClient):
        """List all assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "list-owner"})
        team_id = team_resp.json()["id"]

        await client.post("/api/v1/assets", json={"fqn": "db.schema.t1", "owner_team_id": team_id})
        await client.post("/api/v1/assets", json={"fqn": "db.schema.t2", "owner_team_id": team_id})

        resp = await client.get("/api/v1/assets")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    async def test_filter_assets_by_owner(self, client: AsyncClient):
        """Filter assets by owner team."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "filter-owner-1"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "filter-owner-2"})
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        await client.post("/api/v1/assets", json={"fqn": "team1.asset", "owner_team_id": team1_id})
        await client.post("/api/v1/assets", json={"fqn": "team2.asset", "owner_team_id": team2_id})

        resp = await client.get(f"/api/v1/assets?owner={team1_id}")
        data = resp.json()
        assets = data["results"]
        assert all(a["owner_team_id"] == team1_id for a in assets)

    async def test_update_asset(self, client: AsyncClient):
        """Update an asset."""
        team_resp = await client.post("/api/v1/teams", json={"name": "update-asset-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "update.me.asset", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"fqn": "updated.asset.name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqn"] == "updated.asset.name"

    async def test_get_asset_not_found(self, client: AsyncClient):
        """Getting nonexistent asset should 404."""
        resp = await client.get("/api/v1/assets/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_get_asset_lineage(self, client: AsyncClient):
        """Get asset lineage (downstream consumers)."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "lineage-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "lineage-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "lineage.test.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        # Get lineage
        resp = await client.get(f"/api/v1/assets/{asset_id}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_fqn"] == "lineage.test.table"
        assert len(data["downstream"]) == 1
        assert data["downstream"][0]["team_name"] == "lineage-cons"


class TestImpactAnalysis:
    """Tests for impact analysis endpoint."""

    async def test_impact_analysis_no_contract(self, client: AsyncClient):
        """Impact analysis on asset with no contract should be safe."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "impact.analysis.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={"type": "object", "properties": {"id": {"type": "integer"}}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe_to_publish"] is True
        assert data["breaking_changes"] == []

    async def test_impact_analysis_breaking_change(self, client: AsyncClient):
        """Impact analysis should detect breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-break"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "impact.breaking.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "email": {"type": "string"},
                    },
                    "required": ["id", "email"],
                },
                "compatibility_mode": "backward",
            },
        )

        # Check impact of removing email
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe_to_publish"] is False
        assert data["change_type"] == "major"
        assert len(data["breaking_changes"]) > 0

    async def test_impact_analysis_with_consumers(self, client: AsyncClient):
        """Impact analysis should list impacted consumers."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "impact-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "impact-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "impact.consumers.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        # Check impact
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={"type": "object", "properties": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["impacted_consumers"]) == 1
        assert data["impacted_consumers"][0]["team_name"] == "impact-consumer"

    async def test_impact_analysis_invalid_schema(self, client: AsyncClient):
        """Impact analysis with invalid schema should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-invalid"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "impact.invalid.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={"type": "invalid_type"},
        )
        assert resp.status_code == 400  # BadRequestError for invalid schema

    async def test_impact_analysis_asset_not_found(self, client: AsyncClient):
        """Impact analysis on nonexistent asset should 404."""
        resp = await client.post(
            "/api/v1/assets/00000000-0000-0000-0000-000000000000/impact",
            json={"type": "object"},
        )
        assert resp.status_code == 404


class TestAssetSearch:
    """Tests for asset search endpoint."""

    async def test_search_assets(self, client: AsyncClient):
        """Search assets by FQN pattern."""
        team_resp = await client.post("/api/v1/teams", json={"name": "search-owner"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/assets", json={"fqn": "search.test.alpha", "owner_team_id": team_id}
        )
        await client.post(
            "/api/v1/assets", json={"fqn": "search.test.beta", "owner_team_id": team_id}
        )
        await client.post(
            "/api/v1/assets", json={"fqn": "other.thing.gamma", "owner_team_id": team_id}
        )

        resp = await client.get("/api/v1/assets/search?q=search.test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert all("search.test" in r["fqn"] for r in data["results"])

    async def test_search_assets_with_owner_filter(self, client: AsyncClient):
        """Search assets filtered by owner."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "search-owner-1"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "search-owner-2"})
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        await client.post(
            "/api/v1/assets", json={"fqn": "searchowner.one.table", "owner_team_id": team1_id}
        )
        await client.post(
            "/api/v1/assets", json={"fqn": "searchowner.two.table", "owner_team_id": team2_id}
        )

        resp = await client.get(f"/api/v1/assets/search?q=searchowner&owner={team1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["owner_team_id"] == team1_id for r in data["results"])


class TestAssetDependencies:
    """Tests for asset dependencies endpoints."""

    async def test_create_dependency(self, client: AsyncClient):
        """Create a dependency between assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dep-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dep.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dep.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["dependency_asset_id"] == upstream_id
        assert data["dependency_type"] == "transforms"

    async def test_list_dependencies(self, client: AsyncClient):
        """List dependencies for an asset."""
        team_resp = await client.post("/api/v1/teams", json={"name": "list-dep-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "listdep.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "listdep.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )

        resp = await client.get(f"/api/v1/assets/{downstream_id}/dependencies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["dependency_asset_id"] == upstream_id

    async def test_delete_dependency(self, client: AsyncClient):
        """Delete a dependency."""
        team_resp = await client.post("/api/v1/teams", json={"name": "del-dep-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deldep.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deldep.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        dep_resp = await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )
        dep_id = dep_resp.json()["id"]

        resp = await client.delete(f"/api/v1/assets/{downstream_id}/dependencies/{dep_id}")
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get(f"/api/v1/assets/{downstream_id}/dependencies")
        assert list_resp.json()["total"] == 0
        assert len(list_resp.json()["results"]) == 0

    async def test_self_dependency_fails(self, client: AsyncClient):
        """Asset cannot depend on itself."""
        team_resp = await client.post("/api/v1/teams", json={"name": "self-dep-owner"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "selfdep.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/dependencies",
            json={"depends_on_asset_id": asset_id, "dependency_type": "transforms"},
        )
        assert resp.status_code == 400
        data = resp.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "cannot depend on itself" in error_msg

    async def test_duplicate_dependency_fails(self, client: AsyncClient):
        """Duplicate dependencies should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dup-dep-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dupdep.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dupdep.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )

        resp = await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )
        assert resp.status_code == 409  # DuplicateError for conflicts
        data = resp.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "already exists" in error_msg

    async def test_dependency_asset_not_found(self, client: AsyncClient):
        """Dependency on nonexistent asset should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "notfound-dep-owner"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "notfounddep.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/dependencies",
            json={
                "depends_on_asset_id": "00000000-0000-0000-0000-000000000000",
                "dependency_type": "transforms",
            },
        )
        assert resp.status_code == 404

    async def test_delete_dependency_not_found(self, client: AsyncClient):
        """Deleting nonexistent dependency should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "del-notfound-owner"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "delnotfound.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/assets/{asset_id}/dependencies/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404


class TestAssetLineage:
    """Tests for asset lineage endpoint."""

    async def test_lineage_with_upstream_dependencies(self, client: AsyncClient):
        """Lineage should show upstream dependencies."""
        team_resp = await client.post("/api/v1/teams", json={"name": "lineage-up-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "lineageup.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "lineageup.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )

        resp = await client.get(f"/api/v1/assets/{downstream_id}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["upstream"]) == 1
        assert data["upstream"][0]["asset_fqn"] == "lineageup.upstream.table"

    async def test_lineage_with_downstream_assets(self, client: AsyncClient):
        """Lineage should show downstream assets (reverse dependencies)."""
        team_resp = await client.post("/api/v1/teams", json={"name": "lineage-down-owner"})
        team_id = team_resp.json()["id"]

        upstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "lineagedown.upstream.table", "owner_team_id": team_id}
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "lineagedown.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id, "dependency_type": "transforms"},
        )

        resp = await client.get(f"/api/v1/assets/{upstream_id}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["downstream_assets"]) == 1
        assert data["downstream_assets"][0]["asset_fqn"] == "lineagedown.downstream.table"

    async def test_lineage_asset_not_found(self, client: AsyncClient):
        """Lineage on nonexistent asset should 404."""
        resp = await client.get("/api/v1/assets/00000000-0000-0000-0000-000000000000/lineage")
        assert resp.status_code == 404


class TestAssetUpdate:
    """Tests for asset update endpoint."""

    async def test_update_asset_owner(self, client: AsyncClient):
        """Update asset owner team."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "update-owner-1"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "update-owner-2"})
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "updateowner.table", "owner_team_id": team1_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"owner_team_id": team2_id},
        )
        assert resp.status_code == 200
        assert resp.json()["owner_team_id"] == team2_id

    async def test_update_asset_metadata(self, client: AsyncClient):
        """Update asset metadata."""
        team_resp = await client.post("/api/v1/teams", json={"name": "update-meta-owner"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "updatemeta.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"metadata": {"tier": "gold", "pii": True}},
        )
        assert resp.status_code == 200
        assert resp.json()["metadata"]["tier"] == "gold"

    async def test_update_asset_not_found(self, client: AsyncClient):
        """Updating nonexistent asset should 404."""
        resp = await client.patch(
            "/api/v1/assets/00000000-0000-0000-0000-000000000000",
            json={"fqn": "new.name"},
        )
        assert resp.status_code == 404
