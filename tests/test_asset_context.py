"""Tests for the asset context endpoint."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import make_asset, make_contract, make_schema, make_team


@pytest.mark.asyncio
async def test_asset_context_full_data(client: AsyncClient) -> None:
    """Test context endpoint returns all sections when data exists."""
    # Create team
    team_resp = await client.post("/api/v1/teams", json=make_team("context-team"))
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    # Create asset
    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.dim_customers", team_id),
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    # Publish a contract with field_descriptions via the dedicated column
    schema = make_schema(id="integer", name="string", email="string")
    contract_payload = make_contract("1.0.0", schema)
    contract_payload["field_descriptions"] = {
        "$.properties.email": "Customer email address",
    }
    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=contract_payload,
    )
    assert contract_resp.status_code == 201

    # Create a consumer team and register
    consumer_resp = await client.post("/api/v1/teams", json=make_team("consumer-team"))
    assert consumer_resp.status_code == 201
    consumer_team_id = consumer_resp.json()["id"]

    contract_id = contract_resp.json()["contract"]["id"]
    reg_resp = await client.post(
        f"/api/v1/registrations?contract_id={contract_id}",
        json={
            "consumer_team_id": consumer_team_id,
        },
    )
    assert reg_resp.status_code == 201

    # Create upstream asset and dependency
    upstream_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.raw.customers_raw", team_id),
    )
    assert upstream_resp.status_code == 201
    upstream_id = upstream_resp.json()["id"]

    dep_resp = await client.post(
        f"/api/v1/assets/{asset_id}/dependencies",
        json={
            "dependency_asset_id": upstream_id,
            "dependency_type": "consumes",
        },
    )
    assert dep_resp.status_code == 201

    # Create downstream asset and dependency
    downstream_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.fct_orders", team_id),
    )
    assert downstream_resp.status_code == 201
    downstream_id = downstream_resp.json()["id"]

    dep_resp2 = await client.post(
        f"/api/v1/assets/{downstream_id}/dependencies",
        json={
            "dependency_asset_id": asset_id,
            "dependency_type": "consumes",
        },
    )
    assert dep_resp2.status_code == 201

    # Submit an audit run
    audit_resp = await client.post(
        f"/api/v1/assets/{asset_id}/audit-results",
        json={
            "status": "passed",
            "guarantees_checked": 3,
            "guarantees_passed": 3,
            "guarantees_failed": 0,
            "triggered_by": "dbt_test",
        },
    )
    assert audit_resp.status_code == 200

    # Now fetch context
    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    # Verify asset section
    assert data["asset"]["id"] == asset_id
    assert data["asset"]["fqn"] == "prod.analytics.dim_customers"
    assert data["asset"]["owner_team_id"] == team_id
    assert data["asset"]["owner_team_name"] == "context-team"
    assert data["asset"]["resource_type"] is not None

    # Verify current contract section
    assert data["current_contract"] is not None
    assert data["current_contract"]["version"] == "1.0.0"
    assert "properties" in data["current_contract"]["schema"]
    assert (
        data["current_contract"]["field_descriptions"]["$.properties.email"]
        == "Customer email address"
    )

    # Verify consumers
    assert len(data["consumers"]) == 1
    assert data["consumers"][0]["consumer_team_name"] == "consumer-team"

    # Verify upstream dependencies
    assert len(data["upstream_dependencies"]) == 1
    assert data["upstream_dependencies"][0]["fqn"] == "prod.raw.customers_raw"

    # Verify downstream dependents
    assert len(data["downstream_dependents"]) == 1
    assert data["downstream_dependents"][0]["fqn"] == "prod.analytics.fct_orders"

    # Verify recent audits
    assert len(data["recent_audits"]) == 1
    assert data["recent_audits"][0]["status"] == "passed"
    assert data["recent_audits"][0]["guarantees_passed"] == 3

    # Verify contract history count
    assert data["contract_history_count"] == 1


@pytest.mark.asyncio
async def test_asset_context_no_contract(client: AsyncClient) -> None:
    """Test context endpoint when asset has no contracts."""
    team_resp = await client.post("/api/v1/teams", json=make_team("no-contract-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.raw.no_contract_asset", team_id),
    )
    asset_id = asset_resp.json()["id"]

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["current_contract"] is None
    assert data["consumers"] == []
    assert data["contract_history_count"] == 0


@pytest.mark.asyncio
async def test_asset_context_no_consumers(client: AsyncClient) -> None:
    """Test context endpoint when asset has a contract but no consumers."""
    team_resp = await client.post("/api/v1/teams", json=make_team("no-consumers-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.no_consumers", team_id),
    )
    asset_id = asset_resp.json()["id"]

    schema = make_schema(id="integer")
    await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("1.0.0", schema),
    )

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["current_contract"] is not None
    assert data["consumers"] == []


@pytest.mark.asyncio
async def test_asset_context_no_lineage(client: AsyncClient) -> None:
    """Test context endpoint when asset has no dependencies."""
    team_resp = await client.post("/api/v1/teams", json=make_team("no-lineage-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.no_lineage", team_id),
    )
    asset_id = asset_resp.json()["id"]

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["upstream_dependencies"] == []
    assert data["downstream_dependents"] == []


@pytest.mark.asyncio
async def test_asset_context_active_proposal(client: AsyncClient) -> None:
    """Test context endpoint includes active proposals."""
    team_resp = await client.post("/api/v1/teams", json=make_team("proposal-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.with_proposal", team_id),
    )
    asset_id = asset_resp.json()["id"]

    # Publish initial contract
    schema_v1 = make_schema(id="integer", name="string")
    await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("1.0.0", schema_v1),
    )

    # Create a consumer so breaking change triggers a proposal
    consumer_resp = await client.post("/api/v1/teams", json=make_team("proposal-consumer"))
    consumer_team_id = consumer_resp.json()["id"]

    # Get the contract ID
    contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
    contract_id = contracts_resp.json()["results"][0]["id"]

    await client.post(
        f"/api/v1/registrations?contract_id={contract_id}",
        json={
            "consumer_team_id": consumer_team_id,
        },
    )

    # Publish breaking change (remove required field) — should create proposal
    schema_v2 = make_schema(id="integer")  # removed "name"
    await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("2.0.0", schema_v2),
    )

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert len(data["active_proposals"]) >= 1
    proposal = data["active_proposals"][0]
    assert proposal["status"] == "pending"
    assert proposal["breaking_changes_count"] > 0


@pytest.mark.asyncio
async def test_asset_context_fqn_lookup(client: AsyncClient) -> None:
    """Test context endpoint via FQN query parameter."""
    team_resp = await client.post("/api/v1/teams", json=make_team("fqn-lookup-team"))
    team_id = team_resp.json()["id"]

    fqn = "prod.analytics.fqn_lookup_asset"
    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset(fqn, team_id),
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    ctx_resp = await client.get("/api/v1/assets/context", params={"fqn": fqn})
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["asset"]["id"] == asset_id
    assert data["asset"]["fqn"] == fqn


@pytest.mark.asyncio
async def test_asset_context_deleted_asset(client: AsyncClient) -> None:
    """Test context endpoint returns 404 for deleted asset."""
    team_resp = await client.post("/api/v1/teams", json=make_team("deleted-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.to_delete", team_id),
    )
    asset_id = asset_resp.json()["id"]

    # Delete the asset
    del_resp = await client.delete(f"/api/v1/assets/{asset_id}")
    assert del_resp.status_code == 204

    # Context should 404
    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 404


@pytest.mark.asyncio
async def test_asset_context_missing_asset(client: AsyncClient) -> None:
    """Test context endpoint returns 404 for non-existent asset."""
    fake_id = str(uuid4())
    ctx_resp = await client.get(f"/api/v1/assets/{fake_id}/context")
    assert ctx_resp.status_code == 404


@pytest.mark.asyncio
async def test_asset_context_fqn_not_found(client: AsyncClient) -> None:
    """Test context endpoint returns 404 for non-existent FQN."""
    ctx_resp = await client.get("/api/v1/assets/context", params={"fqn": "nonexistent.fqn.asset"})
    assert ctx_resp.status_code == 404


@pytest.mark.asyncio
async def test_asset_context_multiple_contracts(client: AsyncClient) -> None:
    """Test context endpoint returns the active contract and correct history count."""
    team_resp = await client.post("/api/v1/teams", json=make_team("multi-contract-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.multi_contract", team_id),
    )
    asset_id = asset_resp.json()["id"]

    # Publish two compatible versions (adding an optional field is backward-compatible)
    schema_v1 = make_schema(id="integer")
    resp1 = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("1.0.0", schema_v1),
    )
    assert resp1.status_code == 201

    # Add an optional property (not in "required") — backward-compatible
    schema_v2 = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
        },
        "required": ["id"],
    }
    resp2 = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("1.1.0", schema_v2),
    )
    assert resp2.status_code == 201

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    # Should return the latest active contract (old one was deprecated)
    assert data["current_contract"] is not None
    assert data["current_contract"]["version"] == "1.1.0"
    # History count includes all versions
    assert data["contract_history_count"] == 2


@pytest.mark.asyncio
async def test_asset_context_returns_asset_tags(client: AsyncClient) -> None:
    """Test context endpoint returns tags from the dedicated AssetDB.tags column."""
    team_resp = await client.post("/api/v1/teams", json=make_team("tags-team"))
    team_id = team_resp.json()["id"]

    asset_payload = make_asset("prod.analytics.tagged_asset", team_id)
    asset_payload["tags"] = ["pii", "financial", "sla:p1"]
    asset_resp = await client.post("/api/v1/assets", json=asset_payload)
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["asset"]["tags"] == ["pii", "financial", "sla:p1"]


@pytest.mark.asyncio
async def test_asset_context_returns_field_metadata_from_columns(
    client: AsyncClient,
) -> None:
    """Test context endpoint returns field_descriptions and field_tags from
    the dedicated ContractDB columns, not from schema property annotations."""
    team_resp = await client.post("/api/v1/teams", json=make_team("field-meta-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.field_meta_asset", team_id),
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    # Schema has NO description annotations on properties — metadata comes
    # exclusively from the field_descriptions/field_tags payload fields.
    schema = make_schema(id="integer", name="string", email="string")
    contract_payload = make_contract("1.0.0", schema)
    contract_payload["field_descriptions"] = {
        "$.properties.id": "Primary key",
        "$.properties.email": "Customer email address",
    }
    contract_payload["field_tags"] = {
        "$.properties.email": ["pii", "contact"],
        "$.properties.name": ["display"],
    }

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=contract_payload,
    )
    assert resp.status_code == 201

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    contract = data["current_contract"]
    assert contract["field_descriptions"] == {
        "$.properties.id": "Primary key",
        "$.properties.email": "Customer email address",
    }
    assert contract["field_tags"] == {
        "$.properties.email": ["pii", "contact"],
        "$.properties.name": ["display"],
    }


@pytest.mark.asyncio
async def test_asset_context_field_metadata_empty_when_not_provided(
    client: AsyncClient,
) -> None:
    """Test context endpoint returns empty dicts for field metadata
    when contract was published without field_descriptions/field_tags."""
    team_resp = await client.post("/api/v1/teams", json=make_team("no-field-meta-team"))
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json=make_asset("prod.analytics.no_field_meta", team_id),
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    # Publish contract WITHOUT field_descriptions/field_tags, but WITH
    # a description annotation on a schema property to prove we don't
    # accidentally extract from the schema.
    schema = make_schema(id="integer", name="string")
    schema["properties"]["name"]["description"] = "Should not appear"

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json=make_contract("1.0.0", schema),
    )
    assert resp.status_code == 201

    ctx_resp = await client.get(f"/api/v1/assets/{asset_id}/context")
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()

    assert data["current_contract"]["field_descriptions"] == {}
    assert data["current_contract"]["field_tags"] == {}
