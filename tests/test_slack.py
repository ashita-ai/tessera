"""Tests for Slack notification service."""

from unittest.mock import AsyncMock, patch

import pytest

from tessera.services.slack import (
    notify_contract_published,
    notify_proposal_acknowledged,
    notify_proposal_approved,
    notify_proposal_created,
    send_slack_message,
)

pytestmark = pytest.mark.asyncio


class TestSendSlackMessage:
    """Tests for send_slack_message function."""

    async def test_send_message_no_url_configured(self):
        """Returns False when Slack webhook URL not configured."""
        with patch("tessera.services.slack.settings") as mock_settings:
            mock_settings.slack_webhook_url = None
            result = await send_slack_message("Test message")
            assert result is False

    async def test_send_message_success(self):
        """Successfully sends message to Slack."""
        with (
            patch("tessera.services.slack.settings") as mock_settings,
            patch("tessera.services.slack.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/test"

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await send_slack_message("Test message")
            assert result is True

    async def test_send_message_with_blocks(self):
        """Sends message with Block Kit blocks."""
        with (
            patch("tessera.services.slack.settings") as mock_settings,
            patch("tessera.services.slack.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/test"

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}}]
            result = await send_slack_message("Fallback", blocks=blocks)
            assert result is True

            # Verify blocks were sent
            call_args = mock_client.post.call_args
            assert "blocks" in call_args.kwargs["json"]

    async def test_send_message_failure(self):
        """Returns False when Slack returns error."""
        with (
            patch("tessera.services.slack.settings") as mock_settings,
            patch("tessera.services.slack.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/test"

            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "internal_error"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await send_slack_message("Test message")
            assert result is False

    async def test_send_message_exception(self):
        """Returns False when exception occurs."""
        with (
            patch("tessera.services.slack.settings") as mock_settings,
            patch("tessera.services.slack.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/test"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await send_slack_message("Test message")
            assert result is False


class TestNotifyProposalCreated:
    """Tests for notify_proposal_created."""

    async def test_notify_proposal_created(self):
        """Sends proposal created notification."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            result = await notify_proposal_created(
                asset_fqn="analytics.users",
                version="2.0.0",
                producer_team="data-team",
                affected_consumers=["marketing", "finance"],
                breaking_changes=[
                    {"path": "$.email", "change": "removed"},
                    {"path": "$.name", "change": "type changed"},
                ],
            )
            assert result is True
            mock_send.assert_called_once()

    async def test_notify_proposal_created_many_changes(self):
        """Truncates long lists of changes."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            # More than 5 changes should be truncated
            breaking_changes = [{"path": f"$.field{i}", "change": "removed"} for i in range(10)]
            affected_consumers = [f"team-{i}" for i in range(10)]

            await notify_proposal_created(
                asset_fqn="analytics.orders",
                version="3.0.0",
                producer_team="data-team",
                affected_consumers=affected_consumers,
                breaking_changes=breaking_changes,
            )

            # Should still call send_slack_message
            mock_send.assert_called_once()


class TestNotifyProposalAcknowledged:
    """Tests for notify_proposal_acknowledged."""

    async def test_notify_approved(self):
        """Sends approved acknowledgment notification."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            result = await notify_proposal_acknowledged(
                asset_fqn="analytics.users",
                consumer_team="marketing",
                response="approved",
            )
            assert result is True
            mock_send.assert_called_once()

    async def test_notify_blocked(self):
        """Sends blocked acknowledgment notification."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            result = await notify_proposal_acknowledged(
                asset_fqn="analytics.users",
                consumer_team="finance",
                response="blocked",
                notes="Need 2 weeks to migrate",
            )
            assert result is True
            mock_send.assert_called_once()


class TestNotifyProposalApproved:
    """Tests for notify_proposal_approved."""

    async def test_notify_all_approved(self):
        """Sends all-approved notification."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            result = await notify_proposal_approved(
                asset_fqn="analytics.users",
                version="2.0.0",
            )
            assert result is True
            mock_send.assert_called_once()


class TestNotifyContractPublished:
    """Tests for notify_contract_published."""

    async def test_notify_published(self):
        """Sends contract published notification."""
        with patch("tessera.services.slack.send_slack_message") as mock_send:
            mock_send.return_value = True

            result = await notify_contract_published(
                asset_fqn="warehouse.orders",
                version="1.5.0",
                publisher_team="data-platform",
            )
            assert result is True
            mock_send.assert_called_once()
