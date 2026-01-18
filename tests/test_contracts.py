"""Tests for /api/v1/contracts endpoints and contract publishing workflow."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestContractPublishing:
    """Tests for contract publishing workflow."""

    async def test_publish_first_contract(self, client: AsyncClient):
        """Publishing the first contract should auto-approve."""
        team_resp = await client.post("/api/v1/teams", json={"name": "publisher"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "first.contract.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "published"
        assert data["contract"]["version"] == "1.0.0"

    async def test_compatible_change_auto_publishes(self, client: AsyncClient):
        """Backward-compatible change should auto-publish."""
        team_resp = await client.post("/api/v1/teams", json={"name": "compat-pub"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "compat.change.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "compatibility_mode": "backward",
            },
        )

        # Add optional field (backward compatible)
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.1.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                    "required": ["id"],
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "published"
        assert data["change_type"] == "minor"

    async def test_breaking_change_creates_proposal(self, client: AsyncClient):
        """Breaking change should create a proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "break-pub"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "break.change.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract with two fields
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

        # Remove required field (breaking)
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
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
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "proposal_created"
        assert data["change_type"] == "major"
        assert len(data["breaking_changes"]) > 0
        assert "proposal" in data

    async def test_force_publish_breaking_change(self, client: AsyncClient):
        """Force flag should publish breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-pub"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "force.publish.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Force publish breaking change
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}&force=true",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "force_published"
        assert "warning" in data

    async def test_list_asset_contracts(self, client: AsyncClient):
        """List contracts for an asset."""
        team_resp = await client.post("/api/v1/teams", json={"name": "list-contracts"})
        team_id = team_resp.json()["id"]
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "list.contracts.table", "owner_team_id": team_id}
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

        resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["version"] == "1.0.0"


class TestContractsEndpoint:
    """Tests for /api/v1/contracts endpoints."""

    async def test_list_contracts(self, client: AsyncClient):
        """List all contracts with filtering."""
        team_resp = await client.post("/api/v1/teams", json={"name": "list-contracts-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "list.contracts.endpoint", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create a contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # List contracts
        resp = await client.get("/api/v1/contracts")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data

        # Filter by status
        resp = await client.get("/api/v1/contracts?status=active")
        assert resp.status_code == 200

    async def test_get_contract_by_id(self, client: AsyncClient):
        """Get a contract by ID."""
        team_resp = await client.post("/api/v1/teams", json={"name": "get-contract-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "get.contract.endpoint", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Get the contract
        resp = await client.get(f"/api/v1/contracts/{contract_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.0.0"

    async def test_get_contract_not_found(self, client: AsyncClient):
        """Getting nonexistent contract should 404."""
        resp = await client.get("/api/v1/contracts/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_list_contract_registrations(self, client: AsyncClient):
        """List registrations for a contract."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "contract-reg-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "contract-reg-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "contract.registrations.table", "owner_team_id": producer_id},
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

        # List registrations for this contract
        resp = await client.get(f"/api/v1/contracts/{contract_id}/registrations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["consumer_team_id"] == consumer_id


class TestContractFiltering:
    """Tests for filtering on /api/v1/contracts."""

    async def test_filter_by_asset_id(self, client: AsyncClient):
        """Filter contracts by asset ID."""
        # Setup teams
        t1_resp = await client.post("/api/v1/teams", json={"name": "cfilter-t1"})
        t1_id = t1_resp.json()["id"]

        # Setup assets
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "cfilter.asset1", "owner_team_id": t1_id}
        )
        a1_id = a1_resp.json()["id"]
        a2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "cfilter.asset2", "owner_team_id": t1_id}
        )
        a2_id = a2_resp.json()["id"]

        # Create contracts
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        await client.post(
            f"/api/v1/assets/{a2_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Filter by asset 1
        resp = await client.get(f"/api/v1/contracts?asset_id={a1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["asset_id"] == a1_id

    async def test_filter_by_status(self, client: AsyncClient):
        """Filter contracts by status."""
        t1_resp = await client.post("/api/v1/teams", json={"name": "cfilter-status"})
        t1_id = t1_resp.json()["id"]
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "cfilter.status", "owner_team_id": t1_id}
        )
        a1_id = a1_resp.json()["id"]

        # Create active contract (v1)
        resp1 = await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        assert resp1.status_code == 201

        # Create new version (v2), making v1 deprecated (assuming standard behavior)

        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "2.0.0",  # Major change
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Create second contract (deprecates first)
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.1.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Filter active

        resp = await client.get("/api/v1/contracts?status=active")

        assert resp.status_code == 200
        active_versions = [c["version"] for c in resp.json()["results"] if c["asset_id"] == a1_id]
        assert "1.1.0" in active_versions
        assert "1.0.0" not in active_versions  # Assuming 1.0.0 became deprecated

    async def test_filter_by_status_deprecated(self, client: AsyncClient):
        """Filter contracts by deprecated status."""
        t1_resp = await client.post("/api/v1/teams", json={"name": "cfilter-dep"})
        t1_id = t1_resp.json()["id"]
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "cfilter.dep", "owner_team_id": t1_id}
        )
        a1_id = a1_resp.json()["id"]

        # v1.0.0
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        # v1.1.0 (deprecates v1.0.0)
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={t1_id}",
            json={
                "version": "1.1.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Filter deprecated
        resp = await client.get("/api/v1/contracts?status=deprecated")
        assert resp.status_code == 200
        dep_versions = [c["version"] for c in resp.json()["results"] if c["asset_id"] == a1_id]

        # 1.0.0 should be deprecated
        assert "1.0.0" in dep_versions
        assert "1.1.0" not in dep_versions


class TestGuaranteesUpdate:
    """Tests for PATCH /api/v1/contracts/{id}/guarantees endpoint."""

    async def test_update_guarantees_success(self, client: AsyncClient):
        """Successfully update guarantees on an active contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "guarantees.update.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Update guarantees
        resp = await client.patch(
            f"/api/v1/contracts/{contract_id}/guarantees",
            json={
                "guarantees": {
                    "freshness": {"max_staleness_minutes": 60},
                    "nullability": {"id": "never"},
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["guarantees"]["freshness"]["max_staleness_minutes"] == 60
        assert data["guarantees"]["nullability"]["id"] == "never"

    async def test_update_guarantees_not_found(self, client: AsyncClient):
        """Updating guarantees on nonexistent contract should 404."""
        resp = await client.patch(
            "/api/v1/contracts/00000000-0000-0000-0000-000000000000/guarantees",
            json={"guarantees": {"freshness": {"max_staleness_minutes": 30}}},
        )
        assert resp.status_code == 404

    async def test_update_guarantees_deprecated_contract(self, client: AsyncClient):
        """Updating guarantees on deprecated contract should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "deprecated-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deprecated.contract.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        first_contract_id = contract_resp.json()["contract"]["id"]

        # Second contract (deprecates first)
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

        # Try to update guarantees on deprecated contract
        resp = await client.patch(
            f"/api/v1/contracts/{first_contract_id}/guarantees",
            json={"guarantees": {"freshness": {"max_staleness_minutes": 30}}},
        )
        assert resp.status_code == 400
        assert "deprecated" in resp.json()["error"]["message"].lower()

    async def test_update_guarantees_replaces_existing(self, client: AsyncClient):
        """Updating guarantees should replace existing guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "replace-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "replace.guarantees.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create contract with initial guarantees
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
                "guarantees": {"freshness": {"max_staleness_minutes": 120}},
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Update with new guarantees (should replace, not merge)
        resp = await client.patch(
            f"/api/v1/contracts/{contract_id}/guarantees",
            json={"guarantees": {"volume": {"min_rows": 100}}},
        )
        assert resp.status_code == 200
        data = resp.json()
        # New guarantees should be set
        assert data["guarantees"]["volume"]["min_rows"] == 100
        # Old guarantees should be replaced (freshness should be None or not present)
        assert data["guarantees"].get("freshness") is None


class TestBulkContractPublishing:
    """Tests for POST /api/v1/contracts/bulk endpoint."""

    async def test_bulk_preview_first_contracts(self, client: AsyncClient):
        """Preview bulk publishing first contracts for multiple assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-first"})
        team_id = team_resp.json()["id"]

        # Create two assets without contracts
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.first.asset1", "owner_team_id": team_id}
        )
        a2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.first.asset2", "owner_team_id": team_id}
        )
        a1_id = a1_resp.json()["id"]
        a2_id = a2_resp.json()["id"]

        # Preview bulk publish
        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=true",
            json={
                "contracts": [
                    {
                        "asset_id": a1_id,
                        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                    {
                        "asset_id": a2_id,
                        "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preview"] is True
        assert data["total"] == 2
        assert data["published"] == 2
        assert data["skipped"] == 0
        assert data["failed"] == 0
        assert all(r["status"] == "will_publish" for r in data["results"])
        assert all(r["suggested_version"] == "1.0.0" for r in data["results"])

    async def test_bulk_execute_first_contracts(self, client: AsyncClient):
        """Execute bulk publishing first contracts for multiple assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-exec"})
        team_id = team_resp.json()["id"]

        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.exec.asset1", "owner_team_id": team_id}
        )
        a2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.exec.asset2", "owner_team_id": team_id}
        )
        a1_id = a1_resp.json()["id"]
        a2_id = a2_resp.json()["id"]

        # Execute bulk publish
        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=false",
            json={
                "contracts": [
                    {
                        "asset_id": a1_id,
                        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                    {
                        "asset_id": a2_id,
                        "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preview"] is False
        assert data["published"] == 2
        assert all(r["status"] == "published" for r in data["results"])
        assert all(r["contract_id"] is not None for r in data["results"])

    async def test_bulk_preview_mixed_scenarios(self, client: AsyncClient):
        """Preview bulk publish with compatible changes, no changes, and breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-mixed"})
        team_id = team_resp.json()["id"]

        # Asset 1: will have compatible change
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.mixed.compat", "owner_team_id": team_id}
        )
        a1_id = a1_resp.json()["id"]
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Asset 2: will have no changes (same schema)
        a2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.mixed.nochange", "owner_team_id": team_id}
        )
        a2_id = a2_resp.json()["id"]
        await client.post(
            f"/api/v1/assets/{a2_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                "compatibility_mode": "backward",
            },
        )

        # Asset 3: will have breaking change
        a3_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.mixed.breaking", "owner_team_id": team_id}
        )
        a3_id = a3_resp.json()["id"]
        await client.post(
            f"/api/v1/assets/{a3_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "email": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Preview bulk publish
        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=true",
            json={
                "contracts": [
                    {
                        "asset_id": a1_id,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "new_field": {"type": "string"},
                            },
                        },
                    },
                    {
                        "asset_id": a2_id,
                        "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    },
                    {
                        "asset_id": a3_id,
                        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Find results by asset
        results_by_asset = {str(r["asset_id"]): r for r in data["results"]}

        # Asset 1: compatible change -> will_publish
        assert results_by_asset[a1_id]["status"] == "will_publish"
        assert results_by_asset[a1_id]["suggested_version"] == "1.1.0"

        # Asset 2: no change -> will_skip
        assert results_by_asset[a2_id]["status"] == "will_skip"

        # Asset 3: breaking change -> breaking
        assert results_by_asset[a3_id]["status"] == "breaking"
        assert results_by_asset[a3_id]["suggested_version"] == "2.0.0"
        assert len(results_by_asset[a3_id]["breaking_changes"]) > 0

    async def test_bulk_execute_with_proposals(self, client: AsyncClient):
        """Execute bulk publish with create_proposals_for_breaking=true."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-proposals"})
        team_id = team_resp.json()["id"]

        # Create asset with existing contract
        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.proposal.asset", "owner_team_id": team_id}
        )
        a1_id = a1_resp.json()["id"]
        await client.post(
            f"/api/v1/assets/{a1_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "email": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Execute with breaking change and create_proposals_for_breaking=true
        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=false&create_proposals_for_breaking=true",
            json={
                "contracts": [
                    {
                        "asset_id": a1_id,
                        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["proposals_created"] == 1
        assert data["results"][0]["status"] == "proposal_created"
        assert data["results"][0]["proposal_id"] is not None

    async def test_bulk_invalid_schema_fails(self, client: AsyncClient):
        """Bulk publish with invalid schema should fail that item."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-invalid"})
        team_id = team_resp.json()["id"]

        a1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.invalid.asset", "owner_team_id": team_id}
        )
        a1_id = a1_resp.json()["id"]

        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=true",
            json={
                "contracts": [
                    {
                        "asset_id": a1_id,
                        "schema": {"type": "invalid_type"},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert data["results"][0]["status"] == "failed"
        assert "Invalid schema" in data["results"][0]["error"]

    async def test_bulk_asset_not_found(self, client: AsyncClient):
        """Bulk publish with nonexistent asset should fail that item."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-notfound"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=true",
            json={
                "contracts": [
                    {
                        "asset_id": "00000000-0000-0000-0000-000000000000",
                        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                ],
                "published_by": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert "not found" in data["results"][0]["error"].lower()

    async def test_bulk_publisher_not_found(self, client: AsyncClient):
        """Bulk publish with nonexistent publisher team should 404."""
        resp = await client.post(
            "/api/v1/contracts/bulk?dry_run=true",
            json={
                "contracts": [
                    {
                        "asset_id": "00000000-0000-0000-0000-000000000001",
                        "schema": {"type": "object"},
                    },
                ],
                "published_by": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.status_code == 404
