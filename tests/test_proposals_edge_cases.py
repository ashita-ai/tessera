"""Additional edge case tests for proposals API."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestProposalEdgeCases:
    """Edge case tests for proposals API."""

    async def _create_proposal_setup(
        self, client: AsyncClient, suffix: str = ""
    ) -> tuple[str, str, str, str]:
        """Create standard setup: producer, consumer, asset with contract, consumer registered.

        Returns: (producer_id, consumer_id, asset_id, proposal_id)
        """
        producer_resp = await client.post("/api/v1/teams", json={"name": f"producer-{suffix}"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": f"consumer-{suffix}"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": f"test.proposal.{suffix}", "owner_team_id": producer_id},
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

        return producer_id, consumer_id, asset_id, proposal_id


class TestListProposals:
    """Tests for listing proposals with filters."""

    async def test_list_proposals_filter_by_asset_id(self, client: AsyncClient):
        """Filter proposals by asset_id."""
        team_resp = await client.post("/api/v1/teams", json={"name": "asset-filter-team"})
        team_id = team_resp.json()["id"]

        # Create two assets
        asset1_resp = await client.post(
            "/api/v1/assets", json={"fqn": "filter.asset1.table", "owner_team_id": team_id}
        )
        asset2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "filter.asset2.table", "owner_team_id": team_id}
        )
        asset1_id = asset1_resp.json()["id"]
        asset2_id = asset2_resp.json()["id"]

        # Create contracts for both
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
            # Create breaking change
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
        assert all(p["asset_id"] == asset1_id for p in data["results"])

    async def test_list_proposals_filter_by_proposed_by(self, client: AsyncClient):
        """Filter proposals by proposed_by team."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "proposer-filter-a"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "proposer-filter-b"})
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        # Each team creates an asset and proposal
        for team_id, suffix in [(team1_id, "a"), (team2_id, "b")]:
            asset_resp = await client.post(
                "/api/v1/assets",
                json={"fqn": f"proposer.filter.{suffix}", "owner_team_id": team_id},
            )
            asset_id = asset_resp.json()["id"]

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

        # Filter by team1
        resp = await client.get(f"/api/v1/proposals?proposed_by={team1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["proposed_by"] == team1_id for p in data["results"])

    async def test_list_proposals_pagination(self, client: AsyncClient):
        """Test pagination of proposals."""
        team_resp = await client.post("/api/v1/teams", json={"name": "page-test-team"})
        team_id = team_resp.json()["id"]

        # Create 5 assets with proposals
        for i in range(5):
            asset_resp = await client.post(
                "/api/v1/assets",
                json={"fqn": f"page.test.table{i}", "owner_team_id": team_id},
            )
            asset_id = asset_resp.json()["id"]

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

        # Get first page
        resp1 = await client.get("/api/v1/proposals?limit=2&offset=0")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["results"]) == 2

        # Get second page
        resp2 = await client.get("/api/v1/proposals?limit=2&offset=2")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["results"]) == 2

        # Ensure different results
        ids1 = {p["id"] for p in data1["results"]}
        ids2 = {p["id"] for p in data2["results"]}
        assert ids1.isdisjoint(ids2)


class TestAcknowledgeEdgeCases:
    """Edge cases for acknowledgment flow."""

    async def test_acknowledge_with_invalid_consumer_team(self, client: AsyncClient):
        """Acknowledge with non-existent consumer team returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "inv-cons-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "inv.consumer.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

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

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        fake_team_id = str(uuid4())
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": fake_team_id, "response": "approved"},
        )
        assert resp.status_code == 404

    async def test_acknowledge_proposal_not_found(self, client: AsyncClient):
        """Acknowledge non-existent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "ack-notfound-team"})
        team_id = team_resp.json()["id"]

        fake_proposal_id = str(uuid4())
        resp = await client.post(
            f"/api/v1/proposals/{fake_proposal_id}/acknowledge",
            json={"consumer_team_id": team_id, "response": "approved"},
        )
        assert resp.status_code == 404

    async def test_acknowledge_with_migration_deadline(self, client: AsyncClient):
        """Acknowledgment can include migration deadline."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "mig-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "mig-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "mig.deadline.table", "owner_team_id": producer_id}
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
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "migration_deadline": "2025-06-01T00:00:00Z",
                "notes": "Will migrate by Q2",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["migration_deadline"] is not None


class TestMultipleConsumerApproval:
    """Tests for multi-consumer acknowledgment flows."""

    async def test_auto_approval_with_multiple_consumers(self, client: AsyncClient):
        """Proposal auto-approves when all consumers acknowledge."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "multi-prod"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "multi-cons-a"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "multi-cons-b"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "multi.consumer.table", "owner_team_id": producer_id},
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

        # Register both consumers
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
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

        # First consumer acknowledges - should still be pending
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert status_resp.json()["status"] == "pending"

        # Second consumer acknowledges - should auto-approve
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer2_id, "response": "approved"},
        )
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert status_resp.json()["status"] == "approved"

    async def test_partial_approval_then_block(self, client: AsyncClient):
        """One consumer approves, second blocks - should reject."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "partial-prod"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "partial-cons-a"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "partial-cons-b"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "partial.block.table", "owner_team_id": producer_id},
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
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
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

        # First consumer approves
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )

        # Second consumer blocks - should reject immediately
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer2_id, "response": "blocked"},
        )
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert status_resp.json()["status"] == "rejected"


class TestForceApproveEdgeCases:
    """Edge cases for force approval."""

    async def test_force_approve_not_found(self, client: AsyncClient):
        """Force approve non-existent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-notfound"})
        team_id = team_resp.json()["id"]

        fake_proposal_id = str(uuid4())
        resp = await client.post(f"/api/v1/proposals/{fake_proposal_id}/force?actor_id={team_id}")
        assert resp.status_code == 404

    async def test_force_approve_already_approved(self, client: AsyncClient):
        """Force approve already approved proposal returns 400."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-approved"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "force.approved.table", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

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

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve once
        await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")

        # Try to force approve again
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")
        assert resp.status_code == 400


class TestWithdrawEdgeCases:
    """Edge cases for withdraw."""

    async def test_withdraw_not_found(self, client: AsyncClient):
        """Withdraw non-existent proposal returns 404."""
        fake_proposal_id = str(uuid4())
        resp = await client.post(f"/api/v1/proposals/{fake_proposal_id}/withdraw")
        assert resp.status_code == 404


class TestPublishEdgeCases:
    """Edge cases for publishing from proposals."""

    async def test_publish_not_found(self, client: AsyncClient):
        """Publish from non-existent proposal returns 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "pub-notfound"})
        team_id = team_resp.json()["id"]

        fake_proposal_id = str(uuid4())
        resp = await client.post(
            f"/api/v1/proposals/{fake_proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert resp.status_code == 404

    async def test_publish_rejected_proposal_fails(self, client: AsyncClient):
        """Cannot publish from rejected proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "pub-reject-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "pub-reject-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "pub.rejected.table", "owner_team_id": producer_id},
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

        # Block the proposal
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

    async def test_publish_withdrawn_proposal_fails(self, client: AsyncClient):
        """Cannot publish from withdrawn proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "pub-withdraw-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "pub.withdrawn.table", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

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


class TestProposalStatusDetails:
    """Tests for detailed proposal status endpoint."""

    async def test_proposal_status_not_found(self, client: AsyncClient):
        """Get status of non-existent proposal returns 404."""
        fake_proposal_id = str(uuid4())
        resp = await client.get(f"/api/v1/proposals/{fake_proposal_id}/status")
        assert resp.status_code == 404

    async def test_proposal_status_with_multiple_acks(self, client: AsyncClient):
        """Status shows all acknowledgments and pending consumers."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "status-multi-prod"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "status-multi-a"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "status-multi-b"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "status.multi.table", "owner_team_id": producer_id},
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
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
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

        # One consumer acknowledges
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )

        # Check status
        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumers"]["total"] == 2
        assert data["consumers"]["acknowledged"] == 1
        assert data["consumers"]["pending"] == 1
        assert len(data["acknowledgments"]) == 1
        assert len(data["pending_consumers"]) == 1

    async def test_proposal_status_shows_breaking_changes(self, client: AsyncClient):
        """Status includes breaking changes details."""
        team_resp = await client.post("/api/v1/teams", json={"name": "break-detail-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "breaking.detail.table", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

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

        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "breaking_changes" in data
        assert len(data["breaking_changes"]) > 0
