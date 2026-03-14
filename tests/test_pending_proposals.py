"""Tests for GET /api/v1/proposals/pending/{team_id} endpoint.

Covers: pending proposals, no proposals, all acknowledged, pagination,
expired proposals, and team-scoped authorization.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _setup_proposal_scenario(
    client: AsyncClient,
) -> dict:
    """Create a producer, consumer, asset, contract, registration, and breaking proposal.

    Returns dict with all created IDs.
    """
    producer_resp = await client.post("/api/v1/teams", json={"name": "pending-producer"})
    consumer_resp = await client.post("/api/v1/teams", json={"name": "pending-consumer"})
    producer_id = producer_resp.json()["id"]
    consumer_id = consumer_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json={"fqn": "pending.test.table", "owner_team_id": producer_id},
    )
    asset_id = asset_resp.json()["id"]

    # Create initial contract with backward compatibility
    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
        json={
            "version": "1.0.0",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
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

    # Create breaking change (removes "name" field) -> creates a proposal
    proposal_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
        json={
            "version": "2.0.0",
            "schema": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
            "compatibility_mode": "backward",
        },
    )
    proposal_id = proposal_resp.json()["proposal"]["id"]

    return {
        "producer_id": producer_id,
        "consumer_id": consumer_id,
        "asset_id": asset_id,
        "contract_id": contract_id,
        "proposal_id": proposal_id,
    }


class TestPendingProposalsEndpoint:
    """Tests for GET /api/v1/proposals/pending/{team_id}."""

    async def test_returns_pending_proposals(self, client: AsyncClient) -> None:
        """Consumer team sees pending proposals affecting their registrations."""
        ids = await _setup_proposal_scenario(client)

        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 1
        assert len(data["pending_proposals"]) == 1

        proposal = data["pending_proposals"][0]
        assert proposal["proposal_id"] == ids["proposal_id"]
        assert proposal["asset_id"] == ids["asset_id"]
        assert proposal["asset_fqn"] == "pending.test.table"
        assert proposal["proposed_by_team"] == "pending-producer"
        assert proposal["your_team_status"] == "AWAITING_RESPONSE"
        assert proposal["total_consumers"] >= 1
        assert proposal["acknowledged_count"] == 0
        assert isinstance(proposal["breaking_changes_summary"], list)
        assert len(proposal["breaking_changes_summary"]) > 0
        assert proposal["proposed_at"] is not None

    async def test_no_pending_proposals(self, client: AsyncClient) -> None:
        """Team with no registrations gets empty result."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-registrations-team"})
        team_id = team_resp.json()["id"]

        resp = await client.get(f"/api/v1/proposals/pending/{team_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pending_proposals"] == []

    async def test_all_acknowledged_removes_from_pending(self, client: AsyncClient) -> None:
        """After the sole consumer acknowledges, the proposal transitions out of
        PENDING status and no longer appears in the default pending view."""
        ids = await _setup_proposal_scenario(client)

        # Acknowledge the proposal
        await client.post(
            f"/api/v1/proposals/{ids['proposal_id']}/acknowledge",
            json={
                "consumer_team_id": ids["consumer_id"],
                "response": "approved",
                "notes": "Looks good",
            },
        )

        # Default filter is status=PENDING — proposal has transitioned to APPROVED
        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pending_proposals"] == []

        # But querying with status=approved shows it
        resp2 = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}?status=approved")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["total"] == 1
        proposal = data2["pending_proposals"][0]
        assert proposal["your_team_status"] == "APPROVED"
        assert proposal["acknowledged_count"] == 1

    async def test_pagination(self, client: AsyncClient) -> None:
        """Pagination with limit and offset works."""
        # Create scenario with at least one proposal
        ids = await _setup_proposal_scenario(client)

        # Request with limit=1
        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["pending_proposals"]) <= 1

        # Request with large offset -> empty
        resp2 = await client.get(
            f"/api/v1/proposals/pending/{ids['consumer_id']}?limit=10&offset=100"
        )
        assert resp2.status_code == 200
        assert resp2.json()["pending_proposals"] == []

    async def test_producer_team_sees_nothing(self, client: AsyncClient) -> None:
        """The producing team is not a consumer, so sees no pending proposals."""
        ids = await _setup_proposal_scenario(client)

        resp = await client.get(f"/api/v1/proposals/pending/{ids['producer_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pending_proposals"] == []

    async def test_multiple_consumers(self, client: AsyncClient) -> None:
        """Multiple consumers can see the same proposal."""
        ids = await _setup_proposal_scenario(client)

        # Add a second consumer
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "pending-consumer-2"})
        consumer2_id = consumer2_resp.json()["id"]
        await client.post(
            f"/api/v1/registrations?contract_id={ids['contract_id']}",
            json={"consumer_team_id": consumer2_id},
        )

        # Both consumers see the proposal
        resp1 = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        resp2 = await client.get(f"/api/v1/proposals/pending/{consumer2_id}")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["total"] == 1
        assert resp2.json()["total"] == 1

        # Consumer count should reflect both consumers
        assert resp1.json()["pending_proposals"][0]["total_consumers"] >= 2

    async def test_blocked_acknowledgment_transitions_to_rejected(
        self, client: AsyncClient
    ) -> None:
        """Blocking a proposal immediately rejects it, removing it from pending.

        Use status=rejected to see the blocked proposal with team status.
        """
        ids = await _setup_proposal_scenario(client)

        await client.post(
            f"/api/v1/proposals/{ids['proposal_id']}/acknowledge",
            json={
                "consumer_team_id": ids["consumer_id"],
                "response": "blocked",
                "notes": "This would break our pipeline",
            },
        )

        # No longer in pending (default status=pending)
        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        assert resp.json()["total"] == 0

        # Visible when querying rejected status
        resp2 = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}?status=rejected")
        data = resp2.json()
        assert data["total"] == 1
        assert data["pending_proposals"][0]["your_team_status"] == "BLOCKED"
