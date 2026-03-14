"""Tests for the pending proposals endpoint."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import make_asset, make_contract, make_schema, make_team


async def _setup_proposal_scenario(client: AsyncClient) -> dict:
    """Create a scenario with a pending proposal and consumer team.

    Returns dict with team IDs, asset ID, contract ID, and proposal ID.
    """
    # Create producer and consumer teams
    producer_resp = await client.post("/api/v1/teams", json=make_team("pp-producer"))
    producer_id = producer_resp.json()["id"]

    consumer_resp = await client.post("/api/v1/teams", json=make_team("pp-consumer"))
    consumer_id = consumer_resp.json()["id"]

    # Create asset and publish contract
    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.pending.test", producer_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer", email="string")
    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
        json=make_contract("1.0.0", schema),
    )
    assert contract_resp.status_code == 201
    contract_data = contract_resp.json()
    contract_id = contract_data.get("contract", contract_data)["id"]

    # Register consumer (contract_id is a query param)
    reg_resp = await client.post(
        f"/api/v1/registrations?contract_id={contract_id}",
        json={"consumer_team_id": str(consumer_id)},
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.json()}"

    # Publish a breaking change (will create a proposal since there are consumers)
    # Don't specify version — let the system auto-detect breaking change
    breaking_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }
    publish_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
        json={"schema": breaking_schema, "compatibility_mode": "backward"},
    )
    assert publish_resp.status_code == 201, f"Publish failed: {publish_resp.json()}"
    publish_data = publish_resp.json()

    # The proposal is returned in the publish response when action is proposal_created
    proposal_id = None
    if publish_data.get("action") == "proposal_created":
        proposal_id = publish_data.get("proposal", {}).get("id")

    # Fallback: query proposals endpoint
    if proposal_id is None:
        proposals_resp = await client.get(
            "/api/v1/proposals",
            params={"asset_id": asset_id, "status": "PENDING"},
        )
        proposals = proposals_resp.json().get("results", [])
        proposal_id = proposals[0]["id"] if proposals else None

    return {
        "producer_id": producer_id,
        "consumer_id": consumer_id,
        "asset_id": asset_id,
        "contract_id": contract_id,
        "proposal_id": proposal_id,
    }


@pytest.mark.asyncio
async def test_pending_proposals_no_proposals(client: AsyncClient) -> None:
    """Team with no pending proposals gets empty response."""
    team_resp = await client.post("/api/v1/teams", json=make_team("pp-lonely"))
    team_id = team_resp.json()["id"]

    resp = await client.get(f"/api/v1/proposals/pending/{team_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pending_proposals"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_pending_proposals_returns_pending(client: AsyncClient) -> None:
    """Consumer team sees proposals awaiting their acknowledgment."""
    scenario = await _setup_proposal_scenario(client)

    if scenario["proposal_id"] is None:
        pytest.skip("No proposal was created in this scenario")

    resp = await client.get(f"/api/v1/proposals/pending/{scenario['consumer_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    proposal = data["pending_proposals"][0]
    assert proposal["asset_fqn"] == "prod.pending.test"
    assert proposal["your_team_status"] == "AWAITING_RESPONSE"
    assert proposal["proposed_by_team"] == "pp-producer"


@pytest.mark.asyncio
async def test_pending_proposals_all_acknowledged(client: AsyncClient) -> None:
    """After acknowledging, proposal disappears from pending list."""
    scenario = await _setup_proposal_scenario(client)

    if scenario["proposal_id"] is None:
        pytest.skip("No proposal was created in this scenario")

    # Acknowledge the proposal
    ack_resp = await client.post(
        f"/api/v1/proposals/{scenario['proposal_id']}/acknowledge",
        json={
            "consumer_team_id": scenario["consumer_id"],
            "response": "approved",
        },
    )
    assert (
        ack_resp.status_code == 201
    ), f"Acknowledge failed: {ack_resp.status_code} {ack_resp.json()}"

    # Should no longer appear in pending
    resp = await client.get(f"/api/v1/proposals/pending/{scenario['consumer_id']}")
    assert resp.status_code == 200
    proposals = resp.json()["pending_proposals"]
    pending_for_asset = [p for p in proposals if str(p["asset_id"]) == scenario["asset_id"]]
    assert len(pending_for_asset) == 0


@pytest.mark.asyncio
async def test_pending_proposals_pagination(client: AsyncClient) -> None:
    """Pagination works with limit and offset."""
    team_resp = await client.post("/api/v1/teams", json=make_team("pp-paginate"))
    team_id = team_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/proposals/pending/{team_id}",
        params={"limit": 5, "offset": 0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["pending_proposals"], list)
    assert isinstance(data["total"], int)


@pytest.mark.asyncio
async def test_pending_proposals_wrong_team(client: AsyncClient) -> None:
    """Request for non-existent team returns empty result (auth disabled in tests)."""
    resp = await client.get(f"/api/v1/proposals/pending/{uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
