"""Tests for concurrent operations to verify race condition handling.

These tests verify that concurrent operations are handled correctly:
1. Two teams acknowledging the same proposal sequentially
2. Two contracts being published for the same asset with the same version
3. Rapid sequential publishes don't create version gaps
4. Acknowledgment during status changes is handled gracefully

Note: SQLite does not support row-level locking (SELECT FOR UPDATE is a no-op),
so true concurrent race condition tests require PostgreSQL. These tests verify
the sequential behavior and duplicate detection logic that prevents data corruption.
"""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestProposalAcknowledgment:
    """Tests for proposal acknowledgment scenarios."""

    async def _setup_proposal_with_consumers(
        self, client: AsyncClient, num_consumers: int = 2, suffix: str = ""
    ) -> dict[str, Any]:
        """Create an asset with a breaking change proposal and multiple registered consumers.

        Returns dict with asset_id, proposal_id, producer_id, and consumer_ids.
        """
        # Create producer team
        producer_resp = await client.post("/api/v1/teams", json={"name": f"ack-producer{suffix}"})
        assert producer_resp.status_code == 201
        producer_id = producer_resp.json()["id"]

        # Create consumer teams
        consumer_ids = []
        for i in range(num_consumers):
            consumer_resp = await client.post(
                "/api/v1/teams", json={"name": f"ack-consumer-{i}{suffix}"}
            )
            assert consumer_resp.status_code == 201
            consumer_ids.append(consumer_resp.json()["id"])

        # Create asset (FQN only allows alphanumeric and underscores)
        safe_suffix = suffix.replace("-", "_")
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": f"ack.test{safe_suffix}.table", "owner_team_id": producer_id},
        )
        assert asset_resp.status_code == 201
        asset_id = asset_resp.json()["id"]

        # Create initial contract with required field
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                    "required": ["id", "name"],
                },
                "compatibility_mode": "backward",
            },
        )
        assert contract_resp.status_code == 201
        contract_id = contract_resp.json()["contract"]["id"]

        # Register all consumers
        for consumer_id in consumer_ids:
            reg_resp = await client.post(
                f"/api/v1/registrations?contract_id={contract_id}",
                json={"consumer_team_id": consumer_id},
            )
            assert reg_resp.status_code == 201

        # Create breaking change (remove required field) - creates proposal
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "compatibility_mode": "backward",
            },
        )
        assert proposal_resp.status_code == 201
        assert proposal_resp.json()["action"] == "proposal_created"
        proposal_id = proposal_resp.json()["proposal"]["id"]

        return {
            "asset_id": asset_id,
            "proposal_id": proposal_id,
            "producer_id": producer_id,
            "consumer_ids": consumer_ids,
        }

    async def test_two_teams_acknowledge_proposal_sequentially(self, client: AsyncClient):
        """Both acknowledgments should succeed and trigger auto-approval.

        When two consumers acknowledge the same proposal sequentially,
        both should succeed and the proposal should auto-approve when all
        consumers have acknowledged.
        """
        setup = await self._setup_proposal_with_consumers(client, num_consumers=2, suffix="-seq")
        proposal_id = setup["proposal_id"]
        consumer_ids = setup["consumer_ids"]

        # First acknowledgment
        resp1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[0],
                "response": "approved",
                "notes": "First consumer acknowledges",
            },
        )
        assert resp1.status_code == 201

        # Second acknowledgment
        resp2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[1],
                "response": "approved",
                "notes": "Second consumer acknowledges",
            },
        )
        assert resp2.status_code == 201

        # Verify proposal is now approved (all consumers acknowledged)
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["status"] == "approved"
        assert status["consumers"]["acknowledged"] == 2
        assert status["consumers"]["pending"] == 0

    async def test_duplicate_acknowledgment_rejected(self, client: AsyncClient):
        """Second acknowledgment from same team should be rejected.

        If a team tries to acknowledge a proposal twice,
        the second attempt should fail with a duplicate error.
        """
        # Use 2 consumers so proposal stays pending after first ack
        setup = await self._setup_proposal_with_consumers(client, num_consumers=2, suffix="-dup")
        proposal_id = setup["proposal_id"]
        consumer_id = setup["consumer_ids"][0]

        # First acknowledgment (proposal stays pending since there's another consumer)
        resp1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "notes": "First acknowledgment",
            },
        )
        assert resp1.status_code == 201

        # Verify proposal is still pending
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.json()["status"] == "pending"

        # Second acknowledgment from same team should fail
        resp2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_id,
                "response": "approved",
                "notes": "Duplicate acknowledgment",
            },
        )
        assert resp2.status_code == 409
        data = resp2.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "already acknowledged" in error_msg.lower()

    async def test_all_consumers_acknowledge_triggers_approval(self, client: AsyncClient):
        """Proposal auto-approves when all consumers acknowledge.

        After all registered consumers acknowledge, the proposal should
        automatically transition to approved status.
        """
        setup = await self._setup_proposal_with_consumers(client, num_consumers=2, suffix="-auto")
        proposal_id = setup["proposal_id"]
        consumer_ids = setup["consumer_ids"]

        # First consumer acknowledges - should NOT auto-approve yet
        resp1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[0],
                "response": "approved",
                "notes": "First ack",
            },
        )
        assert resp1.status_code == 201

        # Check status - should still be pending
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "pending"

        # Second consumer acknowledges - this should trigger auto-approval
        resp2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[1],
                "response": "approved",
                "notes": "Second ack",
            },
        )
        assert resp2.status_code == 201

        # Verify proposal is now approved
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "approved"

    async def test_block_rejects_proposal(self, client: AsyncClient):
        """If one consumer blocks, proposal should be rejected.

        The blocking response immediately rejects the proposal.
        """
        setup = await self._setup_proposal_with_consumers(client, num_consumers=2, suffix="-blk")
        proposal_id = setup["proposal_id"]
        consumer_ids = setup["consumer_ids"]

        # First consumer approves
        resp1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[0],
                "response": "approved",
                "notes": "Approved",
            },
        )
        assert resp1.status_code == 201

        # Second consumer blocks
        resp2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[1],
                "response": "blocked",
                "notes": "Cannot accept this breaking change",
            },
        )
        assert resp2.status_code == 201

        # Proposal should be rejected
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "rejected"

    async def test_acknowledge_rejected_proposal_fails(self, client: AsyncClient):
        """Cannot acknowledge a proposal that's already rejected."""
        setup = await self._setup_proposal_with_consumers(client, num_consumers=2, suffix="-rej")
        proposal_id = setup["proposal_id"]
        consumer_ids = setup["consumer_ids"]

        # First consumer blocks - rejects the proposal
        resp1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[0],
                "response": "blocked",
                "notes": "Blocked",
            },
        )
        assert resp1.status_code == 201

        # Second consumer tries to acknowledge - should fail
        resp2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": consumer_ids[1],
                "response": "approved",
                "notes": "Too late",
            },
        )
        assert resp2.status_code == 400
        data = resp2.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "not pending" in error_msg.lower()


class TestContractPublish:
    """Tests for contract publishing scenarios."""

    async def _setup_asset(self, client: AsyncClient, suffix: str = "") -> dict[str, str]:
        """Create a team and asset for testing."""
        team_resp = await client.post("/api/v1/teams", json={"name": f"publish-team{suffix}"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # FQN only allows alphanumeric and underscores
        safe_suffix = suffix.replace("-", "_")
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": f"publish{safe_suffix}.table", "owner_team_id": team_id},
        )
        assert asset_resp.status_code == 201
        asset_id = asset_resp.json()["id"]

        return {"team_id": team_id, "asset_id": asset_id}

    async def test_duplicate_version_rejected(self, client: AsyncClient):
        """Second publish with same version should get 409 Conflict.

        When a version already exists, publishing the same version again
        should fail with a version conflict error.
        """
        setup = await self._setup_asset(client, suffix="-dupver")
        asset_id = setup["asset_id"]
        team_id = setup["team_id"]

        # First publish
        resp1 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp1.status_code == 201

        # Second publish with same version should fail
        resp2 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp2.status_code == 409
        data = resp2.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "already exists" in error_msg.lower()

        # Verify only one contract exists
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        contracts = contracts_resp.json()["results"]
        assert len(contracts) == 1
        assert contracts[0]["version"] == "1.0.0"

    async def test_sequential_publishes_no_version_gaps(self, client: AsyncClient):
        """Sequential publishes should not create version gaps.

        Publishing 1.0.0, 1.1.0, 1.2.0 in sequence should all succeed
        and maintain proper version ordering.
        """
        setup = await self._setup_asset(client, suffix="-seqver")
        asset_id = setup["asset_id"]
        team_id = setup["team_id"]

        versions = ["1.0.0", "1.1.0", "1.2.0"]
        for version in versions:
            resp = await client.post(
                f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
                json={
                    "version": version,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "version": {"type": "string", "const": version},
                        },
                    },
                    "compatibility_mode": "backward",
                },
            )
            assert resp.status_code == 201, f"Failed to publish {version}: {resp.json()}"

        # Verify all versions exist
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        published_versions = {c["version"] for c in contracts_resp.json()["results"]}
        assert published_versions == set(versions)

    async def test_different_versions_succeed(self, client: AsyncClient):
        """Different versions can be published for the same asset.

        Each unique version number should be accepted.
        """
        setup = await self._setup_asset(client, suffix="-diffver")
        asset_id = setup["asset_id"]
        team_id = setup["team_id"]

        # Publish first version
        resp1 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp1.status_code == 201

        # Publish different version
        resp2 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp2.status_code == 201

        # Verify both versions exist
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        published_versions = {c["version"] for c in contracts_resp.json()["results"]}
        assert "1.0.0" in published_versions
        assert "2.0.0" in published_versions


class TestProposalCreation:
    """Tests for proposal creation scenarios."""

    async def _setup_asset_with_contract_and_consumer(
        self, client: AsyncClient, suffix: str = ""
    ) -> dict[str, str]:
        """Create asset with initial contract and one registered consumer."""
        producer_resp = await client.post(
            "/api/v1/teams", json={"name": f"prop-create-producer{suffix}"}
        )
        producer_id = producer_resp.json()["id"]

        consumer_resp = await client.post(
            "/api/v1/teams", json={"name": f"prop-create-consumer{suffix}"}
        )
        consumer_id = consumer_resp.json()["id"]

        # FQN only allows alphanumeric and underscores
        safe_suffix = suffix.replace("-", "_")
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": f"proposal.creation{safe_suffix}.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                    "required": ["id", "name"],
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        return {
            "producer_id": producer_id,
            "consumer_id": consumer_id,
            "asset_id": asset_id,
        }

    async def test_duplicate_pending_proposal_rejected(self, client: AsyncClient):
        """Second breaking change while proposal pending should be rejected.

        Only one pending proposal per asset is allowed at a time.
        """
        setup = await self._setup_asset_with_contract_and_consumer(client, suffix="-dupprop")
        asset_id = setup["asset_id"]
        producer_id = setup["producer_id"]

        # First breaking change creates proposal
        resp1 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp1.status_code == 201
        assert resp1.json()["action"] == "proposal_created"

        # Second breaking change should fail
        resp2 = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "3.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert resp2.status_code == 409
        data = resp2.json()
        error_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "pending proposal" in error_msg.lower()


class TestRegistration:
    """Tests for registration scenarios.

    Note: The registration endpoint currently does not check for duplicate
    registrations (same team registering for same contract). This is a known
    gap - see related issues. These tests verify the expected behavior of the
    registration workflow.
    """

    async def test_registration_workflow(self, client: AsyncClient):
        """Consumer can register for a contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "reg-producer-wf"})
        producer_id = team_resp.json()["id"]

        consumer_resp = await client.post("/api/v1/teams", json={"name": "reg-consumer-wf"})
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "registration.workflow.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer
        resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        assert resp.status_code == 201
        assert resp.json()["consumer_team_id"] == consumer_id
        assert resp.json()["contract_id"] == contract_id
        assert resp.json()["status"] == "active"

    async def test_multiple_consumers_can_register(self, client: AsyncClient):
        """Multiple different consumers can register for the same contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "reg-producer-multi"})
        producer_id = team_resp.json()["id"]

        # Create multiple consumers
        consumer_ids = []
        for i in range(3):
            consumer_resp = await client.post(
                "/api/v1/teams", json={"name": f"reg-consumer-multi-{i}"}
            )
            consumer_ids.append(consumer_resp.json()["id"])

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "registration.multi.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register all consumers
        for consumer_id in consumer_ids:
            resp = await client.post(
                f"/api/v1/registrations?contract_id={contract_id}",
                json={"consumer_team_id": consumer_id},
            )
            assert resp.status_code == 201

        # Verify all registrations exist
        list_resp = await client.get(f"/api/v1/registrations?contract_id={contract_id}")
        assert list_resp.status_code == 200
        registrations = list_resp.json()["results"]
        registered_teams = {r["consumer_team_id"] for r in registrations}
        assert registered_teams == set(consumer_ids)
