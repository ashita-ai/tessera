"""Tests for agent identity on API keys and audit trail (issue #358)."""

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AuditEventDB, Base
from tessera.main import app

pytestmark = pytest.mark.asyncio

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


# --- Fixtures for tests needing both session and client ---


@pytest.fixture
async def _audit_engine():
    connect_args = {"check_same_thread": False} if _USE_SQLITE else {}
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, connect_args=connect_args)
    yield engine
    await engine.dispose()


@pytest.fixture
async def audit_session(_audit_engine) -> AsyncGenerator[AsyncSession, None]:
    async with _audit_engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(_audit_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    async with _audit_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def audit_client(audit_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from tessera.config import settings
    from tessera.db import database

    original = settings.auth_disabled
    settings.auth_disabled = True

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield audit_session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    settings.auth_disabled = original


# --- Helpers ---


async def _create_team(client: AsyncClient, name: str = "agent-test-team") -> str:
    """Helper: create a team and return its ID."""
    resp = await client.post("/api/v1/teams", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


# --- API Key agent field tests (use conftest client) ---


class TestAgentKeyCreate:
    """Tests for creating agent vs human API keys."""

    async def test_create_agent_key(self, client: AsyncClient):
        """Create an API key with agent fields."""
        team_id = await _create_team(client, "agent-key-team")
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "dbt-codegen",
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

    async def test_create_human_key_no_agent_fields(self, client: AsyncClient):
        """Create a normal (human) key without agent fields."""
        team_id = await _create_team(client, "human-key-team")
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "human-key",
                "team_id": team_id,
                "scopes": ["read"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] is None
        assert data["agent_framework"] is None

    async def test_create_agent_key_name_only(self, client: AsyncClient):
        """Agent name without framework is valid."""
        team_id = await _create_team(client, "agent-name-only-team")
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "agent-only-name",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "my-bot",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] == "my-bot"
        assert data["agent_framework"] is None

    async def test_create_agent_key_whitespace_stripped(self, client: AsyncClient):
        """Agent name with whitespace is stripped."""
        team_id = await _create_team(client, "strip-ws-team")
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "ws-key",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "  my-agent  ",
                "agent_framework": "  cursor  ",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] == "my-agent"
        assert data["agent_framework"] == "cursor"

    async def test_create_agent_key_empty_string_becomes_null(self, client: AsyncClient):
        """Empty agent_name string is treated as null (human key)."""
        team_id = await _create_team(client, "empty-agent-team")
        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "empty-agent-key",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "   ",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] is None


class TestAgentKeyList:
    """Tests for listing API keys with is_agent filter."""

    async def test_filter_agent_keys(self, client: AsyncClient):
        """Filter list to only agent keys."""
        team_id = await _create_team(client, "filter-agent-team")

        await client.post(
            "/api/v1/api-keys",
            json={
                "name": "agent-k",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "bot-1",
            },
        )
        await client.post(
            "/api/v1/api-keys",
            json={"name": "human-k", "team_id": team_id, "scopes": ["read"]},
        )

        resp = await client.get(f"/api/v1/api-keys?team_id={team_id}&is_agent=true")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["agent_name"] == "bot-1"

    async def test_filter_human_keys(self, client: AsyncClient):
        """Filter list to only human keys."""
        team_id = await _create_team(client, "filter-human-team")

        await client.post(
            "/api/v1/api-keys",
            json={
                "name": "agent-k2",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "bot-2",
            },
        )
        await client.post(
            "/api/v1/api-keys",
            json={"name": "human-k2", "team_id": team_id, "scopes": ["read"]},
        )

        resp = await client.get(f"/api/v1/api-keys?team_id={team_id}&is_agent=false")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["agent_name"] is None

    async def test_no_filter_returns_all(self, client: AsyncClient):
        """Without is_agent filter, both types returned."""
        team_id = await _create_team(client, "no-filter-team")

        await client.post(
            "/api/v1/api-keys",
            json={
                "name": "agent-k3",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "bot-3",
            },
        )
        await client.post(
            "/api/v1/api-keys",
            json={"name": "human-k3", "team_id": team_id, "scopes": ["read"]},
        )

        resp = await client.get(f"/api/v1/api-keys?team_id={team_id}")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 2


class TestAgentKeyGetDetail:
    """Tests for GET /api/v1/api-keys/{id} with agent fields."""

    async def test_get_agent_key_includes_agent_fields(self, client: AsyncClient):
        """GET single key includes agent_name and agent_framework."""
        team_id = await _create_team(client, "get-agent-detail-team")

        create_resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "detail-bot",
                "team_id": team_id,
                "scopes": ["read"],
                "agent_name": "detail-agent",
                "agent_framework": "cursor",
            },
        )
        key_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/api-keys/{key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "detail-agent"
        assert data["agent_framework"] == "cursor"

    async def test_get_human_key_has_null_agent_fields(self, client: AsyncClient):
        """GET human key has null agent fields."""
        team_id = await _create_team(client, "get-human-detail-team")

        create_resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "human-detail",
                "team_id": team_id,
                "scopes": ["read"],
            },
        )
        key_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/api-keys/{key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] is None
        assert data["agent_framework"] is None


# --- Audit actor_type tests (use local session+client fixtures) ---


class TestAuditActorType:
    """Tests for actor_type in audit events."""

    async def test_audit_event_includes_actor_type(
        self, audit_session: AsyncSession, audit_client: AsyncClient
    ):
        """Audit events include actor_type in response."""
        event = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            actor_id=uuid4(),
            actor_type="human",
            payload={"fqn": "test.asset"},
        )
        audit_session.add(event)
        await audit_session.flush()

        resp = await audit_client.get("/api/v1/audit/events")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["actor_type"] == "human"

    async def test_audit_event_agent_actor_type(
        self, audit_session: AsyncSession, audit_client: AsyncClient
    ):
        """Audit events can have actor_type='agent'."""
        event = AuditEventDB(
            entity_type="contract",
            entity_id=uuid4(),
            action="published",
            actor_id=uuid4(),
            actor_type="agent",
            payload={"version": "1.0.0"},
        )
        audit_session.add(event)
        await audit_session.flush()

        resp = await audit_client.get("/api/v1/audit/events")
        assert resp.status_code == 200
        results = resp.json()["results"]
        agent_events = [r for r in results if r["actor_type"] == "agent"]
        assert len(agent_events) == 1

    async def test_audit_event_default_actor_type_is_human(
        self, audit_session: AsyncSession, audit_client: AsyncClient
    ):
        """Default actor_type is 'human' when not specified."""
        event = AuditEventDB(
            entity_type="team",
            entity_id=uuid4(),
            action="created",
            payload={},
        )
        audit_session.add(event)
        await audit_session.flush()

        resp = await audit_client.get("/api/v1/audit/events")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results[0]["actor_type"] == "human"

    async def test_filter_audit_by_actor_type(
        self, audit_session: AsyncSession, audit_client: AsyncClient
    ):
        """Filter audit events by actor_type."""
        human_event = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            actor_type="human",
            payload={},
        )
        agent_event = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            actor_type="agent",
            payload={},
        )
        audit_session.add_all([human_event, agent_event])
        await audit_session.flush()

        # Filter for agent events only
        resp = await audit_client.get("/api/v1/audit/events?actor_type=agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["actor_type"] == "agent"

        # Filter for human events only
        resp = await audit_client.get("/api/v1/audit/events?actor_type=human")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["actor_type"] == "human"

    async def test_get_single_audit_event_has_actor_type(
        self, audit_session: AsyncSession, audit_client: AsyncClient
    ):
        """GET /audit/events/{id} includes actor_type."""
        event = AuditEventDB(
            entity_type="contract",
            entity_id=uuid4(),
            action="published",
            actor_type="agent",
            payload={},
        )
        audit_session.add(event)
        await audit_session.flush()

        resp = await audit_client.get(f"/api/v1/audit/events/{event.id}")
        assert resp.status_code == 200
        assert resp.json()["actor_type"] == "agent"


class TestAgentKeyAuditIntegration:
    """Integration: creating an agent key generates audit with correct actor_type."""

    async def test_agent_key_creation_audit_trail(self, client: AsyncClient):
        """Creating an agent key produces audit event with agent metadata in payload."""
        team_id = await _create_team(client, "audit-integration-team")

        resp = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "audit-bot",
                "team_id": team_id,
                "scopes": ["read", "write"],
                "agent_name": "audit-bot-agent",
                "agent_framework": "langchain",
            },
        )
        assert resp.status_code == 201

        audit_resp = await client.get(
            "/api/v1/audit/events",
            params={"entity_type": "api_key", "action": "api_key.created"},
        )
        assert audit_resp.status_code == 200
        results = audit_resp.json()["results"]
        assert len(results) >= 1

        matching = [r for r in results if r["payload"].get("agent_name") == "audit-bot-agent"]
        assert len(matching) == 1
        event = matching[0]
        assert event["payload"]["agent_framework"] == "langchain"
        assert "actor_type" in event
