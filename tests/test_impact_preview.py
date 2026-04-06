"""Tests for the impact preview endpoint."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import make_asset, make_contract, make_schema, make_team


async def _publish_contract(
    client: AsyncClient,
    asset_id: str,
    team_id: str,
    version: str,
    schema: dict,
    **kwargs,
) -> dict:
    """Helper to publish a contract with published_by query param.

    Returns the contract dict from the response.
    """
    resp = await client.post(
        f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
        json=make_contract(version, schema, **kwargs),
    )
    assert resp.status_code == 201, f"Contract creation failed: {resp.json()}"
    data = resp.json()
    # Response wraps contract in a 'contract' key
    return data.get("contract", data)


@pytest.mark.asyncio
async def test_impact_preview_non_breaking_change(client: AsyncClient) -> None:
    """Non-breaking change returns is_breaking=False with no migration suggestions."""
    team_resp = await client.post("/api/v1/teams", json=make_team("preview-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.test", team_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer", name="string")
    await _publish_contract(client, asset_id, team_id, "1.0.0", schema)

    # Propose a non-breaking change (add optional field)
    proposed = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},
        },
        "required": ["id", "name"],
    }

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={"proposed_schema": proposed},
    )
    assert resp.status_code == 200, f"Impact preview failed: {resp.json()}"
    data = resp.json()
    assert data["is_breaking"] is False
    assert "change_type" in data
    assert data["breaking_changes"] == []
    assert data["would_create_proposal"] is False
    assert data["proposal_would_notify"] == []
    assert data["migration_suggestions"] == []
    assert data["current_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_impact_preview_breaking_with_consumers(client: AsyncClient) -> None:
    """Breaking change with consumers returns is_breaking=True and would_create_proposal=True."""
    producer_resp = await client.post("/api/v1/teams", json=make_team("producer-team"))
    producer_id = producer_resp.json()["id"]

    consumer_resp = await client.post("/api/v1/teams", json=make_team("consumer-team"))
    consumer_id = consumer_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.breaking", producer_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer", email="string")
    contract = await _publish_contract(client, asset_id, producer_id, "1.0.0", schema)
    contract_id = contract["id"]

    # Register consumer (contract_id is a query param, not in body)
    reg_resp = await client.post(
        f"/api/v1/registrations?contract_id={contract_id}",
        json={"consumer_team_id": str(consumer_id)},
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.json()}"

    # Propose breaking change: remove email
    proposed = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={"proposed_schema": proposed},
    )
    assert resp.status_code == 200, f"Impact preview failed: {resp.json()}"
    data = resp.json()
    assert data["is_breaking"] is True
    assert len(data["breaking_changes"]) > 0
    # With consumers registered, a proposal would be created
    assert (
        len(data["affected_consumers"]) > 0
    ), f"Expected consumers but got: {data['affected_consumers']}"
    assert data["would_create_proposal"] is True
    assert data["change_type"] == "MAJOR"
    assert "consumer-team" in data["proposal_would_notify"]
    assert data["affected_consumers"][0]["consumer_team_name"] == "consumer-team"
    assert "consumer_team_id" in data["affected_consumers"][0]
    assert "contract_id" in data["affected_consumers"][0]
    assert len(data["migration_suggestions"]) > 0
    assert data["suggested_version"] == "2.0.0"


@pytest.mark.asyncio
async def test_impact_preview_breaking_without_consumers(client: AsyncClient) -> None:
    """Breaking change with no consumers returns would_create_proposal=False."""
    team_resp = await client.post("/api/v1/teams", json=make_team("solo-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.solo", team_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer", email="string")
    await _publish_contract(client, asset_id, team_id, "1.0.0", schema)

    proposed = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={"proposed_schema": proposed},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_breaking"] is True
    assert data["would_create_proposal"] is False


@pytest.mark.asyncio
async def test_impact_preview_no_contract_returns_404(client: AsyncClient) -> None:
    """Asset with no published contracts returns 404."""
    team_resp = await client.post("/api/v1/teams", json=make_team("no-contract-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.nocontract", team_id),
    )
    asset_id = asset_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={"proposed_schema": {"type": "object"}},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_impact_preview_asset_not_found(client: AsyncClient) -> None:
    """Non-existent asset returns 404."""
    resp = await client.post(
        f"/api/v1/assets/{uuid.uuid4()}/impact-preview",
        json={"proposed_schema": {"type": "object"}},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_impact_preview_invalid_schema_returns_400(client: AsyncClient) -> None:
    """Invalid proposed_schema returns 400."""
    team_resp = await client.post("/api/v1/teams", json=make_team("invalid-schema-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.invalid", team_id),
    )
    asset_id = asset_resp.json()["id"]

    await _publish_contract(client, asset_id, team_id, "1.0.0", make_schema(id="integer"))

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={"proposed_schema": {"type": "not_a_real_type"}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_impact_preview_compatibility_mode_override(client: AsyncClient) -> None:
    """Compatibility mode override changes what counts as breaking."""
    team_resp = await client.post("/api/v1/teams", json=make_team("override-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.override", team_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer", name="string")
    await _publish_contract(
        client, asset_id, team_id, "1.0.0", schema, compatibility_mode="backward"
    )

    proposed = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},
        },
        "required": ["id", "name"],
    }

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={
            "proposed_schema": proposed,
            "compatibility_mode_override": "none",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["compatibility_mode"] == "none"
    assert resp.json()["is_breaking"] is False


@pytest.mark.asyncio
async def test_impact_preview_with_guarantee_changes(client: AsyncClient) -> None:
    """Guarantee changes are included in the response."""
    team_resp = await client.post("/api/v1/teams", json=make_team("guarantee-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.preview.guarantees", team_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer")
    await _publish_contract(
        client,
        asset_id,
        team_id,
        "1.0.0",
        schema,
        guarantees={"freshness": {"max_delay_hours": 24}},
    )

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/impact-preview",
        json={
            "proposed_schema": schema,
            "proposed_guarantees": {"freshness": {"max_delay_hours": 48}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["guarantee_changes"], list)


@pytest.mark.asyncio
async def test_impact_preview_lineage(client: AsyncClient) -> None:
    """Downstream assets appear in affected_downstream."""
    team_resp = await client.post("/api/v1/teams", json=make_team("lineage-team"))
    team_id = team_resp.json()["id"]

    # Create upstream asset
    upstream_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.lineage.upstream", team_id),
    )
    upstream_id = upstream_resp.json()["id"]

    schema = make_schema(id="integer", data="string")
    await _publish_contract(client, upstream_id, team_id, "1.0.0", schema)

    # Create downstream asset owned by a different team
    downstream_team_resp = await client.post("/api/v1/teams", json=make_team("downstream-team"))
    downstream_team_id = downstream_team_resp.json()["id"]

    downstream_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.lineage.downstream", downstream_team_id),
    )
    downstream_id = downstream_resp.json()["id"]

    # Create dependency (downstream depends on upstream)
    dep_resp = await client.post(
        f"/api/v1/assets/{downstream_id}/dependencies",
        json={
            "depends_on_asset_id": upstream_id,
            "dependency_type": "consumes",
        },
    )
    assert dep_resp.status_code == 201, f"Dependency creation failed: {dep_resp.json()}"

    # Preview a breaking change on upstream
    proposed = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }
    resp = await client.post(
        f"/api/v1/assets/{upstream_id}/impact-preview",
        json={"proposed_schema": proposed},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Downstream asset should be in affected_downstream
    fqns = [a["asset_fqn"] for a in data["affected_downstream"]]
    assert "prod.lineage.downstream" in fqns
    downstream_entry = next(
        a for a in data["affected_downstream"] if a["asset_fqn"] == "prod.lineage.downstream"
    )
    assert "dependency_type" in downstream_entry
    assert "depth" in downstream_entry
    assert downstream_entry["owner_team_name"] == "downstream-team"
