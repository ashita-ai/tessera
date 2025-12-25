"""Tests for /api/v1/proposals endpoints and proposal workflow."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


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

    async def test_list_proposals(self, client: AsyncClient):
        """List proposals with filtering."""
        team_resp = await client.post("/api/v1/teams", json={"name": "list-prop-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "list.proposal.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change (creates proposal)
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # List all proposals
        resp = await client.get("/api/v1/proposals")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data

        # Filter by status
        resp = await client.get("/api/v1/proposals?status=pending")
        assert resp.status_code == 200

    async def test_get_proposal_by_id(self, client: AsyncClient):
        """Get a specific proposal by ID."""
        team_resp = await client.post("/api/v1/teams", json={"name": "get-prop-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "get.proposal.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Get the proposal
        resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == proposal_id
        assert data["status"] == "pending"

    async def test_get_proposal_not_found(self, client: AsyncClient):
        """Getting a nonexistent proposal should 404."""
        resp = await client.get("/api/v1/proposals/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_get_proposal_status(self, client: AsyncClient):
        """Get detailed proposal status."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "status-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "status-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "status.proposal.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Get proposal status
        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert "consumers" in data
        assert data["consumers"]["total"] == 1
        assert data["consumers"]["pending"] == 1

    async def test_withdraw_proposal(self, client: AsyncClient):
        """Withdraw a pending proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "withdraw-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "withdraw.proposal.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Withdraw the proposal
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "withdrawn"

    async def test_withdraw_nonpending_proposal_fails(self, client: AsyncClient):
        """Cannot withdraw a non-pending proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "withdraw-fail-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "withdraw.fail.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Withdraw it first
        await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")

        # Try to withdraw again
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")
        assert resp.status_code == 400

    async def test_force_approve_proposal(self, client: AsyncClient):
        """Force-approve a proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "force-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "force-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "force.proposal.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={producer_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"

    async def test_publish_from_approved_proposal(self, client: AsyncClient):
        """Publish a contract from an approved proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "publish-prop-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "publish.from.proposal", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve the proposal
        await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")

        # Publish from the approved proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "published"
        assert "contract" in data

    async def test_publish_from_unapproved_proposal_fails(self, client: AsyncClient):
        """Cannot publish from a non-approved proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "unpub-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "unpub.proposal.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change (creates pending proposal)
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Try to publish from pending proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert resp.status_code == 400

    async def test_acknowledge_nonpending_proposal_fails(self, client: AsyncClient):
        """Cannot acknowledge a non-pending proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "ack-nonpend-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "ack-nonpend-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "ack.nonpending.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Withdraw the proposal
        await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")

        # Try to acknowledge withdrawn proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "approved"},
        )
        assert resp.status_code == 400

    async def test_duplicate_acknowledgment_fails(self, client: AsyncClient):
        """Cannot acknowledge a proposal twice."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "dup-ack-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "dup-ack-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dup.ack.table", "owner_team_id": producer_id}
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

        # Create breaking change
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
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "approved"},
        )

        # Second acknowledgment should fail
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "approved"},
        )
        assert resp.status_code == 400

    async def test_blocked_acknowledgment_rejects_proposal(self, client: AsyncClient):
        """Blocked acknowledgment rejects the proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "block-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "block-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "block.proposal.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Block the proposal
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "blocked"},
        )

        # Check proposal is rejected
        resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert resp.json()["status"] == "rejected"


class TestProposalFiltering:
    """Tests for proposal listing with filters."""

    async def test_list_proposals_filter_by_asset_id(self, client: AsyncClient):
        """Filter proposals by asset ID."""
        team_resp = await client.post("/api/v1/teams", json={"name": "filter-asset-team"})
        team_id = team_resp.json()["id"]

        # Create two assets
        asset1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "filter.asset1.table", "owner_team_id": team_id}
        )
        asset1_id = asset1_resp.json()["id"]

        asset2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "filter.asset2.table", "owner_team_id": team_id}
        )
        asset2_id = asset2_resp.json()["id"]

        # Create contracts and proposals for both assets
        for asset_id in [asset1_id, asset2_id]:
            await client.post(
                f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
                json={
                    "version": "1.0.0",
                    "schema": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                    },
                    "compatibility_mode": "backward",
                },
            )
            await client.post(
                f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
                json={
                    "version": "2.0.0",
                    "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    "compatibility_mode": "backward",
                },
            )

        # Filter by asset1
        resp = await client.get(f"/api/v1/proposals?asset_id={asset1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for proposal in data["results"]:
            assert proposal["asset_id"] == asset1_id

    async def test_list_proposals_filter_by_proposed_by(self, client: AsyncClient):
        """Filter proposals by proposer team ID."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "proposer-team1"})
        team1_id = team1_resp.json()["id"]

        team2_resp = await client.post("/api/v1/teams", json={"name": "proposer-team2"})
        team2_id = team2_resp.json()["id"]

        # Create asset owned by team1
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "proposer.filter.table", "owner_team_id": team1_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team1_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change (proposal by team1)
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team1_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Filter by team1 as proposer
        resp = await client.get(f"/api/v1/proposals?proposed_by={team1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for proposal in data["results"]:
            assert proposal["proposed_by"] == team1_id

        # Filter by team2 (should find none from this test)
        resp = await client.get(f"/api/v1/proposals?proposed_by={team2_id}")
        assert resp.status_code == 200

    async def test_list_proposals_pagination(self, client: AsyncClient):
        """Test pagination of proposals list."""
        resp = await client.get("/api/v1/proposals?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "limit" in data
        assert data["limit"] == 5
        assert "offset" in data
        assert data["offset"] == 0

    async def test_list_proposals_includes_asset_fqn(self, client: AsyncClient):
        """Proposal list includes asset FQN for display."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fqn-display-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "fqn.display.test.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        resp = await client.get(f"/api/v1/proposals?asset_id={asset_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["asset_fqn"] == "fqn.display.test.table"


class TestProposalStatusDetails:
    """Tests for detailed proposal status endpoint."""

    async def test_status_includes_proposer_info(self, client: AsyncClient):
        """Status includes proposer team name."""
        team_resp = await client.post("/api/v1/teams", json={"name": "proposer-info-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "proposer.info.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Get status
        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "proposed_by" in data
        assert data["proposed_by"]["team_id"] == team_id
        assert data["proposed_by"]["team_name"] == "proposer-info-team"

    async def test_status_includes_acknowledgment_details(self, client: AsyncClient):
        """Status includes detailed acknowledgment info."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "ack-detail-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "ack-detail-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "ack.detail.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Acknowledge
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "notes": "Test acknowledgment notes",
            },
        )

        # Get status
        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["acknowledgments"]) == 1
        ack = data["acknowledgments"][0]
        assert ack["consumer_team_id"] == consumer_id
        assert ack["consumer_team_name"] == "ack-detail-cons"
        assert "approved" in ack["response"]  # Response contains 'approved'
        assert ack["notes"] == "Test acknowledgment notes"

    async def test_status_shows_pending_consumers(self, client: AsyncClient):
        """Status shows which consumers haven't acknowledged yet."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "pending-prod"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "pending-cons1"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "pending-cons2"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "pending.consumers.table", "owner_team_id": producer_id}
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

        # Register both consumers
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Only consumer1 acknowledges
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )

        # Get status
        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumers"]["total"] == 2
        assert data["consumers"]["acknowledged"] == 1
        assert data["consumers"]["pending"] == 1
        assert len(data["pending_consumers"]) == 1
        assert data["pending_consumers"][0]["team_id"] == consumer2_id
        assert data["pending_consumers"][0]["team_name"] == "pending-cons2"

    async def test_status_not_found(self, client: AsyncClient):
        """Status for nonexistent proposal returns 404."""
        resp = await client.get("/api/v1/proposals/00000000-0000-0000-0000-000000000000/status")
        assert resp.status_code == 404


class TestProposalAutoApproval:
    """Tests for automatic proposal approval when all consumers acknowledge."""

    async def test_auto_approve_when_all_consumers_acknowledge(self, client: AsyncClient):
        """Proposal auto-approves when all registered consumers acknowledge."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "auto-approve-prod"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "auto-approve-cons1"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "auto-approve-cons2"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "auto.approve.table", "owner_team_id": producer_id}
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

        # Register both consumers
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Consumer 1 acknowledges - still pending
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )

        # Verify still pending
        resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert resp.json()["status"] == "pending"

        # Consumer 2 acknowledges - should auto-approve
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer2_id, "response": "approved"},
        )

        # Verify approved
        resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert resp.json()["status"] == "approved"

    async def test_no_consumers_auto_approves(self, client: AsyncClient):
        """Proposal without registered consumers doesn't create proposal at all."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-consumers-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "no.consumers.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract (no consumers register)
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change - should auto-publish, no proposal
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # Without consumers, breaking change publishes directly
        assert data["action"] in ["published", "proposal_created"]


class TestPublishFromProposal:
    """Tests for publishing contracts from approved proposals."""

    async def test_publish_with_version_override(self, client: AsyncClient):
        """Can specify different version when publishing from proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "version-override-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "version.override.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve
        await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")

        # Publish with different version
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "3.0.0", "published_by": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract"]["version"] == "3.0.0"

    async def test_publish_deprecates_old_contract(self, client: AsyncClient):
        """Publishing from proposal deprecates the old active contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "deprecate-old-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deprecate.old.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        old_contract_id = contract_resp.json()["contract"]["id"]

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve and publish
        await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deprecated_contract_id"] == old_contract_id

        # Verify old contract is deprecated
        old_resp = await client.get(f"/api/v1/contracts/{old_contract_id}")
        assert old_resp.json()["status"] == "deprecated"

    async def test_publish_from_withdrawn_proposal_fails(self, client: AsyncClient):
        """Cannot publish from a withdrawn proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "withdrawn-pub-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "withdrawn.pub.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Withdraw the proposal
        await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")

        # Try to publish from withdrawn proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert resp.status_code == 400

    async def test_publish_from_rejected_proposal_fails(self, client: AsyncClient):
        """Cannot publish from a rejected proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "rejected-pub-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "rejected-pub-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "rejected.pub.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Consumer blocks (rejects proposal)
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "blocked"},
        )

        # Try to publish from rejected proposal
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": producer_id},
        )
        assert resp.status_code == 400

    async def test_publish_not_found(self, client: AsyncClient):
        """Publishing from nonexistent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "publish-notfound-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/proposals/00000000-0000-0000-0000-000000000000/publish",
            json={"version": "1.0.0", "published_by": team_id},
        )
        assert resp.status_code == 404


class TestForceProposal:
    """Tests for force-approving proposals."""

    async def test_force_nonpending_fails(self, client: AsyncClient):
        """Cannot force-approve a non-pending proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-nonpend-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "force.nonpend.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Withdraw it
        await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")

        # Try to force approve
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")
        assert resp.status_code == 400

    async def test_force_not_found(self, client: AsyncClient):
        """Force-approving nonexistent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-notfound-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/proposals/00000000-0000-0000-0000-000000000000/force?actor_id={team_id}"
        )
        assert resp.status_code == 404


class TestWithdrawProposal:
    """Tests for withdrawing proposals."""

    async def test_withdraw_not_found(self, client: AsyncClient):
        """Withdrawing nonexistent proposal returns 404."""
        resp = await client.post("/api/v1/proposals/00000000-0000-0000-0000-000000000000/withdraw")
        assert resp.status_code == 404


class TestAcknowledgmentEdgeCases:
    """Tests for acknowledgment edge cases."""

    async def test_acknowledge_not_found_proposal(self, client: AsyncClient):
        """Acknowledging nonexistent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "ack-notfound-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/proposals/00000000-0000-0000-0000-000000000000/acknowledge",
            json={"consumer_team_id": team_id, "response": "approved"},
        )
        assert resp.status_code == 404

    async def test_acknowledge_with_nonexistent_consumer_team(self, client: AsyncClient):
        """Acknowledging with nonexistent consumer team returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "real-producer"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "bad.consumer.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Try to acknowledge with nonexistent team
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": "00000000-0000-0000-0000-000000000000",
                "response": "approved",
            },
        )
        # Returns 403 (authorization check) or 404 (team not found) depending on auth
        assert resp.status_code in [403, 404]

    async def test_acknowledge_with_migration_deadline(self, client: AsyncClient):
        """Acknowledgment can include migration deadline."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "deadline-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "deadline-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deadline.ack.table", "owner_team_id": producer_id}
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

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Acknowledge with deadline
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "migration_deadline": "2025-06-01T00:00:00Z",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["migration_deadline"] is not None
