"""Slack notification service."""

import logging
from typing import Any

import httpx

from tessera.config import settings

logger = logging.getLogger(__name__)


async def send_slack_message(
    text: str,
    blocks: list[dict[str, Any]] | None = None,
) -> bool:
    """Send a message to Slack via webhook.

    Args:
        text: Fallback text (shown in notifications)
        blocks: Optional Slack Block Kit blocks for rich formatting

    Returns:
        True if sent successfully, False otherwise
    """
    if not settings.slack_webhook_url:
        logger.debug("Slack webhook URL not configured, skipping notification")
        return False

    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.slack_webhook_url,
                json=payload,
                timeout=10.0,
            )
            if response.status_code == 200 and response.text == "ok":
                logger.debug("Slack notification sent successfully")
                return True
            else:
                logger.warning(f"Slack notification failed: {response.status_code} {response.text}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


async def notify_proposal_created(
    asset_fqn: str,
    version: str,
    producer_team: str,
    affected_consumers: list[str],
    breaking_changes: list[dict[str, Any]],
) -> bool:
    """Notify Slack when a breaking change proposal is created."""
    changes_text = "\n".join(
        f"• `{c.get('path', 'unknown')}`: {c.get('change', 'changed')}"
        for c in breaking_changes[:5]
    )
    if len(breaking_changes) > 5:
        changes_text += f"\n• _...and {len(breaking_changes) - 5} more_"

    consumers_text = ", ".join(affected_consumers[:5])
    if len(affected_consumers) > 5:
        consumers_text += f", +{len(affected_consumers) - 5} more"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":warning: Breaking Change Proposed",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Asset:*\n`{asset_fqn}`"},
                {"type": "mrkdwn", "text": f"*Version:*\n`{version}`"},
                {"type": "mrkdwn", "text": f"*Producer:*\n{producer_team}"},
                {"type": "mrkdwn", "text": f"*Affected:*\n{consumers_text}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Breaking Changes:*\n{changes_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Consumers must acknowledge before this change can ship.",
                }
            ],
        },
    ]

    return await send_slack_message(
        text=f"Breaking change proposed for {asset_fqn} v{version}",
        blocks=blocks,
    )


async def notify_proposal_acknowledged(
    asset_fqn: str,
    consumer_team: str,
    response: str,
    notes: str | None = None,
) -> bool:
    """Notify Slack when a consumer acknowledges a proposal."""
    emoji = ":white_check_mark:" if response == "approved" else ":no_entry:"
    status = "approved" if response == "approved" else "blocked"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{consumer_team}* {status} the breaking change for `{asset_fqn}`",
            },
        },
    ]

    if notes:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{notes}_"}],
            }
        )

    return await send_slack_message(
        text=f"{consumer_team} {status} breaking change for {asset_fqn}",
        blocks=blocks,
    )


async def notify_proposal_approved(
    asset_fqn: str,
    version: str,
) -> bool:
    """Notify Slack when all consumers have approved a proposal."""
    msg = f":tada: *All consumers approved!* Breaking change for `{asset_fqn}` "
    msg += f"v`{version}` is ready to ship."
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": msg},
        },
    ]

    return await send_slack_message(
        text=f"All consumers approved breaking change for {asset_fqn} v{version}",
        blocks=blocks,
    )


async def notify_contract_published(
    asset_fqn: str,
    version: str,
    publisher_team: str,
) -> bool:
    """Notify Slack when a new contract version is published."""
    msg = f":package: *Contract Published:* `{asset_fqn}` v`{version}` by {publisher_team}"
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": msg},
        },
    ]

    return await send_slack_message(
        text=f"Contract published: {asset_fqn} v{version}",
        blocks=blocks,
    )
