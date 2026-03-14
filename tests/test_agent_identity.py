"""Tests for agent identity on API keys and audit trail."""

import pytest
from httpx import AsyncClient

from tests.conftest import make_team


@pytest.mark.asyncio
async def test_create_agent_key(client: AsyncClient) -> None:
    """Creating an API key with agent_name produces an agent key."""
    team_resp = await client.post("/api/v1/teams", json=make_team("agent-team"))
    team_id = team_resp.json()["id"]

    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "dbt-agent-key",
            "team_id": team_id,
            "scopes": ["read", "write"],
            "agent_name": "dbt-codegen-agent",
            "agent_framework": "claude-code",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_name"] == "dbt-codegen-agent"
    assert data["agent_framework"] == "claude-code"
    assert data["is_agent"] is True


@pytest.mark.asyncio
async def test_create_human_key(client: AsyncClient) -> None:
    """Creating an API key without agent_name produces a human key."""
    team_resp = await client.post("/api/v1/teams", json=make_team("human-team"))
    team_id = team_resp.json()["id"]

    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "human-key",
            "team_id": team_id,
            "scopes": ["read", "write"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_name"] is None
    assert data["agent_framework"] is None
    assert data["is_agent"] is False


@pytest.mark.asyncio
async def test_list_keys_filter_by_is_agent(client: AsyncClient) -> None:
    """Listing keys with is_agent filter returns correct subset."""
    team_resp = await client.post("/api/v1/teams", json=make_team("filter-team"))
    team_id = team_resp.json()["id"]

    # Create one agent key and one human key
    await client.post(
        "/api/v1/api-keys",
        json={
            "name": "agent-key",
            "team_id": team_id,
            "scopes": ["read"],
            "agent_name": "my-agent",
        },
    )
    await client.post(
        "/api/v1/api-keys",
        json={
            "name": "human-key",
            "team_id": team_id,
            "scopes": ["read"],
        },
    )

    # Filter: agent only
    resp = await client.get("/api/v1/api-keys", params={"is_agent": "true"})
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert all(k["is_agent"] for k in keys)
    assert any(k["agent_name"] == "my-agent" for k in keys)

    # Filter: human only
    resp = await client.get("/api/v1/api-keys", params={"is_agent": "false"})
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert all(not k["is_agent"] for k in keys)


@pytest.mark.asyncio
async def test_audit_event_includes_actor_type(client: AsyncClient) -> None:
    """Audit events include actor_type field."""
    # Create a team to trigger an audit event
    team_resp = await client.post("/api/v1/teams", json=make_team("audit-actor-team"))
    assert team_resp.status_code == 201

    # List audit events
    resp = await client.get("/api/v1/audit/events")
    assert resp.status_code == 200
    events = resp.json()["results"]
    # All events created via test client (auth disabled) should have actor_type
    for event in events:
        assert "actor_type" in event
        # Default is "human" since auth is disabled in tests
        assert event["actor_type"] in ("human", "agent")


@pytest.mark.asyncio
async def test_audit_events_filter_by_actor_type(client: AsyncClient) -> None:
    """Audit events can be filtered by actor_type."""
    # Create some events
    await client.post("/api/v1/teams", json=make_team("actor-filter-team"))

    # Filter by human
    resp = await client.get("/api/v1/audit/events", params={"actor_type": "human"})
    assert resp.status_code == 200
    events = resp.json()["results"]
    for event in events:
        assert event["actor_type"] == "human"

    # Filter by agent (should be empty since tests use auth disabled = human)
    resp = await client.get("/api/v1/audit/events", params={"actor_type": "agent"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_key_includes_agent_fields(client: AsyncClient) -> None:
    """Getting a single key by ID returns agent fields."""
    team_resp = await client.post("/api/v1/teams", json=make_team("get-key-team"))
    team_id = team_resp.json()["id"]

    create_resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "cursor-agent",
            "team_id": team_id,
            "scopes": ["read", "write"],
            "agent_name": "cursor-agent",
            "agent_framework": "cursor",
        },
    )
    key_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/api-keys/{key_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_name"] == "cursor-agent"
    assert data["agent_framework"] == "cursor"
    assert data["is_agent"] is True
