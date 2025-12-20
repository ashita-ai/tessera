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
        assert "proposals" in data
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
