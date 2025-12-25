"""Tests for webhook functionality."""

from datetime import UTC, datetime
from uuid import uuid4

from tessera.models.webhook import (
    BreakingChange,
    ContractPublishedPayload,
    ImpactedConsumer,
    ProposalCreatedPayload,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.webhooks import _sign_payload


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
