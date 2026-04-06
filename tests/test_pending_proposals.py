"""Tests for GET /api/v1/proposals/pending/{team_id} endpoint."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _setup_proposal_scenario(client: AsyncClient) -> dict:
    """Create a producer, consumer, asset, contract, registration, and breaking proposal.

    Returns a dict with all the IDs needed for testing.
    """
    producer_resp = await client.post("/api/v1/teams", json={"name": "pending-producer"})
    assert producer_resp.status_code == 201
    producer_id = producer_resp.json()["id"]

    consumer_resp = await client.post("/api/v1/teams", json={"name": "pending-consumer"})
    assert consumer_resp.status_code == 201
    consumer_id = consumer_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json={"fqn": "prod.core.dim_customers", "owner_team_id": producer_id},
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    # Publish initial contract
    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
        json={
            "version": "1.0.0",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
            },
            "compatibility_mode": "backward",
        },
    )
    assert contract_resp.status_code == 201
    contract_id = contract_resp.json()["contract"]["id"]

    # Register consumer
    reg_resp = await client.post(
        f"/api/v1/registrations?contract_id={contract_id}",
        json={"consumer_team_id": consumer_id},
    )
    assert reg_resp.status_code == 201

    # Publish breaking change (removes 'email' field) → creates proposal
    breaking_resp = await client.post(
        f"/api/v1/assets/{asset_id}/publish?published_by={producer_id}",
        json={
            "version": "2.0.0",
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
    assert breaking_resp.status_code == 201
    assert (
        "proposal" in breaking_resp.json()
    ), f"Expected a proposal for breaking change, got: {breaking_resp.json()}"
    proposal_id = breaking_resp.json()["proposal"]["id"]

    return {
        "producer_id": producer_id,
        "consumer_id": consumer_id,
        "asset_id": asset_id,
        "contract_id": contract_id,
        "proposal_id": proposal_id,
    }


class TestPendingProposals:
    """Tests for the pending proposals team inbox endpoint."""

    async def test_returns_pending_proposals(self, client: AsyncClient):
        """Consumer team sees proposals awaiting their acknowledgment."""
        ids = await _setup_proposal_scenario(client)

        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 1
        assert len(data["pending_proposals"]) == 1

        proposal = data["pending_proposals"][0]
        assert proposal["proposal_id"] == ids["proposal_id"]
        assert proposal["asset_id"] == ids["asset_id"]
        assert proposal["asset_fqn"] == "prod.core.dim_customers"
        assert proposal["proposed_by_team"] == "pending-producer"
        assert proposal["your_team_status"] == "AWAITING_RESPONSE"
        assert proposal["total_consumers"] >= 1
        assert proposal["acknowledged_count"] == 0
        assert isinstance(proposal["breaking_changes_summary"], list)
        assert len(proposal["breaking_changes_summary"]) > 0

    async def test_empty_when_no_proposals(self, client: AsyncClient):
        """Team with no registrations gets an empty list."""
        team_resp = await client.post("/api/v1/teams", json={"name": "lonely-team"})
        team_id = team_resp.json()["id"]

        resp = await client.get(f"/api/v1/proposals/pending/{team_id}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 0
        assert data["pending_proposals"] == []

    async def test_empty_after_acknowledgment(self, client: AsyncClient):
        """Proposals disappear from pending list after the team acknowledges."""
        ids = await _setup_proposal_scenario(client)

        # Acknowledge the proposal
        ack_resp = await client.post(
            f"/api/v1/proposals/{ids['proposal_id']}/acknowledge",
            json={
                "consumer_team_id": ids["consumer_id"],
                "response": "approved",
                "notes": "Looks good",
            },
        )
        assert ack_resp.status_code == 201

        # Pending list should now be empty for this team
        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["pending_proposals"] == []

    async def test_pagination(self, client: AsyncClient):
        """Pagination works with limit and offset."""
        ids = await _setup_proposal_scenario(client)

        # With limit=1, offset=0, should get one result
        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 1
        assert data["offset"] == 0
        assert len(data["pending_proposals"]) == 1

        # With offset beyond total, should get empty list
        resp = await client.get(
            f"/api/v1/proposals/pending/{ids['consumer_id']}?limit=1&offset=100"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["pending_proposals"]) == 0

    async def test_producer_team_sees_nothing(self, client: AsyncClient):
        """The proposing team has no pending proposals (they're not a consumer)."""
        ids = await _setup_proposal_scenario(client)

        resp = await client.get(f"/api/v1/proposals/pending/{ids['producer_id']}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_nonexistent_team_returns_404(self, client: AsyncClient):
        """Requesting pending proposals for a non-existent team returns 404."""
        import uuid

        fake_team_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/proposals/pending/{fake_team_id}")
        assert resp.status_code == 404

    async def test_multiple_consumers(self, client: AsyncClient):
        """Multiple consumer teams each see their own pending status independently."""
        ids = await _setup_proposal_scenario(client)

        # Add a second consumer
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "pending-consumer-2"})
        consumer2_id = consumer2_resp.json()["id"]

        # Register second consumer on the same contract
        await client.post(
            f"/api/v1/registrations?contract_id={ids['contract_id']}",
            json={"consumer_team_id": consumer2_id},
        )

        # Both consumers should see the proposal
        resp1 = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        resp2 = await client.get(f"/api/v1/proposals/pending/{consumer2_id}")
        assert resp1.json()["total"] == 1
        assert resp2.json()["total"] == 1

        # First consumer acknowledges
        await client.post(
            f"/api/v1/proposals/{ids['proposal_id']}/acknowledge",
            json={
                "consumer_team_id": ids["consumer_id"],
                "response": "approved",
                "notes": "ok",
            },
        )

        # First consumer's list is now empty, second still sees it
        resp1 = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}")
        resp2 = await client.get(f"/api/v1/proposals/pending/{consumer2_id}")
        assert resp1.json()["total"] == 0
        assert resp2.json()["total"] == 1

        # Acknowledged count should reflect the first team's ack
        assert resp2.json()["pending_proposals"][0]["acknowledged_count"] == 1

    async def test_response_includes_pagination_fields(self, client: AsyncClient):
        """Response always includes total, limit, and offset fields."""
        ids = await _setup_proposal_scenario(client)

        resp = await client.get(f"/api/v1/proposals/pending/{ids['consumer_id']}?limit=5&offset=0")
        data = resp.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert data["limit"] == 5
        assert data["offset"] == 0
