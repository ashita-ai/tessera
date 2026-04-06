"""Additional edge case tests for proposals API."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AssetDB

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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
                f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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
            f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
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


class TestProposalSoftDeletedAssets:
    """Tests that proposal endpoints correctly return 404 for soft-deleted assets."""

    async def _create_proposal_with_affected_team(
        self, client: AsyncClient, suffix: str
    ) -> tuple[str, str, str, str, str]:
        """Create a proposal setup that includes an affected downstream team.

        Returns: (owner_id, affected_team_id, upstream_asset_id, downstream_asset_id, proposal_id)
        """
        owner_resp = await client.post("/api/v1/teams", json={"name": f"sd-owner-{suffix}"})
        assert owner_resp.status_code == 201, f"Team create failed: {owner_resp.text}"
        owner = owner_resp.json()

        affected_resp = await client.post("/api/v1/teams", json={"name": f"sd-affected-{suffix}"})
        assert affected_resp.status_code == 201, f"Team create failed: {affected_resp.text}"
        affected = affected_resp.json()

        upstream_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": f"sd.upstream.{suffix}", "owner_team_id": owner["id"]},
        )
        assert upstream_resp.status_code == 201, f"Asset create failed: {upstream_resp.text}"
        upstream = upstream_resp.json()

        # Publish initial contract
        schema_v1 = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        await client.post(
            f"/api/v1/assets/{upstream['id']}/publish",
            params={"published_by": owner["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset and dependency so affected_teams is populated
        downstream = (
            await client.post(
                "/api/v1/assets",
                json={
                    "fqn": f"sd.downstream.{suffix}",
                    "owner_team_id": affected["id"],
                },
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # Breaking change creates a proposal
        schema_v2 = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/publish",
            params={"published_by": owner["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        proposal_id = result.json()["proposal"]["id"]

        return (
            owner["id"],
            affected["id"],
            upstream["id"],
            downstream["id"],
            proposal_id,
        )

    async def _soft_delete_asset(self, session: AsyncSession, asset_id: str) -> None:
        """Soft-delete an asset directly via ORM."""
        result = await session.execute(select(AssetDB).where(AssetDB.id == UUID(asset_id)))
        asset_db = result.scalar_one()
        asset_db.deleted_at = datetime.now(UTC)
        await session.commit()

    async def test_file_objection_returns_404_for_soft_deleted_asset(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        """file_objection returns 404 when the proposal's asset is soft-deleted."""
        (
            owner_id,
            affected_id,
            asset_id,
            _,
            proposal_id,
        ) = await self._create_proposal_with_affected_team(client, "obj_sd")

        # Soft-delete the upstream asset
        await self._soft_delete_asset(session, asset_id)

        # Attempt to file an objection — should 404 because the asset is gone
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": affected_id},
            json={"reason": "This should not work"},
        )
        assert resp.status_code == 404

    async def test_publish_from_proposal_returns_404_for_soft_deleted_asset(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        """publish_from_proposal returns 404 when the proposal's asset is soft-deleted."""
        owner_id, _, asset_id, _, proposal_id = await self._create_proposal_with_affected_team(
            client, "pub_sd"
        )

        # Force-approve so we can attempt to publish
        await client.post(
            f"/api/v1/proposals/{proposal_id}/force",
            params={"actor_id": owner_id},
        )

        # Soft-delete the upstream asset
        await self._soft_delete_asset(session, asset_id)

        # Attempt to publish from the approved proposal — should 404
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": owner_id},
        )
        assert resp.status_code == 404

    async def test_file_objection_deactivated_user_sets_name_to_none(
        self, client: AsyncClient
    ) -> None:
        """Deactivated objector_user_id succeeds but sets objector_user_name to None."""
        (
            owner_id,
            affected_id,
            asset_id,
            _,
            proposal_id,
        ) = await self._create_proposal_with_affected_team(client, "deact_user")

        # Create a user and then deactivate them
        user_resp = await client.post(
            "/api/v1/users",
            json={"username": "deact-objector", "name": "Soon Deactivated"},
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        deact_resp = await client.delete(f"/api/v1/users/{user_id}")
        assert deact_resp.status_code == 204

        # File objection with the deactivated user
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={
                "objector_team_id": affected_id,
                "objector_user_id": user_id,
            },
            json={"reason": "Filing with deactivated user"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "objection_filed"
        assert data["objection"]["objected_by_user_id"] == user_id
        assert data["objection"]["objected_by_user_name"] is None
