"""Tests for webhook HTTP delivery with mocking."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tessera.models.webhook import (
    ContractPublishedPayload,
    ProposalCreatedPayload,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.webhooks import (
    _deliver_webhook,
    _fire_and_forget,
    _sign_payload,
)

pytestmark = pytest.mark.asyncio


class TestWebhookDelivery:
    """Tests for _deliver_webhook function."""

    async def test_deliver_no_url_configured(self):
        """Returns True (success) when no webhook URL configured."""
        with patch("tessera.services.webhooks.settings") as mock_settings:
            mock_settings.webhook_url = None

            event = WebhookEvent(
                event=WebhookEventType.CONTRACT_PUBLISHED,
                timestamp=datetime.now(UTC),
                payload=ContractPublishedPayload(
                    contract_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    version="1.0.0",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                ),
            )
            result = await _deliver_webhook(event)
            assert result is True

    async def test_deliver_success(self):
        """Successfully delivers webhook."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            event = WebhookEvent(
                event=WebhookEventType.CONTRACT_PUBLISHED,
                timestamp=datetime.now(UTC),
                payload=ContractPublishedPayload(
                    contract_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    version="1.0.0",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                ),
            )
            result = await _deliver_webhook(event)
            assert result is True
            mock_client.post.assert_called_once()

    async def test_deliver_with_signature(self):
        """Adds signature header when secret is configured."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = "my-secret-key"

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            event = WebhookEvent(
                event=WebhookEventType.PROPOSAL_CREATED,
                timestamp=datetime.now(UTC),
                payload=ProposalCreatedPayload(
                    proposal_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                    proposed_version="2.0.0",
                    breaking_changes=[],
                    impacted_consumers=[],
                ),
            )
            result = await _deliver_webhook(event)
            assert result is True

            # Check that signature header was added
            call_args = mock_client.post.call_args
            headers = call_args.kwargs["headers"]
            assert "X-Tessera-Signature" in headers
            assert headers["X-Tessera-Signature"].startswith("sha256=")

    async def test_deliver_retries_on_failure(self):
        """Retries on non-2xx response."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            # Fail first two attempts, succeed on third
            mock_response_fail = AsyncMock()
            mock_response_fail.status_code = 500
            mock_response_fail.text = "Internal Server Error"

            mock_response_success = AsyncMock()
            mock_response_success.status_code = 200
            mock_response_success.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[
                    mock_response_fail,
                    mock_response_fail,
                    mock_response_success,
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
                event=WebhookEventType.CONTRACT_PUBLISHED,
                timestamp=datetime.now(UTC),
                payload=ContractPublishedPayload(
                    contract_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    version="1.0.0",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                ),
            )
            result = await _deliver_webhook(event)
            assert result is True
            assert mock_client.post.call_count == 3

    async def test_deliver_fails_after_max_retries(self):
        """Returns False after exhausting retries."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            # All attempts fail
            mock_response = AsyncMock()
            mock_response.status_code = 503
            mock_response.text = "Service Unavailable"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
                event=WebhookEventType.CONTRACT_PUBLISHED,
                timestamp=datetime.now(UTC),
                payload=ContractPublishedPayload(
                    contract_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    version="1.0.0",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                ),
            )
            result = await _deliver_webhook(event)
            assert result is False


class TestFireAndForget:
    """Tests for _fire_and_forget function."""

    def test_fire_and_forget_no_loop(self):
        """Does not raise when no event loop is running."""
        # This should not raise
        event = WebhookEvent(
            event=WebhookEventType.CONTRACT_PUBLISHED,
            timestamp=datetime.now(UTC),
            payload=ContractPublishedPayload(
                contract_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="test.asset",
                version="1.0.0",
                producer_team_id=uuid4(),
                producer_team_name="test-team",
            ),
        )
        # In a non-async context, this should just log and return
        _fire_and_forget(event)

    async def test_fire_and_forget_with_loop(self):
        """Schedules delivery task when loop is running."""
        with (
            patch("tessera.services.webhooks._deliver_with_tracking"),
            patch("tessera.services.webhooks.asyncio.get_running_loop") as mock_loop,
        ):
            mock_task = MagicMock()
            mock_loop_obj = MagicMock()
            mock_loop_obj.create_task = MagicMock(return_value=mock_task)
            mock_loop.return_value = mock_loop_obj

            event = WebhookEvent(
                event=WebhookEventType.CONTRACT_PUBLISHED,
                timestamp=datetime.now(UTC),
                payload=ContractPublishedPayload(
                    contract_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    version="1.0.0",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                ),
            )
            _fire_and_forget(event)
            mock_loop_obj.create_task.assert_called_once()


class TestSignPayload:
    """Tests for _sign_payload function."""

    def test_sign_returns_hex(self):
        """Signature is a hex string."""
        sig = _sign_payload('{"test": true}', "secret")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_consistent(self):
        """Same input produces same signature."""
        payload = '{"data": "test"}'
        secret = "my-secret"
        sig1 = _sign_payload(payload, secret)
        sig2 = _sign_payload(payload, secret)
        assert sig1 == sig2

    def test_sign_different_secrets(self):
        """Different secrets produce different signatures."""
        payload = '{"data": "test"}'
        sig1 = _sign_payload(payload, "secret1")
        sig2 = _sign_payload(payload, "secret2")
        assert sig1 != sig2

    def test_sign_different_payloads(self):
        """Different payloads produce different signatures."""
        secret = "my-secret"
        sig1 = _sign_payload('{"a": 1}', secret)
        sig2 = _sign_payload('{"b": 2}', secret)
        assert sig1 != sig2
