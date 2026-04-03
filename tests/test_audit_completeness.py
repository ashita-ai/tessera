"""End-to-end tests verifying audit events are created for all mutations.

These tests perform operations through the API and then verify the corresponding
audit events exist in the database with correct action, actor, and payload.
"""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AuditEventDB

pytestmark = pytest.mark.asyncio


async def _get_audit_events(
    session: AsyncSession, action: str, entity_id: UUID | None = None
) -> list[AuditEventDB]:
    """Fetch audit events by action and optionally entity_id."""
    query = select(AuditEventDB).where(AuditEventDB.action == action)
    if entity_id is not None:
        query = query.where(AuditEventDB.entity_id == entity_id)
    result = await session.execute(query)
    return list(result.scalars().all())


class TestRestoreAuditEvents:
    """Verify restore/reactivate operations create audit events."""

    async def test_restore_asset_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-restore-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_restore_test", "owner_team_id": team_id},
        )
        asset_id = UUID(asset_resp.json()["id"])

        # Delete the asset
        await client.delete(f"/api/v1/assets/{asset_id}")

        # Restore the asset
        resp = await client.post(f"/api/v1/assets/{asset_id}/restore")
        assert resp.status_code == 200

        # Verify audit event
        events = await _get_audit_events(test_session, "asset.restored", asset_id)
        assert len(events) == 1
        assert events[0].entity_type == "asset"
        assert events[0].payload["fqn"] == "db.schema.audit_restore_test"

    async def test_restore_team_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create and delete team
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-team-restore"})
        team_id = UUID(team_resp.json()["id"])

        await client.delete(f"/api/v1/teams/{team_id}?force=true")

        # Restore the team
        resp = await client.post(f"/api/v1/teams/{team_id}/restore")
        assert resp.status_code == 200

        # Verify audit event
        events = await _get_audit_events(test_session, "team.restored", team_id)
        assert len(events) == 1
        assert events[0].entity_type == "team"
        assert events[0].payload["name"] == "audit-team-restore"

    async def test_reactivate_user_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create team for the user
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-user-team"})
        team_id = team_resp.json()["id"]

        # Create and deactivate user
        user_resp = await client.post(
            "/api/v1/users",
            json={
                "username": "auditreactivate",
                "name": "Audit Reactivate",
                "team_id": team_id,
            },
        )
        user_id = UUID(user_resp.json()["id"])

        await client.delete(f"/api/v1/users/{user_id}")

        # Reactivate the user
        resp = await client.post(f"/api/v1/users/{user_id}/reactivate")
        assert resp.status_code == 200

        # Verify audit event
        events = await _get_audit_events(test_session, "user.reactivated", user_id)
        assert len(events) == 1
        assert events[0].entity_type == "user"
        assert events[0].payload["username"] == "auditreactivate"
        assert events[0].payload["name"] == "Audit Reactivate"


class TestProposalAuditEvents:
    """Verify proposal mutations create audit events."""

    async def test_withdraw_proposal_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create team, asset, and initial contract
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-withdraw-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_withdraw", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
            },
        )

        # Create a consumer team and register
        consumer_resp = await client.post("/api/v1/teams", json={"name": "audit-withdraw-consumer"})
        consumer_id = consumer_resp.json()["id"]

        # Get the contract
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        contract_id = contracts_resp.json()["results"][0]["id"]

        await client.post(
            f"/api/v1/contracts/{contract_id}/register",
            json={"consumer_team_id": consumer_id},
        )

        # Publish breaking change to create a proposal
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"new_id": {"type": "string"}},
                    "required": ["new_id"],
                },
            },
        )
        assert resp.json()["action"] == "proposal_created"
        proposal_id = UUID(resp.json()["proposal"]["id"])

        # Withdraw the proposal
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/withdraw")
        assert resp.status_code == 200

        # Verify audit event
        events = await _get_audit_events(test_session, "proposal.withdrawn", proposal_id)
        assert len(events) == 1
        assert events[0].entity_type == "proposal"
        assert events[0].payload["asset_id"] == asset_id

    async def test_file_objection_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create producer and consumer teams
        producer_resp = await client.post(
            "/api/v1/teams", json={"name": "audit-objection-producer"}
        )
        producer_id = producer_resp.json()["id"]

        consumer_resp = await client.post(
            "/api/v1/teams", json={"name": "audit-objection-consumer"}
        )
        consumer_id = consumer_resp.json()["id"]

        # Create asset with dependency chain for affected parties
        upstream_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_objection_upstream", "owner_team_id": producer_id},
        )
        upstream_id = upstream_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_objection_downstream", "owner_team_id": consumer_id},
        )
        downstream_id = downstream_resp.json()["id"]

        # Create dependency: downstream depends on upstream
        await client.post(
            f"/api/v1/assets/{downstream_id}/dependencies",
            json={"depends_on_asset_id": upstream_id},
        )

        # Publish initial contract on upstream
        await client.post(
            f"/api/v1/assets/{upstream_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
            },
        )

        # Register consumer
        contracts_resp = await client.get(f"/api/v1/assets/{upstream_id}/contracts")
        contract_id = contracts_resp.json()["results"][0]["id"]

        await client.post(
            f"/api/v1/contracts/{contract_id}/register",
            json={"consumer_team_id": consumer_id},
        )

        # Publish breaking change to create a proposal
        resp = await client.post(
            f"/api/v1/assets/{upstream_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"new_field": {"type": "string"}},
                    "required": ["new_field"],
                },
            },
        )
        assert resp.json()["action"] == "proposal_created"
        proposal_id = UUID(resp.json()["proposal"]["id"])

        # File objection
        resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/object" f"?objector_team_id={consumer_id}",
            json={"reason": "We need migration time"},
        )
        assert resp.status_code == 201

        # Verify audit event
        events = await _get_audit_events(test_session, "proposal.objection_filed", proposal_id)
        assert len(events) == 1
        assert events[0].entity_type == "proposal"
        assert events[0].actor_id == UUID(consumer_id)
        assert events[0].payload["reason"] == "We need migration time"


class TestBulkAuditEvents:
    """Verify bulk operations create audit events."""

    async def test_reassign_team_assets_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create source and target teams
        source_resp = await client.post("/api/v1/teams", json={"name": "audit-reassign-source"})
        source_id = UUID(source_resp.json()["id"])

        target_resp = await client.post("/api/v1/teams", json={"name": "audit-reassign-target"})
        target_id = target_resp.json()["id"]

        # Create assets in source team
        await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_reassign_1", "owner_team_id": str(source_id)},
        )
        await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_reassign_2", "owner_team_id": str(source_id)},
        )

        # Reassign all assets
        resp = await client.post(
            f"/api/v1/teams/{source_id}/reassign-assets",
            json={"target_team_id": target_id},
        )
        assert resp.status_code == 200
        assert resp.json()["reassigned"] == 2

        # Verify audit event
        events = await _get_audit_events(test_session, "bulk.assets_reassigned", source_id)
        assert len(events) == 1
        assert events[0].entity_type == "team"
        assert events[0].payload["source_team_id"] == str(source_id)
        assert events[0].payload["target_team_id"] == target_id
        assert events[0].payload["asset_count"] == 2
        assert len(events[0].payload["asset_ids"]) == 2

    async def test_bulk_assign_owner_creates_audit_event(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        # Create team and user
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-bulk-owner-team"})
        team_id = team_resp.json()["id"]

        user_resp = await client.post(
            "/api/v1/users",
            json={"username": "auditbulk", "name": "Bulk Owner", "team_id": team_id},
        )
        user_id = user_resp.json()["id"]

        # Create assets
        a1 = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_bulk_1", "owner_team_id": team_id},
        )
        a2 = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_bulk_2", "owner_team_id": team_id},
        )
        asset_ids = [a1.json()["id"], a2.json()["id"]]

        # Bulk assign owner
        resp = await client.post(
            "/api/v1/assets/bulk-assign",
            json={"asset_ids": asset_ids, "owner_user_id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2

        # Verify audit event
        events = await _get_audit_events(test_session, "bulk.owner_assigned")
        matching = [e for e in events if e.payload.get("asset_count") == 2]
        assert len(matching) == 1
        assert matching[0].payload["new_owner_user_id"] == user_id
        assert len(matching[0].payload["asset_ids"]) == 2
