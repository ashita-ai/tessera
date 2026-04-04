"""Slack message delivery service.

Sends formatted Block Kit payloads to Slack via incoming webhook or bot token.
Reuses SSRF protection from the webhook infrastructure.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from tessera.db.models import SlackConfigDB
from tessera.services.webhooks import validate_webhook_url

logger = logging.getLogger(__name__)

# Slack API endpoint for bot-token-based delivery
_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Timeouts (seconds)
_DELIVERY_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Result of a Slack message delivery attempt."""

    success: bool
    error: str | None = None


async def deliver_slack_message(
    config: SlackConfigDB,
    payload: dict[str, Any],
) -> DeliveryResult:
    """Send a formatted message to Slack using the config's auth method.

    Chooses between webhook URL and bot token delivery based on which
    field is set on the config. Applies SSRF protection to webhook URLs.

    Args:
        config: The Slack config with webhook_url or bot_token.
        payload: Dict with 'text' (fallback) and 'blocks' (Block Kit).

    Returns:
        DeliveryResult indicating success or failure with error detail.
    """
    if config.webhook_url:
        return await _deliver_via_webhook(config.webhook_url, payload)
    elif config.bot_token:
        return await _deliver_via_bot_token(config.bot_token, config.channel_id, payload)
    else:
        return DeliveryResult(success=False, error="No webhook_url or bot_token configured")


async def _deliver_via_webhook(
    webhook_url: str,
    payload: dict[str, Any],
) -> DeliveryResult:
    """Deliver a message via Slack incoming webhook URL.

    Validates the URL with SSRF protection before sending.
    """
    # SSRF protection — reuse the webhook infrastructure's validation
    is_valid, error_msg = await validate_webhook_url(webhook_url)
    if not is_valid:
        return DeliveryResult(success=False, error=f"SSRF validation failed: {error_msg}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                timeout=_DELIVERY_TIMEOUT,
            )
            if response.status_code == 200 and response.text == "ok":
                return DeliveryResult(success=True)
            else:
                return DeliveryResult(
                    success=False,
                    error=f"Slack webhook returned {response.status_code}: {response.text[:200]}",
                )
    except httpx.TimeoutException:
        return DeliveryResult(success=False, error="Slack webhook request timed out")
    except Exception as e:
        logger.error("Slack webhook delivery failed: %s", e, exc_info=True)
        return DeliveryResult(success=False, error="Webhook delivery failed — check server logs")


async def _deliver_via_bot_token(
    bot_token: str,
    channel_id: str,
    payload: dict[str, Any],
) -> DeliveryResult:
    """Deliver a message via Slack Bot Token (chat.postMessage API).

    Uses the Slack Web API which supports richer interactions than webhooks.
    """
    try:
        body: dict[str, Any] = {
            "channel": channel_id,
            "text": payload.get("text", ""),
        }
        if "blocks" in payload:
            body["blocks"] = payload["blocks"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                _SLACK_POST_MESSAGE_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=_DELIVERY_TIMEOUT,
            )

            if response.status_code != 200:
                return DeliveryResult(
                    success=False,
                    error=f"Slack API returned HTTP {response.status_code}",
                )

            # httpx response.json() is synchronous, not a coroutine
            data: dict[str, Any] = response.json()
            if data.get("ok"):
                return DeliveryResult(success=True)
            else:
                return DeliveryResult(
                    success=False,
                    error=f"Slack API error: {data.get('error', 'unknown')}",
                )
    except httpx.TimeoutException:
        return DeliveryResult(success=False, error="Slack API request timed out")
    except Exception as e:
        logger.error("Slack bot token delivery failed: %s", e, exc_info=True)
        return DeliveryResult(success=False, error="Bot token delivery failed — check server logs")
