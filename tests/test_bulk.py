"""Tests for /api/v1/bulk endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestBulkRegistrations:
    """Tests for bulk registration creation."""

    async def test_bulk_create_registrations_success(self, client: AsyncClient) -> None:
        """Create multiple registrations at once."""
        # Create teams
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-reg-team"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "bulk-consumer"})
        team_id = team_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create assets
        asset1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.reg.table1", "owner_team_id": team_id}
        )
        asset2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.reg.table2", "owner_team_id": team_id}
        )
        asset1_id = asset1_resp.json()["id"]
        asset2_id = asset2_resp.json()["id"]

        # Create contracts
        contract1_resp = await client.post(
            f"/api/v1/assets/{asset1_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract2_resp = await client.post(
            f"/api/v1/assets/{asset2_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract1_id = contract1_resp.json()["contract"]["id"]
        contract2_id = contract2_resp.json()["contract"]["id"]

        # Bulk create registrations
        resp = await client.post(
            "/api/v1/bulk/registrations",
            json={
                "registrations": [
                    {"contract_id": contract1_id, "consumer_team_id": consumer_id},
                    {"contract_id": contract2_id, "consumer_team_id": consumer_id},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["succeeded"] == 2
        assert data["failed"] == 0
        assert len(data["results"]) == 2
        assert all(r["success"] for r in data["results"])

    async def test_bulk_registrations_skip_duplicates(self, client: AsyncClient) -> None:
        """Skip duplicate registrations when skip_duplicates is true."""
        # Create teams
        team_resp = await client.post("/api/v1/teams", json={"name": "dup-reg-team"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "dup-consumer"})
        team_id = team_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dup.reg.table", "owner_team_id": team_id}
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

        # First bulk create
        await client.post(
            "/api/v1/bulk/registrations",
            json={"registrations": [{"contract_id": contract_id, "consumer_team_id": consumer_id}]},
        )

        # Second bulk create with skip_duplicates
        resp = await client.post(
            "/api/v1/bulk/registrations",
            json={
                "registrations": [{"contract_id": contract_id, "consumer_team_id": consumer_id}],
                "skip_duplicates": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1
        assert data["results"][0]["success"] is True
        assert data["results"][0]["details"].get("skipped") is True

    async def test_bulk_registrations_duplicate_fails(self, client: AsyncClient) -> None:
        """Duplicate registration fails when skip_duplicates is false."""
        # Create teams
        team_resp = await client.post("/api/v1/teams", json={"name": "fail-dup-team"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "fail-dup-consumer"})
        team_id = team_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "fail.dup.table", "owner_team_id": team_id}
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

        # First registration
        await client.post(
            "/api/v1/bulk/registrations",
            json={"registrations": [{"contract_id": contract_id, "consumer_team_id": consumer_id}]},
        )

        # Second bulk create should fail
        resp = await client.post(
            "/api/v1/bulk/registrations",
            json={
                "registrations": [{"contract_id": contract_id, "consumer_team_id": consumer_id}],
                "skip_duplicates": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert data["results"][0]["success"] is False
        assert "already exists" in data["results"][0]["error"]

    async def test_bulk_registrations_invalid_contract(self, client: AsyncClient) -> None:
        """Registration with invalid contract fails."""
        consumer_resp = await client.post("/api/v1/teams", json={"name": "inv-contract-consumer"})
        consumer_id = consumer_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/registrations",
            json={
                "registrations": [
                    {
                        "contract_id": "00000000-0000-0000-0000-000000000000",
                        "consumer_team_id": consumer_id,
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert "not found" in data["results"][0]["error"]


class TestBulkAssets:
    """Tests for bulk asset creation."""

    async def test_bulk_create_assets_success(self, client: AsyncClient) -> None:
        """Create multiple assets at once."""
        team_resp = await client.post("/api/v1/teams", json={"name": "bulk-assets-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {"fqn": "bulk.assets.table1", "owner_team_id": team_id},
                    {"fqn": "bulk.assets.table2", "owner_team_id": team_id},
                    {"fqn": "bulk.assets.table3", "owner_team_id": team_id},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0
        assert all(r["success"] for r in data["results"])
        assert all(r["id"] is not None for r in data["results"])

    async def test_bulk_assets_skip_duplicates(self, client: AsyncClient) -> None:
        """Skip duplicate assets when skip_duplicates is true."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dup-assets-team"})
        team_id = team_resp.json()["id"]

        # First create
        await client.post(
            "/api/v1/bulk/assets",
            json={"assets": [{"fqn": "dup.asset.table", "owner_team_id": team_id}]},
        )

        # Second create with skip_duplicates
        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [{"fqn": "dup.asset.table", "owner_team_id": team_id}],
                "skip_duplicates": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1
        assert data["results"][0]["details"].get("skipped") is True

    async def test_bulk_assets_duplicate_fails(self, client: AsyncClient) -> None:
        """Duplicate asset fails when skip_duplicates is false."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fail-dup-assets-team"})
        team_id = team_resp.json()["id"]

        # First create
        await client.post(
            "/api/v1/bulk/assets",
            json={"assets": [{"fqn": "fail.dup.asset", "owner_team_id": team_id}]},
        )

        # Second create should fail
        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [{"fqn": "fail.dup.asset", "owner_team_id": team_id}],
                "skip_duplicates": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert "already exists" in data["results"][0]["error"]

    async def test_bulk_assets_invalid_team(self, client: AsyncClient) -> None:
        """Asset with invalid team fails."""
        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {
                        "fqn": "inv.team.asset",
                        "owner_team_id": "00000000-0000-0000-0000-000000000000",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        # Could fail on authorization or team not found
        assert data["results"][0]["success"] is False

    async def test_bulk_assets_with_metadata(self, client: AsyncClient) -> None:
        """Create assets with metadata."""
        team_resp = await client.post("/api/v1/teams", json={"name": "meta-assets-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {
                        "fqn": "meta.asset.table",
                        "owner_team_id": team_id,
                        "metadata": {"source": "test", "priority": "high"},
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1


class TestBulkAcknowledgments:
    """Tests for bulk acknowledgment creation."""

    async def test_bulk_acknowledge_proposals_success(self, client: AsyncClient) -> None:
        """Acknowledge multiple proposals at once."""
        # Create producer and consumer teams
        producer_resp = await client.post("/api/v1/teams", json={"name": "bulk-ack-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "bulk-ack-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create multiple assets with contracts
        proposals = []
        for i in range(2):
            asset_resp = await client.post(
                "/api/v1/assets", json={"fqn": f"bulk.ack.table{i}", "owner_team_id": producer_id}
            )
            asset_id = asset_resp.json()["id"]

            # Create initial contract
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

            # Create breaking change to generate proposal
            proposal_resp = await client.post(
                f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
                json={
                    "version": "2.0.0",
                    "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    "compatibility_mode": "backward",
                },
            )
            proposals.append(proposal_resp.json()["proposal"]["id"])

        # Bulk acknowledge
        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": proposals[0],
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    },
                    {
                        "proposal_id": proposals[1],
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["succeeded"] == 2
        assert data["failed"] == 0
        # Both proposals should be auto-approved
        for result in data["results"]:
            assert result["success"] is True
            assert result["details"]["proposal_status"] == "approved"

    async def test_bulk_acknowledge_with_block(self, client: AsyncClient) -> None:
        """Blocking acknowledgment rejects proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "bulk-block-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "bulk-block-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset with contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bulk.block.table", "owner_team_id": producer_id}
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

        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": proposal_id,
                        "consumer_team_id": consumer_id,
                        "response": "blocked",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1
        assert data["results"][0]["details"]["proposal_status"] == "rejected"

    async def test_bulk_acknowledge_duplicate_fails(self, client: AsyncClient) -> None:
        """Duplicate acknowledgment fails."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "dup-ack-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "dup-ack-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dup.ack.table", "owner_team_id": producer_id}
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

        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # First acknowledgment
        await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": proposal_id,
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    }
                ]
            },
        )

        # Create new proposal since first was auto-approved
        proposal_resp2 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "3.0.0",
                "schema": {"type": "object", "properties": {}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id2 = proposal_resp2.json()["proposal"]["id"]

        # First ack for new proposal
        await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": proposal_id2,
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    }
                ]
            },
        )

        # Try duplicate ack - but proposal should be approved already
        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": proposal_id2,
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        # Should fail because already acknowledged or proposal not pending
        assert data["results"][0]["success"] is False

    async def test_bulk_acknowledge_invalid_proposal(self, client: AsyncClient) -> None:
        """Acknowledgment with invalid proposal fails."""
        consumer_resp = await client.post("/api/v1/teams", json={"name": "inv-prop-consumer"})
        consumer_id = consumer_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": "00000000-0000-0000-0000-000000000000",
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert "not found" in data["results"][0]["error"]

    async def test_bulk_acknowledge_continues_on_error(self, client: AsyncClient) -> None:
        """Bulk acknowledgment continues processing after error."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "cont-err-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "cont-err-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "cont.err.table", "owner_team_id": producer_id}
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

        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # First item invalid, second valid
        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={
                "acknowledgments": [
                    {
                        "proposal_id": "00000000-0000-0000-0000-000000000000",
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    },
                    {
                        "proposal_id": proposal_id,
                        "consumer_team_id": consumer_id,
                        "response": "approved",
                    },
                ],
                "continue_on_error": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert data["results"][0]["success"] is False
        assert data["results"][1]["success"] is True


class TestBulkValidation:
    """Tests for bulk request validation."""

    async def test_bulk_registrations_empty_list(self, client: AsyncClient) -> None:
        """Empty registrations list fails validation."""
        resp = await client.post(
            "/api/v1/bulk/registrations",
            json={"registrations": []},
        )
        assert resp.status_code == 422  # Validation error

    async def test_bulk_assets_empty_list(self, client: AsyncClient) -> None:
        """Empty assets list fails validation."""
        resp = await client.post(
            "/api/v1/bulk/assets",
            json={"assets": []},
        )
        assert resp.status_code == 422  # Validation error

    async def test_bulk_acknowledgments_empty_list(self, client: AsyncClient) -> None:
        """Empty acknowledgments list fails validation."""
        resp = await client.post(
            "/api/v1/bulk/acknowledgments",
            json={"acknowledgments": []},
        )
        assert resp.status_code == 422  # Validation error

    async def test_bulk_assets_invalid_fqn_format(self, client: AsyncClient) -> None:
        """Invalid FQN format fails validation."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fqn-validation-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {"fqn": "invalid-fqn", "owner_team_id": team_id},
                ]
            },
        )
        assert resp.status_code == 422
        assert "FQN must be dot-separated segments" in resp.text

    async def test_bulk_assets_valid_fqn_format(self, client: AsyncClient) -> None:
        """Valid FQN format passes validation."""
        team_resp = await client.post("/api/v1/teams", json={"name": "valid-fqn-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {"fqn": "database.schema.table", "owner_team_id": team_id},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["succeeded"] == 1

    async def test_bulk_assets_fqn_starts_with_number(self, client: AsyncClient) -> None:
        """FQN starting with number fails validation."""
        team_resp = await client.post("/api/v1/teams", json={"name": "num-fqn-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/bulk/assets",
            json={
                "assets": [
                    {"fqn": "1database.schema.table", "owner_team_id": team_id},
                ]
            },
        )
        assert resp.status_code == 422
        assert "FQN must be dot-separated segments" in resp.text
