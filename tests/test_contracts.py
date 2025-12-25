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
