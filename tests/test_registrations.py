"""Tests for /api/v1/registrations endpoints."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AuditEventDB, RegistrationDB

pytestmark = pytest.mark.asyncio


class TestRegistrationsAPI:
    """Tests for consumer registration."""

    async def test_register_as_consumer(self, client: AsyncClient):
        """Register a team as consumer of a contract."""
        # Create producer and consumer teams
        producer_resp = await client.post("/api/v1/teams", json={"name": "reg-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "reg-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        # Create asset and contract
        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "reg.test.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register as consumer
        resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["consumer_team_id"] == consumer_id
        assert data["status"] == "active"

    async def test_impact_shows_consumers(self, client: AsyncClient):
        """Impact analysis should show registered consumers."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "show-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "show-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "show.consumers.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
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

        # Impact analysis should show the consumer
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/impact",
            json={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        data = resp.json()
        assert len(data["impacted_consumers"]) == 1
        assert data["impacted_consumers"][0]["team_name"] == "show-consumer"


class TestRegistrationsEndpoint:
    """Tests for /api/v1/registrations endpoints."""

    async def test_create_registration(self, client: AsyncClient):
        """Create a consumer registration."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "create-reg-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "create-reg-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "create.registration.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["consumer_team_id"] == consumer_id
        assert data["status"] == "active"

    async def test_create_registration_invalid_contract(self, client: AsyncClient):
        """Creating registration for nonexistent contract should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "invalid-reg-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/registrations?contract_id=00000000-0000-0000-0000-000000000000",
            json={"consumer_team_id": team_id},
        )
        assert resp.status_code == 404

    async def test_get_registration(self, client: AsyncClient):
        """Get a registration by ID."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "get-reg-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "get-reg-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "get.registration.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        reg_id = reg_resp.json()["id"]

        # Get the registration
        resp = await client.get(f"/api/v1/registrations/{reg_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == reg_id

    async def test_get_registration_not_found(self, client: AsyncClient):
        """Getting nonexistent registration should 404."""
        resp = await client.get("/api/v1/registrations/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_update_registration(self, client: AsyncClient):
        """Update a registration."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "update-reg-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "update-reg-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "update.registration.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        reg_id = reg_resp.json()["id"]

        # Update the registration
        resp = await client.patch(
            f"/api/v1/registrations/{reg_id}",
            json={"status": "migrating", "pinned_version": "1.0.0"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "migrating"
        assert data["pinned_version"] == "1.0.0"

    async def test_delete_registration(self, client: AsyncClient):
        """Delete a registration."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "delete-reg-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "delete-reg-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "delete.registration.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        reg_id = reg_resp.json()["id"]

        # Delete the registration
        resp = await client.delete(f"/api/v1/registrations/{reg_id}")
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(f"/api/v1/registrations/{reg_id}")
        assert resp.status_code == 404

    async def test_delete_registration_audit_and_softdelete_same_flush(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Verify audit event and soft-delete are flushed together.

        Both the deleted_at mutation and the audit event must be persisted
        in the same flush. If either fails, neither should be committed.
        """
        producer_resp = await client.post("/api/v1/teams", json={"name": "del-audit-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "del-audit-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "del.audit.consistency", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        reg_id = UUID(reg_resp.json()["id"])

        # Delete the registration
        resp = await client.delete(f"/api/v1/registrations/{reg_id}")
        assert resp.status_code == 204

        # Both soft-delete and audit event must exist in the DB
        reg_result = await test_session.execute(
            select(RegistrationDB).where(RegistrationDB.id == reg_id)
        )
        registration = reg_result.scalar_one()
        assert registration.deleted_at is not None, "soft-delete was not persisted"

        audit_result = await test_session.execute(
            select(AuditEventDB)
            .where(AuditEventDB.entity_id == reg_id)
            .where(AuditEventDB.action == "registration.deleted")
        )
        audit_event = audit_result.scalar_one_or_none()
        assert audit_event is not None, "audit event was not persisted"
        assert audit_event.entity_type == "registration"
        assert audit_event.payload["contract_id"] == contract_id

    async def test_delete_registration_audit_occurred_after_deleted_at(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Verify audit occurred_at is >= deleted_at.

        The mutation (deleted_at) must happen before the audit event is
        recorded, so the audit timestamp must be equal to or after the
        soft-delete timestamp.
        """
        producer_resp = await client.post("/api/v1/teams", json={"name": "del-order-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "del-order-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "del.order.check", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        reg_id = UUID(reg_resp.json()["id"])

        # Delete the registration
        resp = await client.delete(f"/api/v1/registrations/{reg_id}")
        assert resp.status_code == 204

        # Fetch both timestamps
        reg_result = await test_session.execute(
            select(RegistrationDB).where(RegistrationDB.id == reg_id)
        )
        registration = reg_result.scalar_one()

        audit_result = await test_session.execute(
            select(AuditEventDB)
            .where(AuditEventDB.entity_id == reg_id)
            .where(AuditEventDB.action == "registration.deleted")
        )
        audit_event = audit_result.scalar_one()

        # Normalize both to naive UTC — SQLite strips tzinfo on round-trip,
        # so one may be aware (identity-map hit) while the other is naive.
        occurred = audit_event.occurred_at.replace(tzinfo=None)
        deleted = registration.deleted_at.replace(tzinfo=None)
        assert occurred >= deleted, (
            f"audit occurred_at ({audit_event.occurred_at}) must be >= "
            f"deleted_at ({registration.deleted_at})"
        )
