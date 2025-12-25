"""Tests for audit trail query API."""

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AuditEventDB, Base
from tessera.main import app

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


@pytest.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from tessera.config import settings
    from tessera.db import database

    original_auth_disabled = settings.auth_disabled
    settings.auth_disabled = True  # Disable auth for simpler setup

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[database.get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    settings.auth_disabled = original_auth_disabled


class TestAuditAPI:
    """Tests for GET /api/v1/audit/events."""

    async def test_list_audit_events_basic(self, session: AsyncSession, client: AsyncClient):
        # Create some audit events
        event1 = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            actor_id=uuid4(),
            payload={"fqn": "test.asset"},
        )
        session.add(event1)
        await session.flush()

        response = await client.get("/api/v1/audit/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["entity_type"] == "asset"

    async def test_list_audit_events_filters(self, session: AsyncSession, client: AsyncClient):
        entity_id = uuid4()
        event1 = AuditEventDB(
            entity_type="asset",
            entity_id=entity_id,
            action="created",
            actor_id=uuid4(),
            payload={"fqn": "test.asset"},
        )
        event2 = AuditEventDB(
            entity_type="contract",
            entity_id=uuid4(),
            action="published",
            actor_id=uuid4(),
            payload={"version": "1.0.0"},
        )
        session.add_all([event1, event2])
        await session.flush()

        # Filter by entity_type
        response = await client.get("/api/v1/audit/events", params={"entity_type": "asset"})
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1

        # Filter by entity_id
        response = await client.get("/api/v1/audit/events", params={"entity_id": str(entity_id)})
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1

        # Filter by action
        response = await client.get("/api/v1/audit/events", params={"action": "created"})
        assert response.status_code == 200
        assert len(response.json()["results"]) >= 1

    async def test_get_audit_event_by_id(self, session: AsyncSession, client: AsyncClient):
        """Get specific audit event by ID."""
        event = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="deleted",
            actor_id=uuid4(),
            payload={"reason": "cleanup"},
        )
        session.add(event)
        await session.flush()

        response = await client.get(f"/api/v1/audit/events/{event.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "asset"
        assert data["action"] == "deleted"

    async def test_get_audit_event_not_found(self, client: AsyncClient):
        """Get nonexistent audit event returns 404."""
        response = await client.get("/api/v1/audit/events/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    async def test_get_entity_history(self, session: AsyncSession, client: AsyncClient):
        """Get audit history for a specific entity."""
        entity_id = uuid4()

        # Create multiple events for same entity
        events = [
            AuditEventDB(
                entity_type="contract",
                entity_id=entity_id,
                action="created",
                payload={"version": "1.0.0"},
            ),
            AuditEventDB(
                entity_type="contract",
                entity_id=entity_id,
                action="updated",
                payload={"version": "1.1.0"},
            ),
        ]
        session.add_all(events)
        await session.flush()

        response = await client.get(f"/api/v1/audit/entities/contract/{entity_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    async def test_audit_events_pagination(self, session: AsyncSession, client: AsyncClient):
        """Test pagination parameters."""
        # Create multiple events
        for i in range(5):
            event = AuditEventDB(
                entity_type="team",
                entity_id=uuid4(),
                action="created",
                payload={"index": i},
            )
            session.add(event)
        await session.flush()

        # Test limit
        response = await client.get("/api/v1/audit/events", params={"limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2
        assert data["limit"] == 2

        # Test offset
        response = await client.get("/api/v1/audit/events", params={"limit": 2, "offset": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 2

    async def test_audit_events_date_filters(self, session: AsyncSession, client: AsyncClient):
        """Test date range filters."""
        from datetime import UTC, datetime, timedelta

        event = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            payload={},
        )
        session.add(event)
        await session.flush()

        # Filter from today
        today = datetime.now(UTC)
        yesterday = today - timedelta(days=1)

        response = await client.get(
            "/api/v1/audit/events",
            params={"from": yesterday.isoformat()},
        )
        assert response.status_code == 200

    async def test_audit_events_actor_filter(self, session: AsyncSession, client: AsyncClient):
        """Filter events by actor ID."""
        actor_id = uuid4()

        event = AuditEventDB(
            entity_type="proposal",
            entity_id=uuid4(),
            action="acknowledged",
            actor_id=actor_id,
            payload={},
        )
        session.add(event)
        await session.flush()

        response = await client.get(
            "/api/v1/audit/events",
            params={"actor_id": str(actor_id)},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
