"""Tests for webhook functionality."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tessera.models.webhook import (
    AcknowledgmentPayload,
    BreakingChange,
    ContractPublishedPayload,
    ImpactedConsumer,
    ProposalCreatedPayload,
    ProposalStatusPayload,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.webhooks import _sign_payload

pytestmark = pytest.mark.asyncio


class TestWebhookModels:
    """Tests for webhook models."""

    def test_webhook_event_serialization(self):
        """Test that webhook events serialize correctly."""
        proposal_id = uuid4()
        asset_id = uuid4()
        producer_team_id = uuid4()

        event = WebhookEvent(
            event=WebhookEventType.PROPOSAL_CREATED,
            timestamp=datetime.now(UTC),
            payload=ProposalCreatedPayload(
                proposal_id=proposal_id,
                asset_id=asset_id,
                asset_fqn="analytics.users",
                producer_team_id=producer_team_id,
                producer_team_name="analytics-team",
                proposed_version="2.0.0",
                breaking_changes=[
                    BreakingChange(
                        change_type="dropped_column",
                        path="$.properties.old_field",
                        message="Field 'old_field' was removed",
                    )
                ],
                impacted_consumers=[
                    ImpactedConsumer(
                        team_id=uuid4(),
                        team_name="downstream-team",
                        pinned_version="1.0.0",
                    )
                ],
            ),
        )

        # Should serialize without error
        json_str = event.model_dump_json()
        assert "proposal.created" in json_str
        assert "analytics.users" in json_str
        assert "dropped_column" in json_str

    def test_contract_published_payload(self):
        """Test contract published payload."""
        contract_id = uuid4()
        asset_id = uuid4()
        producer_team_id = uuid4()
        proposal_id = uuid4()

        payload = ContractPublishedPayload(
            contract_id=contract_id,
            asset_id=asset_id,
            asset_fqn="warehouse.orders",
            version="3.0.0",
            producer_team_id=producer_team_id,
            producer_team_name="data-team",
            from_proposal_id=proposal_id,
        )

        assert payload.contract_id == contract_id
        assert payload.from_proposal_id == proposal_id


class TestWebhookSigning:
    """Tests for webhook HMAC signing."""

    def test_sign_payload(self):
        """Test that payloads are signed correctly."""
        payload = '{"event": "test"}'
        secret = "test-secret"

        signature = _sign_payload(payload, secret)

        # Should be a hex digest
        assert len(signature) == 64  # SHA-256 produces 64 hex chars
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_payload_consistency(self):
        """Test that same payload+secret produces same signature."""
        payload = '{"data": "consistent"}'
        secret = "my-secret-key"

        sig1 = _sign_payload(payload, secret)
        sig2 = _sign_payload(payload, secret)

        assert sig1 == sig2

    def test_sign_payload_different_secrets(self):
        """Test that different secrets produce different signatures."""
        payload = '{"data": "test"}'

        sig1 = _sign_payload(payload, "secret-1")
        sig2 = _sign_payload(payload, "secret-2")

        assert sig1 != sig2


class TestWebhookEventTypes:
    """Tests for webhook event types."""

    def test_all_event_types_have_values(self):
        """Test that all event types have string values."""
        expected_events = [
            "proposal.created",
            "proposal.acknowledged",
            "proposal.approved",
            "proposal.rejected",
            "proposal.force_approved",
            "proposal.withdrawn",
            "contract.published",
        ]

        for event_type in WebhookEventType:
            assert event_type.value in expected_events


class TestAdditionalWebhookPayloads:
    """Tests for additional webhook payload types."""

    def test_acknowledgment_payload(self):
        """Test acknowledgment payload serialization."""
        proposal_id = uuid4()
        asset_id = uuid4()
        consumer_team_id = uuid4()

        payload = AcknowledgmentPayload(
            proposal_id=proposal_id,
            asset_id=asset_id,
            asset_fqn="analytics.events",
            consumer_team_id=consumer_team_id,
            consumer_team_name="downstream-team",
            response="acknowledged",
            migration_deadline=datetime.now(UTC),
            notes="Will migrate by next sprint",
            pending_count=2,
            acknowledged_count=3,
        )

        assert payload.proposal_id == proposal_id
        assert payload.pending_count == 2
        assert payload.acknowledged_count == 3
        assert payload.notes == "Will migrate by next sprint"

    def test_acknowledgment_payload_optional_fields(self):
        """Test acknowledgment payload with optional fields as None."""
        payload = AcknowledgmentPayload(
            proposal_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="data.users",
            consumer_team_id=uuid4(),
            consumer_team_name="consumer",
            response="accepted",
            migration_deadline=None,
            notes=None,
            pending_count=0,
            acknowledged_count=1,
        )

        assert payload.migration_deadline is None
        assert payload.notes is None

    def test_proposal_status_payload(self):
        """Test proposal status payload."""
        proposal_id = uuid4()
        asset_id = uuid4()
        actor_team_id = uuid4()

        payload = ProposalStatusPayload(
            proposal_id=proposal_id,
            asset_id=asset_id,
            asset_fqn="warehouse.orders",
            status="approved",
            actor_team_id=actor_team_id,
            actor_team_name="approving-team",
        )

        assert payload.status == "approved"
        assert payload.actor_team_id == actor_team_id

    def test_proposal_status_payload_no_actor(self):
        """Test proposal status payload without actor."""
        payload = ProposalStatusPayload(
            proposal_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="data.metrics",
            status="auto_approved",
            actor_team_id=None,
            actor_team_name=None,
        )

        assert payload.actor_team_id is None
        assert payload.actor_team_name is None

    def test_breaking_change_with_details(self):
        """Test breaking change with extra details."""
        change = BreakingChange(
            change_type="type_narrowed",
            path="$.properties.amount.type",
            message="Type changed from number to integer",
            details={"old_type": "number", "new_type": "integer"},
        )

        assert change.change_type == "type_narrowed"
        assert change.details["old_type"] == "number"

    def test_impacted_consumer_without_pin(self):
        """Test impacted consumer without pinned version."""
        consumer = ImpactedConsumer(
            team_id=uuid4(),
            team_name="flexible-consumer",
            pinned_version=None,
        )

        assert consumer.pinned_version is None


class TestWebhookEventCreation:
    """Tests for creating webhook events."""

    def test_create_proposal_acknowledged_event(self):
        """Create a proposal acknowledged event."""
        event = WebhookEvent(
            event=WebhookEventType.PROPOSAL_ACKNOWLEDGED,
            timestamp=datetime.now(UTC),
            payload=AcknowledgmentPayload(
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="data.users",
                consumer_team_id=uuid4(),
                consumer_team_name="consumer-team",
                response="acknowledged",
                migration_deadline=None,
                notes=None,
                pending_count=1,
                acknowledged_count=2,
            ),
        )

        json_str = event.model_dump_json()
        assert "proposal.acknowledged" in json_str

    def test_create_proposal_approved_event(self):
        """Create a proposal approved event."""
        event = WebhookEvent(
            event=WebhookEventType.PROPOSAL_APPROVED,
            timestamp=datetime.now(UTC),
            payload=ProposalStatusPayload(
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="metrics.revenue",
                status="approved",
                actor_team_id=uuid4(),
                actor_team_name="producer-team",
            ),
        )

        json_str = event.model_dump_json()
        assert "proposal.approved" in json_str

    def test_create_proposal_rejected_event(self):
        """Create a proposal rejected event."""
        event = WebhookEvent(
            event=WebhookEventType.PROPOSAL_REJECTED,
            timestamp=datetime.now(UTC),
            payload=ProposalStatusPayload(
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="raw.events",
                status="rejected",
                actor_team_id=uuid4(),
                actor_team_name="blocking-team",
            ),
        )

        json_str = event.model_dump_json()
        assert "proposal.rejected" in json_str

    def test_create_contract_published_event(self):
        """Create a contract published event."""
        event = WebhookEvent(
            event=WebhookEventType.CONTRACT_PUBLISHED,
            timestamp=datetime.now(UTC),
            payload=ContractPublishedPayload(
                contract_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="staging.customers",
                version="2.1.0",
                producer_team_id=uuid4(),
                producer_team_name="data-team",
                from_proposal_id=uuid4(),
            ),
        )

        json_str = event.model_dump_json()
        assert "contract.published" in json_str
        assert "2.1.0" in json_str


class TestWebhookServiceFunctions:
    """Tests for webhook service high-level functions."""

    async def test_send_proposal_created_no_webhook_url(self):
        """send_proposal_created does nothing without webhook URL."""
        from tessera.services.webhooks import send_proposal_created

        # Should not raise - just logs and returns
        await send_proposal_created(
            proposal_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="test.asset",
            producer_team_id=uuid4(),
            producer_team_name="test-team",
            proposed_version="2.0.0",
            breaking_changes=[
                {"change_type": "dropped_column", "path": "$.x", "message": "removed"}
            ],
            impacted_consumers=[{"team_id": str(uuid4()), "team_name": "consumer"}],
        )

    async def test_send_proposal_acknowledged_no_webhook_url(self):
        """send_proposal_acknowledged does nothing without webhook URL."""
        from tessera.services.webhooks import send_proposal_acknowledged

        await send_proposal_acknowledged(
            proposal_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="test.asset",
            consumer_team_id=uuid4(),
            consumer_team_name="consumer",
            response="acknowledged",
            migration_deadline=None,
            notes=None,
            pending_count=0,
            acknowledged_count=1,
        )

    async def test_send_proposal_status_change_no_webhook_url(self):
        """send_proposal_status_change does nothing without webhook URL."""
        from tessera.services.webhooks import send_proposal_status_change

        await send_proposal_status_change(
            event_type=WebhookEventType.PROPOSAL_APPROVED,
            proposal_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="test.asset",
            status="approved",
            actor_team_id=uuid4(),
            actor_team_name="approver",
        )

    async def test_send_contract_published_no_webhook_url(self):
        """send_contract_published does nothing without webhook URL."""
        from tessera.services.webhooks import send_contract_published

        await send_contract_published(
            contract_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="test.asset",
            version="1.0.0",
            producer_team_id=uuid4(),
            producer_team_name="producer",
            from_proposal_id=None,
        )
