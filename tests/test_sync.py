"""Tests for /api/v1/sync endpoints (push, pull, dbt, dbt/impact)."""

import json
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


class TestDbtGuaranteesExtraction:
    """Tests for extracting guarantees from dbt tests during sync."""

    async def test_dbt_sync_extracts_not_null_tests(self, client: AsyncClient, tmp_path: Path):
        """Sync should extract not_null tests as nullability guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team-1"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.orders": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "orders_with_tests",
                    "description": "Orders model",
                    "tags": [],
                    "columns": {
                        "id": {"data_type": "integer"},
                        "customer_id": {"data_type": "integer"},
                        "status": {"data_type": "varchar"},
                    },
                },
                "test.project.not_null_orders_id": {
                    "resource_type": "test",
                    "depends_on": {"nodes": ["model.project.orders"]},
                    "test_metadata": {
                        "name": "not_null",
                        "kwargs": {"column_name": "id"},
                    },
                },
                "test.project.not_null_orders_customer_id": {
                    "resource_type": "test",
                    "depends_on": {"nodes": ["model.project.orders"]},
                    "test_metadata": {
                        "name": "not_null",
                        "kwargs": {"column_name": "customer_id"},
                    },
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
        assert data["guarantees_extracted"] == 1

        # Verify asset has guarantees in metadata
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        asset = next(a for a in assets if "orders_with_tests" in a["fqn"])
        asset_detail = await client.get(f"/api/v1/assets/{asset['id']}")
        metadata = asset_detail.json().get("metadata", {})

        assert "guarantees" in metadata
        assert "nullability" in metadata["guarantees"]
        assert metadata["guarantees"]["nullability"]["id"] == "never"
        assert metadata["guarantees"]["nullability"]["customer_id"] == "never"

    async def test_dbt_sync_extracts_accepted_values_tests(
        self, client: AsyncClient, tmp_path: Path
    ):
        """Sync should extract accepted_values tests as guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team-2"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.users": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "users_with_values",
                    "description": "Users model",
                    "tags": [],
                    "columns": {
                        "id": {"data_type": "integer"},
                        "status": {"data_type": "varchar"},
                    },
                },
                "test.project.accepted_values_users_status": {
                    "resource_type": "test",
                    "depends_on": {"nodes": ["model.project.users"]},
                    "test_metadata": {
                        "name": "accepted_values",
                        "kwargs": {
                            "column_name": "status",
                            "values": ["active", "inactive", "pending"],
                        },
                    },
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
        assert data["guarantees_extracted"] == 1

        # Verify asset has accepted_values guarantees
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        asset = next(a for a in assets if "users_with_values" in a["fqn"])
        asset_detail = await client.get(f"/api/v1/assets/{asset['id']}")
        metadata = asset_detail.json().get("metadata", {})

        assert "guarantees" in metadata
        assert "accepted_values" in metadata["guarantees"]
        assert metadata["guarantees"]["accepted_values"]["status"] == [
            "active",
            "inactive",
            "pending",
        ]

    async def test_dbt_sync_extracts_custom_tests(self, client: AsyncClient, tmp_path: Path):
        """Sync should extract unique and relationship tests as custom guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team-3"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.products": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "products_custom",
                    "description": "Products model",
                    "tags": [],
                    "columns": {
                        "id": {"data_type": "integer"},
                        "sku": {"data_type": "varchar"},
                    },
                },
                "test.project.unique_products_sku": {
                    "resource_type": "test",
                    "depends_on": {"nodes": ["model.project.products"]},
                    "test_metadata": {
                        "name": "unique",
                        "kwargs": {"column_name": "sku"},
                    },
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
        assert data["guarantees_extracted"] == 1

        # Verify asset has custom guarantees
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        asset = next(a for a in assets if "products_custom" in a["fqn"])
        asset_detail = await client.get(f"/api/v1/assets/{asset['id']}")
        metadata = asset_detail.json().get("metadata", {})

        assert "guarantees" in metadata
        assert "custom" in metadata["guarantees"]
        assert len(metadata["guarantees"]["custom"]) == 1
        assert metadata["guarantees"]["custom"][0]["type"] == "unique"
        assert metadata["guarantees"]["custom"][0]["column"] == "sku"

    async def test_dbt_sync_no_tests_no_guarantees(self, client: AsyncClient, tmp_path: Path):
        """Sync should not add guarantees if no tests are defined."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team-4"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.simple": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "simple_model",
                    "description": "Simple model without tests",
                    "tags": [],
                    "columns": {"id": {"data_type": "integer"}},
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
        assert data["guarantees_extracted"] == 0

        # Verify asset has no guarantees in metadata
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        asset = next(a for a in assets if "simple_model" in a["fqn"])
        asset_detail = await client.get(f"/api/v1/assets/{asset['id']}")
        metadata = asset_detail.json().get("metadata", {})

        assert "guarantees" not in metadata

    async def test_dbt_sync_extracts_singular_tests(self, client: AsyncClient, tmp_path: Path):
        """Sync should extract singular tests (SQL files) as custom guarantees.

        Singular tests express custom business logic assertions like
        'market_value must equal shares * price * multiplier'.
        """
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team-5"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.positions": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "positions_singular",
                    "description": "Positions model",
                    "tags": [],
                    "columns": {
                        "id": {"data_type": "integer"},
                        "shares": {"data_type": "numeric"},
                        "price": {"data_type": "numeric"},
                        "market_value": {"data_type": "numeric"},
                    },
                },
                # Singular test - SQL file in tests/ directory, no test_metadata
                "test.project.assert_market_value_consistency": {
                    "resource_type": "test",
                    "depends_on": {"nodes": ["model.project.positions"]},
                    "description": "Validates market_value = shares * price",
                    "raw_code": (
                        "SELECT * FROM {{ ref('positions') }} "
                        "WHERE ABS(market_value - shares * price) > 0.01"
                    ),
                    # No test_metadata - this is what makes it a singular test
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
        assert data["guarantees_extracted"] == 1

        # Verify asset has singular test as custom guarantee
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assets = assets_resp.json()["results"]
        asset = next(a for a in assets if "positions_singular" in a["fqn"])
        asset_detail = await client.get(f"/api/v1/assets/{asset['id']}")
        metadata = asset_detail.json().get("metadata", {})

        assert "guarantees" in metadata
        assert "custom" in metadata["guarantees"]
        assert len(metadata["guarantees"]["custom"]) == 1

        singular_test = metadata["guarantees"]["custom"][0]
        assert singular_test["type"] == "singular"
        assert singular_test["name"] == "assert_market_value_consistency"
        assert singular_test["description"] == "Validates market_value = shares * price"
        assert "market_value" in singular_test["sql"]
        assert "shares * price" in singular_test["sql"]


class TestDbtAutoCreateProposals:
    """Tests for auto_create_proposals flag in dbt upload."""

    async def test_auto_create_proposals_creates_proposal_for_breaking_change(
        self, client: AsyncClient
    ):
        """auto_create_proposals should create proposal when schema has breaking changes."""
        # Step 1: Create team
        team_resp = await client.post("/api/v1/teams", json={"name": "proposals-test-team"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # Step 2: Create asset with initial contract (id, name, email columns)
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.users", "owner_team_id": team_id},
        )
        assert asset_resp.status_code == 201
        asset_id = asset_resp.json()["id"]

        # Publish initial contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )
        assert contract_resp.status_code == 201

        # Step 3: Upload manifest with breaking change (removes email column)
        manifest = {
            "nodes": {
                "model.project.users": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "users",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "name": {"data_type": "string"},
                        # email column removed - breaking change!
                    },
                }
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
                "auto_create_proposals": True,
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # Verify proposal was created
        assert result["proposals"]["created"] == 1
        assert len(result["proposals"]["details"]) == 1

        proposal_info = result["proposals"]["details"][0]
        assert proposal_info["asset_fqn"] == "test.main.users"
        assert proposal_info["breaking_changes_count"] >= 1
        assert proposal_info["change_type"] in ["major", "patch", "minor"]

        # Verify proposal exists via API
        proposal_id = proposal_info["proposal_id"]
        get_resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert get_resp.status_code == 200
        proposal = get_resp.json()
        assert proposal["asset_id"] == asset_id
        assert proposal["status"] == "pending"

    async def test_auto_create_proposals_no_proposal_for_compatible_change(
        self, client: AsyncClient
    ):
        """auto_create_proposals should not create proposal for compatible changes."""
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "proposals-compat-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.orders", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Upload manifest with compatible change (add new column)
        manifest = {
            "nodes": {
                "model.project.orders": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "orders",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "amount": {"data_type": "numeric"},  # New column - compatible
                    },
                }
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
                "auto_create_proposals": True,
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # No proposal should be created for compatible changes
        assert result["proposals"]["created"] == 0
        assert len(result["proposals"]["details"]) == 0

    async def test_auto_create_proposals_disabled_by_default(self, client: AsyncClient):
        """auto_create_proposals should be disabled by default."""
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "proposals-default-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.products", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "sku": {"type": "string"},
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Upload manifest with breaking change but WITHOUT auto_create_proposals
        manifest = {
            "nodes": {
                "model.project.products": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "products",
                    "columns": {
                        "id": {"data_type": "integer"},
                        # sku removed - breaking change!
                    },
                }
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
                # auto_create_proposals NOT specified (defaults to False)
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # No proposal should be created when flag is not set
        assert result["proposals"]["created"] == 0


class TestDbtAutoPublishContractsExisting:
    """Tests for auto_publish_contracts with existing assets."""

    async def test_auto_publish_contracts_existing_asset_no_contract(self, client: AsyncClient):
        """auto_publish_contracts should publish v1.0.0 for existing assets without contracts."""
        # Create team and asset (no contract)
        team_resp = await client.post("/api/v1/teams", json={"name": "auto-pub-existing-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.no_contract_asset", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Upload manifest with columns - should auto-publish v1.0.0
        manifest = {
            "nodes": {
                "model.project.no_contract_asset": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "no_contract_asset",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "name": {"data_type": "string"},
                    },
                }
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
                "auto_publish_contracts": True,
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # Contract should be published
        assert result["contracts"]["published"] == 1

        # Verify contract exists via API
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        contracts = contracts_resp.json()["results"]
        assert len(contracts) == 1
        assert contracts[0]["version"] == "1.0.0"
        assert contracts[0]["status"] == "active"

    async def test_auto_publish_contracts_existing_asset_compatible_change(
        self, client: AsyncClient
    ):
        """auto_publish_contracts should bump version for compatible changes."""
        # Create team and asset with existing contract
        team_resp = await client.post("/api/v1/teams", json={"name": "auto-pub-compat-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.compat_asset", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish initial contract v1.0.0
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                    },
                    "required": [],
                },
                "compatibility_mode": "backward",
            },
        )

        # Upload manifest with compatible change (add column)
        manifest = {
            "nodes": {
                "model.project.compat_asset": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "compat_asset",
                    "columns": {
                        "id": {"data_type": "integer"},
                        "name": {"data_type": "string"},  # New column
                    },
                }
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
                "auto_publish_contracts": True,
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # New version should be published
        assert result["contracts"]["published"] == 1

        # Verify new contract version exists
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        contracts = contracts_resp.json()["results"]
        versions = [c["version"] for c in contracts]
        assert "1.1.0" in versions  # Minor version bump


class TestDbtAutoRegisterConsumersExisting:
    """Tests for auto_register_consumers with existing assets."""

    async def test_auto_register_consumers_existing_asset_from_refs(self, client: AsyncClient):
        """auto_register_consumers should register consumers for existing assets from refs."""
        # Create teams
        producer_resp = await client.post("/api/v1/teams", json={"name": "producer-team"})
        producer_team_id = producer_resp.json()["id"]

        consumer_resp = await client.post("/api/v1/teams", json={"name": "consumer-team"})
        consumer_team_id = consumer_resp.json()["id"]

        # Create upstream asset with contract
        upstream_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.upstream_model", "owner_team_id": producer_team_id},
        )
        upstream_id = upstream_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{upstream_id}/contracts?published_by={producer_team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Create downstream asset (already exists)
        await client.post(
            "/api/v1/assets",
            json={"fqn": "test.main.downstream_model", "owner_team_id": consumer_team_id},
        )

        # Upload manifest with ref dependency
        manifest = {
            "nodes": {
                "model.project.upstream_model": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "upstream_model",
                    "columns": {"id": {"data_type": "integer"}},
                },
                "model.project.downstream_model": {
                    "resource_type": "model",
                    "database": "test",
                    "schema": "main",
                    "name": "downstream_model",
                    "columns": {"id": {"data_type": "integer"}},
                    "depends_on": {"nodes": ["model.project.upstream_model"]},
                },
            },
            "sources": {},
        }

        upload_resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": consumer_team_id,
                "conflict_mode": "overwrite",
                "auto_register_consumers": True,
                "infer_consumers_from_refs": True,
            },
        )
        assert upload_resp.status_code == 200
        result = upload_resp.json()

        # Registration should be created
        assert result["registrations"]["created"] >= 1
