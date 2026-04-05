"""Tests for audit trail query API."""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AuditEventDB
from tessera.services.audit import log_contract_published


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


class TestAuditFiltering:
    """Tests for complex filtering on audit API."""

    async def test_filter_by_entity_type(self, session: AsyncSession, client: AsyncClient):
        """Filter by entity type."""
        e1 = AuditEventDB(
            entity_type="target_type",
            entity_id=uuid4(),
            action="created",
            payload={},
        )
        e2 = AuditEventDB(
            entity_type="other_type",
            entity_id=uuid4(),
            action="created",
            payload={},
        )
        session.add_all([e1, e2])
        await session.flush()

        # Match
        resp = await client.get("/api/v1/audit/events?entity_type=target_type")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["entity_type"] == "target_type"

    async def test_filter_by_action(self, session: AsyncSession, client: AsyncClient):
        """Filter by action."""
        e1 = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="target_action",
            payload={},
        )
        e2 = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="other_action",
            payload={},
        )
        session.add_all([e1, e2])
        await session.flush()

        # Match
        resp = await client.get("/api/v1/audit/events?action=target_action")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["action"] == "target_action"

    async def test_combined_filters(self, session: AsyncSession, client: AsyncClient):
        """Filter by entity type AND action."""
        e1 = AuditEventDB(
            entity_type="type1",
            entity_id=uuid4(),
            action="action1",
            payload={},
        )
        e2 = AuditEventDB(
            entity_type="type1",
            entity_id=uuid4(),
            action="action2",
            payload={},
        )
        e3 = AuditEventDB(
            entity_type="type2",
            entity_id=uuid4(),
            action="action1",
            payload={},
        )
        session.add_all([e1, e2, e3])
        await session.flush()

        resp = await client.get("/api/v1/audit/events?entity_type=type1&action=action1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        result = resp.json()["results"][0]
        assert result["entity_type"] == "type1"
        assert result["action"] == "action1"

    async def test_filter_returns_empty_for_no_matches(
        self, session: AsyncSession, client: AsyncClient
    ):
        """Filter returns empty list if no matches."""
        e1 = AuditEventDB(
            entity_type="asset",
            entity_id=uuid4(),
            action="created",
            payload={},
        )
        session.add(e1)
        await session.flush()

        resp = await client.get("/api/v1/audit/events?entity_type=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["results"] == []


class TestLogContractPublished:
    """Tests for the log_contract_published audit helper."""

    async def test_previous_version_included_in_payload(self, session: AsyncSession) -> None:
        """When previous_version is provided, it appears in the audit payload."""
        contract_id = uuid4()
        publisher_id = uuid4()
        event = await log_contract_published(
            session=session,
            contract_id=contract_id,
            publisher_id=publisher_id,
            version="2.0.0",
            previous_version="not-a-version",
        )
        assert event.payload["previous_version"] == "not-a-version"
        assert event.payload["version"] == "2.0.0"

    async def test_previous_version_omitted_when_none(self, session: AsyncSession) -> None:
        """When previous_version is None, it is not present in the payload."""
        event = await log_contract_published(
            session=session,
            contract_id=uuid4(),
            publisher_id=uuid4(),
            version="1.0.0",
        )
        assert "previous_version" not in event.payload
