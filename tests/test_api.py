"""API integration tests for Tessera."""

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
        assert resp.status_code == 400

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


class TestContractsAPI:
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

    async def test_list_contracts(self, client: AsyncClient):
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
        contracts = resp.json()
        assert len(contracts) == 1
        assert contracts[0]["version"] == "1.0.0"


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


class TestRegistrations:
    """Tests for consumer registration."""

    async def test_register_as_consumer(self, client: AsyncClient):
        """Register a team as consumer of a contract."""
        # Create producer and consumer teams
        producer_resp = await client.post("/api/v1/teams", json={"name": "reg-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "reg-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "reg.test.table", "owner_team_id": producer_id}
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

        # Register as consumer
        resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["consumer_team_id"] == consumer_id
        assert data["status"] == "active"

    async def test_impact_shows_consumers(self, client: AsyncClient):
        """Impact analysis should show registered consumers."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "show-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "show-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "show.consumers.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        # Impact analysis should show the consumer
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        data = resp.json()
        assert len(data["impacted_consumers"]) == 1
        assert data["impacted_consumers"][0]["team_name"] == "show-consumer"


class TestProposals:
    """Tests for proposal workflow."""

    async def test_acknowledge_proposal(self, client: AsyncClient):
        """Consumer can acknowledge a proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "ack-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "ack-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "ack.proposal.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        # Create breaking change (creates proposal)
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Acknowledge the proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "notes": "We've updated our pipeline",
            },
        )
        assert resp.status_code == 201


class TestHealth:
    """Tests for health endpoint."""

    async def test_health_check(self, client: AsyncClient):
        """Health endpoint should return healthy."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
