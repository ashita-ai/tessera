"""Tests for /api/v1/sync endpoints (push, pull, dbt, dbt/impact)."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


@pytest.fixture
def sync_path(tmp_path: Path, monkeypatch):
    """Set up sync path for tests."""
    from tessera import config
    path = tmp_path / "contracts"
    monkeypatch.setattr(config.settings, "git_sync_path", path)
    return path


@pytest.fixture
def no_sync_path(monkeypatch):
    """Ensure git_sync_path is not configured."""
    from tessera import config
    monkeypatch.setattr(config.settings, "git_sync_path", None)


class TestSyncPathNotConfigured:
    """Tests for when GIT_SYNC_PATH is not configured."""

    async def test_push_without_git_sync_path(self, client: AsyncClient, no_sync_path):
        """Push should return 400 when GIT_SYNC_PATH is not configured."""
        resp = await client.post("/api/v1/sync/push")
        assert resp.status_code == 400
        data = resp.json()
        # Error response may use "detail" or "message" depending on error handler
        error_message = data.get("detail") or data.get("message") or str(data)
        assert "GIT_SYNC_PATH not configured" in error_message

    async def test_pull_without_git_sync_path(self, client: AsyncClient, no_sync_path):
        """Pull should return 400 when GIT_SYNC_PATH is not configured."""
        resp = await client.post("/api/v1/sync/pull")
        assert resp.status_code == 400
        data = resp.json()
        # Error response may use "detail" or "message" depending on error handler
        error_message = data.get("detail") or data.get("message") or str(data)
        assert "GIT_SYNC_PATH not configured" in error_message


class TestSyncPush:
    """Tests for /api/v1/sync/push endpoint."""

    async def test_push_with_data(self, client: AsyncClient, sync_path: Path):
        """Push should export teams, assets, and contracts to YAML files."""
        # Create test data
        team_resp = await client.post("/api/v1/teams", json={"name": "sync-push-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "sync.push.table", "owner_team_id": team_id}
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

        # Push to files
        resp = await client.post("/api/v1/sync/push")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exported"]["teams"] >= 1
        assert data["exported"]["assets"] >= 1
        assert data["exported"]["contracts"] >= 1

        # Verify files exist
        teams_path = sync_path / "teams"
        assets_path = sync_path / "assets"
        assert teams_path.exists()
        assert assets_path.exists()

        # Verify team file content
        team_file = teams_path / "sync-push-team.yaml"
        assert team_file.exists()
        team_data = yaml.safe_load(team_file.read_text())
        assert team_data["name"] == "sync-push-team"
        assert team_data["id"] == team_id

    async def test_push_with_registrations(self, client: AsyncClient, sync_path: Path):
        """Push should include registrations in exported contracts."""

        # Create producer and consumer
        producer_resp = await client.post("/api/v1/teams", json={"name": "push-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "push-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "push.reg.table", "owner_team_id": producer_id}
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

        # Push
        resp = await client.post("/api/v1/sync/push")
        assert resp.status_code == 200

        # Verify asset file includes registrations
        asset_file = sync_path / "assets" / "push_reg_table.yaml"
        assert asset_file.exists()
        asset_data = yaml.safe_load(asset_file.read_text())
        assert len(asset_data["contracts"]) == 1
        assert len(asset_data["contracts"][0]["registrations"]) == 1
        assert asset_data["contracts"][0]["registrations"][0]["consumer_team_id"] == consumer_id


class TestSyncPull:
    """Tests for /api/v1/sync/pull endpoint."""

    async def test_pull_nonexistent_path(self, client: AsyncClient, tmp_path: Path, monkeypatch):
        """Pull from nonexistent path should 404."""
        from tessera import config
        monkeypatch.setattr(config.settings, "git_sync_path", tmp_path / "nonexistent")

        resp = await client.post("/api/v1/sync/pull")
        assert resp.status_code == 404

    async def test_pull_empty_directory(self, client: AsyncClient, sync_path: Path):
        """Pull from empty directory should succeed with zero imports."""
        sync_path.mkdir(parents=True, exist_ok=True)

        resp = await client.post("/api/v1/sync/pull")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["imported"]["teams"] == 0
        assert data["imported"]["assets"] == 0
        assert data["imported"]["contracts"] == 0

    async def test_pull_teams(self, client: AsyncClient, sync_path: Path):
        """Pull should import teams from YAML files."""
        teams_path = sync_path / "teams"
        teams_path.mkdir(parents=True)

        # Create team file
        team_data = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "imported-team",
            "metadata": {"source": "git"},
        }
        (teams_path / "imported-team.yaml").write_text(yaml.dump(team_data))

        resp = await client.post("/api/v1/sync/pull")
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"]["teams"] == 1

        # Verify team was created
        team_resp = await client.get("/api/v1/teams/11111111-1111-1111-1111-111111111111")
        assert team_resp.status_code == 200
        assert team_resp.json()["name"] == "imported-team"

    async def test_roundtrip_push_pull(self, client: AsyncClient, sync_path: Path):
        """Push then pull should preserve data."""

        # Create data
        team_resp = await client.post("/api/v1/teams", json={"name": "roundtrip-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "roundtrip.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"x": {"type": "string"}}},
                "compatibility_mode": "backward",
            },
        )

        # Push
        push_resp = await client.post("/api/v1/sync/push")
        assert push_resp.status_code == 200

        # Pull (should update existing)
        pull_resp = await client.post("/api/v1/sync/pull")
        assert pull_resp.status_code == 200
        data = pull_resp.json()
        assert data["imported"]["teams"] >= 1
        assert data["imported"]["assets"] >= 1
        assert data["imported"]["contracts"] >= 1


class TestSyncDbt:
    """Tests for /api/v1/sync/dbt endpoint."""

    async def test_dbt_manifest_not_found(self, client: AsyncClient):
        """Sync from nonexistent manifest should 404."""
        # Create a team first
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path=/nonexistent/manifest.json&owner_team_id={team_id}"
        )
        assert resp.status_code == 404

    async def test_dbt_sync_models(self, client: AsyncClient, tmp_path: Path):
        """Sync should create assets from dbt models."""
        # Create team
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-models-team"})
        team_id = team_resp.json()["id"]

        # Create manifest with models
        manifest = {
            "nodes": {
                "model.project.users": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "users",
                    "description": "User data model",
                    "tags": ["pii"],
                    "columns": {
                        "id": {"description": "Primary key", "data_type": "integer"},
                        "email": {"description": "User email", "data_type": "varchar"},
                    },
                },
                "model.project.orders": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "orders",
                    "description": "Order data",
                    "tags": [],
                    "columns": {},
                },
            },
            "sources": {},
        }
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path={manifest_file}&owner_team_id={team_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["assets"]["created"] == 2
        assert data["assets"]["updated"] == 0

        # Verify assets were created
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        fqns = [a["fqn"] for a in assets]
        assert "analytics.public.users" in fqns
        assert "analytics.public.orders" in fqns

    async def test_dbt_sync_sources(self, client: AsyncClient, tmp_path: Path):
        """Sync should create assets from dbt sources."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-sources-team"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {},
            "sources": {
                "source.project.raw.customers": {
                    "database": "raw",
                    "schema": "stripe",
                    "name": "customers",
                    "description": "Raw Stripe customers",
                    "columns": {
                        "customer_id": {"description": "Stripe customer ID"},
                    },
                },
            },
        }
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path={manifest_file}&owner_team_id={team_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] == 1

    async def test_dbt_sync_updates_existing(self, client: AsyncClient, tmp_path: Path):
        """Sync should update existing assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-update-team"})
        team_id = team_resp.json()["id"]

        # Create asset first
        await client.post(
            "/api/v1/assets",
            json={"fqn": "warehouse.schema.existing", "owner_team_id": team_id},
        )

        # Sync manifest that includes existing asset
        manifest = {
            "nodes": {
                "model.project.existing": {
                    "resource_type": "model",
                    "database": "warehouse",
                    "schema": "schema",
                    "name": "existing",
                    "description": "Updated description",
                    "tags": ["updated"],
                    "columns": {},
                },
            },
            "sources": {},
        }
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path={manifest_file}&owner_team_id={team_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] == 0
        assert data["assets"]["updated"] == 1

    async def test_dbt_sync_ignores_tests(self, client: AsyncClient, tmp_path: Path):
        """Sync should skip test and other non-model resource types."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-tests-team"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "test.project.not_null_users_id": {
                    "resource_type": "test",
                    "database": "analytics",
                    "schema": "dbt_test",
                    "name": "not_null_users_id",
                },
                "model.project.real_model": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "real_model",
                    "description": "",
                    "tags": [],
                    "columns": {},
                },
            },
            "sources": {},
        }
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path={manifest_file}&owner_team_id={team_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only the model should be created, not the test
        assert data["assets"]["created"] == 1

    async def test_dbt_sync_seeds_and_snapshots(self, client: AsyncClient, tmp_path: Path):
        """Sync should include seeds and snapshots."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-seeds-team"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "seed.project.country_codes": {
                    "resource_type": "seed",
                    "database": "analytics",
                    "schema": "seeds",
                    "name": "country_codes",
                    "description": "Country code lookup",
                    "tags": [],
                    "columns": {},
                },
                "snapshot.project.users_history": {
                    "resource_type": "snapshot",
                    "database": "analytics",
                    "schema": "snapshots",
                    "name": "users_history",
                    "description": "User SCD2 history",
                    "tags": [],
                    "columns": {},
                },
            },
            "sources": {},
        }
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        resp = await client.post(
            f"/api/v1/sync/dbt?manifest_path={manifest_file}&owner_team_id={team_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] == 2


class TestDbtImpact:
    """Tests for /api/v1/sync/dbt/impact endpoint."""

    async def test_dbt_impact_no_contracts(self, client: AsyncClient):
        """Impact check with no existing contracts should show all safe."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team-1"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.users": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_users",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "name": {"data_type": "varchar"},
                    },
                },
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/impact",
            json={"manifest": manifest, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["total_models"] == 1
        assert data["models_with_contracts"] == 0
        assert data["breaking_changes_count"] == 0
        assert data["results"][0]["safe_to_publish"] is True
        assert data["results"][0]["has_contract"] is False

    async def test_dbt_impact_compatible_change(self, client: AsyncClient):
        """Impact check with compatible changes should show safe."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team-2"})
        team_id = team_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "analytics.public.impact_compat", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Check impact with added optional column (compatible)
        manifest = {
            "nodes": {
                "model.project.impact_compat": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_compat",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "new_col": {"data_type": "varchar"},  # Added column
                    },
                },
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/impact",
            json={"manifest": manifest, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["models_with_contracts"] == 1
        assert data["breaking_changes_count"] == 0
        assert data["results"][0]["safe_to_publish"] is True
        assert data["results"][0]["has_contract"] is True

    async def test_dbt_impact_breaking_change(self, client: AsyncClient):
        """Impact check with breaking changes should detect them."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team-3"})
        team_id = team_resp.json()["id"]

        # Create asset and contract with required column
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "analytics.public.impact_break", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "email": {"type": "string"},  # This will be removed
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Check impact with removed column (breaking)
        manifest = {
            "nodes": {
                "model.project.impact_break": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_break",
                    "columns": {
                        "id": {"data_type": "integer"},
                        # email column removed
                    },
                },
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/impact",
            json={"manifest": manifest, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "breaking_changes_detected"
        assert data["breaking_changes_count"] == 1
        assert data["results"][0]["safe_to_publish"] is False
        assert len(data["results"][0]["breaking_changes"]) > 0

    async def test_dbt_impact_multiple_models(self, client: AsyncClient):
        """Impact check should handle multiple models."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team-4"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.model_a": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_multi_a",
                    "columns": {"id": {"data_type": "integer"}},
                },
                "model.project.model_b": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_multi_b",
                    "columns": {"id": {"data_type": "integer"}},
                },
            },
            "sources": {
                "source.project.raw": {
                    "database": "raw",
                    "schema": "stripe",
                    "name": "impact_source",
                    "columns": {"customer_id": {"data_type": "varchar"}},
                },
            },
        }

        resp = await client.post(
            "/api/v1/sync/dbt/impact",
            json={"manifest": manifest, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_models"] == 3
        assert data["status"] == "success"

    async def test_dbt_impact_type_mapping(self, client: AsyncClient):
        """Impact check should correctly map dbt types to JSON Schema types."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-team-5"})
        team_id = team_resp.json()["id"]

        # Create asset with specific types
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "analytics.public.impact_types", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "amount": {"type": "number"},
                        "active": {"type": "boolean"},
                        "name": {"type": "string"},
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Check impact with same types in dbt format
        manifest = {
            "nodes": {
                "model.project.impact_types": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "impact_types",
                    "columns": {
                        "id": {"data_type": "bigint"},  # maps to integer
                        "amount": {"data_type": "decimal(18,2)"},  # maps to number
                        "active": {"data_type": "boolean"},
                        "name": {"data_type": "varchar(255)"},  # maps to string
                    },
                },
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/impact",
            json={"manifest": manifest, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["breaking_changes_count"] == 0
