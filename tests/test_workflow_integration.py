"""Integration tests for the complete proposal workflow and data integrity.

These tests verify:
1. Complete proposal lifecycle: create -> acknowledge -> publish -> new contract
2. Data integrity: owner_user must belong to owner_team
3. Contract version propagation after publish
4. Registration migration to new contract versions
5. Multiple consumer acknowledgment scenarios
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestProposalWorkflowIntegration:
    """Tests for complete proposal workflow from creation to publication."""

    async def test_full_workflow_acknowledge_publish_creates_new_contract(
        self, client: AsyncClient
    ):
        """Complete workflow: breaking change -> all consumers ack -> publish -> new contract."""
        # Setup: producer and two consumers
        producer_resp = await client.post("/api/v1/teams", json={"name": "workflow-producer"})
        consumer1_resp = await client.post("/api/v1/teams", json={"name": "workflow-consumer-1"})
        consumer2_resp = await client.post("/api/v1/teams", json={"name": "workflow-consumer-2"})
        producer_id = producer_resp.json()["id"]
        consumer1_id = consumer1_resp.json()["id"]
        consumer2_id = consumer2_resp.json()["id"]

        # Create asset
        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "workflow.test.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract v1.0.0
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                },
                "compatibility_mode": "backward",
            },
        )
        assert contract_resp.status_code == 201
        contract_id = contract_resp.json()["contract"]["id"]

        # Both consumers register
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer2_id},
        )

        # Create breaking change (removes 'email' field) -> creates proposal
        breaking_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert breaking_resp.status_code == 201
        assert breaking_resp.json()["action"] == "proposal_created"
        proposal_id = breaking_resp.json()["proposal"]["id"]

        # Verify proposal is pending with 2 consumers
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["status"] == "pending"
        assert status["consumers"]["total"] == 2
        assert status["consumers"]["pending"] == 2

        # Consumer 1 acknowledges
        ack1_resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer1_id, "response": "approved"},
        )
        assert ack1_resp.status_code == 201

        # Verify still pending (1 consumer left)
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        status = status_resp.json()
        assert status["status"] == "pending"
        assert status["consumers"]["acknowledged"] == 1
        assert status["consumers"]["pending"] == 1

        # Consumer 2 acknowledges
        ack2_resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer2_id, "response": "approved"},
        )
        assert ack2_resp.status_code == 201

        # Verify proposal is now approved
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        status = status_resp.json()
        assert status["status"] == "approved"
        assert status["consumers"]["acknowledged"] == 2
        assert status["consumers"]["pending"] == 0

        # Publish from approved proposal
        publish_resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": producer_id},
        )
        assert publish_resp.status_code == 200
        assert publish_resp.json()["action"] == "published"
        new_contract = publish_resp.json()["contract"]
        assert new_contract["version"] == "2.0.0"

        # Verify contract history shows both versions
        history_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert history_resp.status_code == 200
        contracts = history_resp.json()["results"]
        versions = [c["version"] for c in contracts]
        assert "1.0.0" in versions
        assert "2.0.0" in versions

        # Verify v2.0.0 is active, v1.0.0 is deprecated
        for c in contracts:
            if c["version"] == "2.0.0":
                assert c["status"] == "active"
            elif c["version"] == "1.0.0":
                assert c["status"] == "deprecated"

    async def test_proposal_with_no_consumers_requires_explicit_publish(self, client: AsyncClient):
        """Proposals with no consumers still require explicit publish (safety feature).

        Even when there are no registered consumers, the proposal workflow requires
        the producer to explicitly publish via /proposals/{id}/publish or force.
        This gives producers a chance to reconsider breaking changes.
        """
        team_resp = await client.post("/api/v1/teams", json={"name": "no-consumer-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "no.consumer.table", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
            },
        )

        # Create breaking change with NO consumers registered
        breaking_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        )
        assert breaking_resp.status_code == 201
        assert breaking_resp.json()["action"] == "proposal_created"
        proposal_id = breaking_resp.json()["proposal"]["id"]

        # Proposal stays pending even with no consumers
        # This is by design - gives producer a chance to reconsider
        proposal_resp = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert proposal_resp.json()["status"] == "pending"

        # Producer can force-approve the proposal
        force_resp = await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")
        assert force_resp.status_code == 200
        assert force_resp.json()["status"] == "approved"

        # Now producer can publish
        publish_resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": team_id},
        )
        assert publish_resp.status_code == 200
        assert publish_resp.json()["action"] == "published"

    async def test_registrations_tracked_on_original_contract(self, client: AsyncClient):
        """Registrations are tied to the contract they registered on."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "reg-track-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "reg-track-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "reg.track.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create v1 contract
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
            },
        )
        v1_contract_id = contract_resp.json()["contract"]["id"]

        # Register consumer on v1
        reg_resp = await client.post(
            f"/api/v1/registrations?contract_id={v1_contract_id}",
            json={"consumer_team_id": consumer_id},
        )
        assert reg_resp.status_code == 201
        registration_id = reg_resp.json()["id"]

        # Create breaking change -> proposal
        breaking_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        )
        proposal_id = breaking_resp.json()["proposal"]["id"]

        # Acknowledge
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": consumer_id, "response": "approved"},
        )

        # Publish v2
        await client.post(
            f"/api/v1/proposals/{proposal_id}/publish",
            json={"version": "2.0.0", "published_by": producer_id},
        )

        # Check that original registration still exists and is on v1 contract
        reg_check = await client.get(f"/api/v1/registrations/{registration_id}")
        assert reg_check.status_code == 200
        assert reg_check.json()["contract_id"] == v1_contract_id


class TestDataIntegrity:
    """Tests for data integrity constraints."""

    async def test_owner_user_must_belong_to_owner_team(self, client: AsyncClient):
        """owner_user_id must be a member of owner_team_id."""
        # Create two teams
        team1_resp = await client.post("/api/v1/teams", json={"name": "integrity-team-1"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "integrity-team-2"})
        assert team1_resp.status_code == 201, f"Failed to create team1: {team1_resp.json()}"
        assert team2_resp.status_code == 201, f"Failed to create team2: {team2_resp.json()}"
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        # Create user in team1
        user_resp = await client.post(
            "/api/v1/users",
            json={"name": "Alice Smith", "email": "team1user@test.com", "team_id": team1_id},
        )
        assert user_resp.status_code == 201, f"Failed to create user: {user_resp.json()}"
        user_id = user_resp.json()["id"]

        # Try to create asset owned by team2 with user from team1 - should fail
        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "integrity.test.asset",
                "owner_team_id": team2_id,
                "owner_user_id": user_id,  # User is in team1, not team2
            },
        )
        # Should reject because user doesn't belong to owner team
        assert (
            asset_resp.status_code == 400
        ), f"Expected 400, got {asset_resp.status_code}: {asset_resp.json()}"
        # Verify error message mentions owner/team mismatch
        response_text = str(asset_resp.json())
        assert "owner" in response_text.lower() and "team" in response_text.lower()

    async def test_owner_user_in_same_team_succeeds(self, client: AsyncClient):
        """owner_user_id in same team as owner_team_id should work."""
        team_resp = await client.post("/api/v1/teams", json={"name": "same-team-test"})
        team_id = team_resp.json()["id"]

        user_resp = await client.post(
            "/api/v1/users",
            json={"name": "Same Team User", "email": "sameteam@test.com", "team_id": team_id},
        )
        user_id = user_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "same.team.asset",
                "owner_team_id": team_id,
                "owner_user_id": user_id,
            },
        )
        assert asset_resp.status_code == 201
        assert asset_resp.json()["owner_user_id"] == user_id

    async def test_update_owner_user_to_different_team_fails(self, client: AsyncClient):
        """Cannot update owner_user to someone outside owner_team."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "update-team-1"})
        team2_resp = await client.post("/api/v1/teams", json={"name": "update-team-2"})
        assert team1_resp.status_code == 201, f"Failed to create team1: {team1_resp.json()}"
        assert team2_resp.status_code == 201, f"Failed to create team2: {team2_resp.json()}"
        team1_id = team1_resp.json()["id"]
        team2_id = team2_resp.json()["id"]

        user1_resp = await client.post(
            "/api/v1/users",
            json={"name": "Bob Jones", "email": "user1@test.com", "team_id": team1_id},
        )
        assert user1_resp.status_code == 201, f"Failed to create user1: {user1_resp.json()}"
        user1_id = user1_resp.json()["id"]

        user2_resp = await client.post(
            "/api/v1/users",
            json={"name": "Carol White", "email": "user2@test.com", "team_id": team2_id},
        )
        assert user2_resp.status_code == 201, f"Failed to create user2: {user2_resp.json()}"
        user2_id = user2_resp.json()["id"]

        # Create asset owned by team1 with user1
        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "update.owner.test",
                "owner_team_id": team1_id,
                "owner_user_id": user1_id,
            },
        )
        assert asset_resp.status_code == 201, f"Failed to create asset: {asset_resp.json()}"
        asset_id = asset_resp.json()["id"]

        # Try to update owner_user to user from different team
        update_resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"owner_user_id": user2_id},
        )
        # Should fail because user2 is not in team1
        assert (
            update_resp.status_code == 400
        ), f"Expected 400, got {update_resp.status_code}: {update_resp.json()}"
        # Verify error message mentions owner/team mismatch
        response_text = str(update_resp.json())
        assert "owner" in response_text.lower() and "team" in response_text.lower()


class TestContractVersionPropagation:
    """Tests for contract version propagation after changes."""

    async def test_compatible_change_auto_publishes(self, client: AsyncClient):
        """Compatible changes should auto-publish without proposal."""
        team_resp = await client.post("/api/v1/teams", json={"name": "compat-test-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "compat.change.table", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create v1.0.0
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )

        # Add new optional field (backward compatible)
        compat_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.1.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "new_field": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        assert compat_resp.status_code == 201
        # Should auto-publish, not create proposal
        assert compat_resp.json()["action"] in ["published", "auto_published"]
        assert "contract" in compat_resp.json()

        # Verify both versions exist
        history = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        versions = [c["version"] for c in history.json()["results"]]
        assert "1.0.0" in versions
        assert "1.1.0" in versions

    async def test_breaking_change_creates_proposal(self, client: AsyncClient):
        """Breaking changes with consumers should create a proposal."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "break-test-prod"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "break-test-cons"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "break.change.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create v1.0.0
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

        # Remove field (breaking change)
        break_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        assert break_resp.status_code == 201
        assert break_resp.json()["action"] == "proposal_created"
        assert "proposal" in break_resp.json()


class TestMultipleConsumerScenarios:
    """Tests for scenarios with multiple consumers."""

    async def test_one_blocked_rejects_proposal(self, client: AsyncClient):
        """If any consumer blocks, proposal is rejected."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "multi-block-prod"})
        cons1_resp = await client.post("/api/v1/teams", json={"name": "multi-block-cons1"})
        cons2_resp = await client.post("/api/v1/teams", json={"name": "multi-block-cons2"})
        producer_id = producer_resp.json()["id"]
        cons1_id = cons1_resp.json()["id"]
        cons2_id = cons2_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "multi.block.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register both consumers
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": cons1_id},
        )
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": cons2_id},
        )

        # Create breaking change
        prop_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        )
        proposal_id = prop_resp.json()["proposal"]["id"]

        # Consumer 1 approves
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": cons1_id, "response": "approved"},
        )

        # Consumer 2 blocks
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": cons2_id, "response": "blocked"},
        )

        # Proposal should be rejected
        prop_status = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert prop_status.json()["status"] == "rejected"

    async def test_all_approve_approves_proposal(self, client: AsyncClient):
        """When all consumers approve, proposal is approved."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "multi-approve-prod"})
        cons1_resp = await client.post("/api/v1/teams", json={"name": "multi-approve-cons1"})
        cons2_resp = await client.post("/api/v1/teams", json={"name": "multi-approve-cons2"})
        cons3_resp = await client.post("/api/v1/teams", json={"name": "multi-approve-cons3"})
        producer_id = producer_resp.json()["id"]
        cons1_id = cons1_resp.json()["id"]
        cons2_id = cons2_resp.json()["id"]
        cons3_id = cons3_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "multi.approve.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Register all consumers
        for cons_id in [cons1_id, cons2_id, cons3_id]:
            await client.post(
                f"/api/v1/registrations?contract_id={contract_id}",
                json={"consumer_team_id": cons_id},
            )

        # Create breaking change
        prop_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        )
        proposal_id = prop_resp.json()["proposal"]["id"]

        # All consumers approve
        for cons_id in [cons1_id, cons2_id, cons3_id]:
            await client.post(
                f"/api/v1/proposals/{proposal_id}/acknowledge",
                json={"consumer_team_id": cons_id, "response": "approved"},
            )

        # Proposal should be approved
        prop_status = await client.get(f"/api/v1/proposals/{proposal_id}")
        assert prop_status.json()["status"] == "approved"

    async def test_unregistered_team_can_acknowledge(self, client: AsyncClient):
        """Unregistered teams can still acknowledge (they may want to voice opinion).

        Note: The current API allows unregistered teams to acknowledge.
        This is arguably valid - a team may want to express support/concern
        even if they're not a registered consumer.
        """
        producer_resp = await client.post("/api/v1/teams", json={"name": "unreg-ack-prod"})
        registered_resp = await client.post("/api/v1/teams", json={"name": "unreg-ack-reg"})
        unregistered_resp = await client.post("/api/v1/teams", json={"name": "unreg-ack-unreg"})
        producer_id = producer_resp.json()["id"]
        registered_id = registered_resp.json()["id"]
        unregistered_id = unregistered_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "unreg.ack.table", "owner_team_id": producer_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "field": {"type": "string"}},
                },
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        # Only register one consumer
        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": registered_id},
        )

        # Create breaking change
        prop_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        )
        proposal_id = prop_resp.json()["proposal"]["id"]

        # Unregistered team can acknowledge
        # Current behavior: This is allowed (they can express an opinion)
        ack_resp = await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": unregistered_id, "response": "approved"},
        )
        # The API currently allows this - document the actual behavior
        assert ack_resp.status_code == 201

        # But the proposal won't auto-approve until the registered consumer acknowledges
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.json()["status"] == "pending"

        # Now registered consumer acknowledges
        await client.post(
            f"/api/v1/proposals/{proposal_id}/acknowledge",
            json={"consumer_team_id": registered_id, "response": "approved"},
        )

        # Now it should be approved
        status_resp = await client.get(f"/api/v1/proposals/{proposal_id}/status")
        assert status_resp.json()["status"] == "approved"
