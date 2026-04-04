"""Tests for Slack message delivery service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tessera.services.slack_delivery import (
    deliver_slack_message,
)

pytestmark = pytest.mark.asyncio


def _make_config(
    webhook_url: str | None = None,
    bot_token: str | None = None,
    channel_id: str = "CABC123",
) -> MagicMock:
    """Create a mock SlackConfigDB."""
    config = MagicMock()
    config.webhook_url = webhook_url
    config.bot_token = bot_token
    config.channel_id = channel_id
    return config


class TestDeliverViaWebhook:
    """Tests for webhook-based delivery."""

    async def test_successful_delivery(self):
        """Delivers message via webhook successfully."""
        config = _make_config(webhook_url="https://hooks.slack.com/services/T/B/x")
        payload = {"text": "test", "blocks": []}

        with (
            patch(
                "tessera.services.slack_delivery.validate_webhook_url",
                new_callable=AsyncMock,
            ) as mock_validate,
            patch("tessera.services.slack_delivery.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_validate.return_value = (True, "")

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await deliver_slack_message(config, payload)

        assert result.success is True
        assert result.error is None

    async def test_ssrf_rejected(self):
        """Rejects delivery when SSRF validation fails."""
        config = _make_config(webhook_url="http://169.254.169.254/metadata")
        payload = {"text": "test"}

        with patch(
            "tessera.services.slack_delivery.validate_webhook_url",
            new_callable=AsyncMock,
        ) as mock_validate:
            mock_validate.return_value = (False, "IP address is not global")
            result = await deliver_slack_message(config, payload)

        assert result.success is False
        assert "SSRF" in result.error  # type: ignore[operator]

    async def test_webhook_error_response(self):
        """Handles non-200 response from Slack webhook."""
        config = _make_config(webhook_url="https://hooks.slack.com/services/T/B/x")
        payload = {"text": "test"}

        with (
            patch(
                "tessera.services.slack_delivery.validate_webhook_url",
                new_callable=AsyncMock,
            ) as mock_validate,
            patch("tessera.services.slack_delivery.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_validate.return_value = (True, "")

            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "internal_error"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await deliver_slack_message(config, payload)

        assert result.success is False
        assert "500" in result.error  # type: ignore[operator]


class TestDeliverViaBotToken:
    """Tests for bot-token-based delivery."""

    async def test_successful_delivery(self):
        """Delivers message via bot token successfully."""
        config = _make_config(bot_token="xoxb-test-token-123")
        payload = {"text": "test", "blocks": [{"type": "section"}]}

        with patch("tessera.services.slack_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await deliver_slack_message(config, payload)

        assert result.success is True

        # Verify bearer token was used
        call_kwargs = mock_client.post.call_args
        assert "Bearer xoxb-test-token-123" in call_kwargs.kwargs["headers"]["Authorization"]

    async def test_slack_api_error(self):
        """Handles Slack API error response."""
        config = _make_config(bot_token="xoxb-test-token")
        payload = {"text": "test"}

        with patch("tessera.services.slack_delivery.httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": False, "error": "channel_not_found"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await deliver_slack_message(config, payload)

        assert result.success is False
        assert "channel_not_found" in result.error  # type: ignore[operator]


class TestNoAuthMethod:
    """Tests for configs with neither auth method."""

    async def test_returns_error(self):
        """Returns error when no auth method configured."""
        config = _make_config()  # Neither webhook_url nor bot_token
        result = await deliver_slack_message(config, {"text": "test"})

        assert result.success is False
        assert "No webhook_url or bot_token" in result.error  # type: ignore[operator]
