"""Slack Block Kit message formatters.

Pure functions that transform Tessera event data into Slack Block Kit payloads.
No side effects, no HTTP calls — just data transformation.
"""

from typing import Any

from tessera.config import settings

# Slack mrkdwn special characters that need escaping
_MRKDWN_ESCAPE = str.maketrans({"<": "&lt;", ">": "&gt;", "&": "&amp;"})


def _escape(text: str) -> str:
    """Escape text for Slack mrkdwn to prevent injection."""
    return text.translate(_MRKDWN_ESCAPE)


def _truncate_list(
    items: list[str],
    max_items: int = 5,
) -> str:
    """Format a list of strings, truncating if needed."""
    shown = items[:max_items]
    result = "\n".join(f"• {item}" for item in shown)
    remaining = len(items) - max_items
    if remaining > 0:
        result += f"\n• _...and {remaining} more_"
    return result


def _base_url() -> str:
    """Get the Tessera base URL for deep links."""
    return settings.tessera_base_url.rstrip("/")


def format_proposal_created(
    asset_fqn: str,
    version: str,
    producer_team: str,
    affected_consumers: list[str],
    breaking_changes: list[dict[str, Any]],
    proposal_id: str,
) -> dict[str, Any]:
    """Format a proposal_created event as a Slack Block Kit message.

    Args:
        asset_fqn: Fully qualified asset name.
        version: Proposed version.
        producer_team: Name of the producing team.
        affected_consumers: Names of affected consumer teams.
        breaking_changes: List of breaking change dicts with 'path' and 'change' keys.
        proposal_id: UUID of the proposal (as string) for deep linking.

    Returns:
        Dict with 'text' (fallback) and 'blocks' (Block Kit payload).
    """
    changes_text = _truncate_list(
        [
            f"`{_escape(c.get('path', 'unknown'))}`: {_escape(c.get('change', 'changed'))}"
            for c in breaking_changes
        ]
    )

    consumers_text = ", ".join(_escape(c) for c in affected_consumers[:5])
    if len(affected_consumers) > 5:
        consumers_text += f", +{len(affected_consumers) - 5} more"

    base = _base_url()
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":warning: Breaking Change Proposal",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Asset:*\n`{_escape(asset_fqn)}`"},
                {"type": "mrkdwn", "text": f"*Version:*\n`{_escape(version)}`"},
                {"type": "mrkdwn", "text": f"*Producer:*\n{_escape(producer_team)}"},
                {"type": "mrkdwn", "text": f"*Affected:*\n{consumers_text}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{len(breaking_changes)} breaking change(s):*\n{changes_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Proposal", "emoji": True},
                    "url": f"{base}/proposals/{proposal_id}",
                },
            ],
        },
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

    return {
        "text": f":warning: Breaking change proposed for {asset_fqn} v{version}",
        "blocks": blocks,
    }


def format_proposal_resolved(
    asset_fqn: str,
    version: str,
    status: str,
    proposal_id: str,
    blocker_team: str | None = None,
    blocker_reason: str | None = None,
) -> dict[str, Any]:
    """Format a proposal_resolved event as a Slack Block Kit message.

    Args:
        asset_fqn: Fully qualified asset name.
        version: Version in the proposal.
        status: Resolution status (approved, rejected, expired, withdrawn).
        proposal_id: UUID of the proposal for deep linking.
        blocker_team: Team that blocked (if rejected).
        blocker_reason: Reason for blocking (if rejected).

    Returns:
        Dict with 'text' and 'blocks'.
    """
    base = _base_url()

    if status == "approved":
        emoji = ":white_check_mark:"
        title = "Proposal Approved"
        detail = (
            f"`{_escape(asset_fqn)}` v`{_escape(version)}`\nAll consumers acknowledged. Publishing."
        )
        color_text = "approved"
    elif status == "rejected":
        emoji = ":no_entry:"
        title = "Proposal Blocked"
        detail = f"`{_escape(asset_fqn)}` v`{_escape(version)}`"
        if blocker_team:
            detail += f"\nBlocked by: *{_escape(blocker_team)}*"
        if blocker_reason:
            detail += f'\nReason: "{_escape(blocker_reason)}"'
        color_text = "blocked"
    elif status == "expired":
        emoji = ":hourglass:"
        title = "Proposal Expired"
        detail = (
            f"`{_escape(asset_fqn)}` v`{_escape(version)}`\n"
            "Proposal expired without full consumer acknowledgment."
        )
        color_text = "expired"
    else:
        emoji = ":information_source:"
        title = f"Proposal {_escape(status.title())}"
        detail = f"`{_escape(asset_fqn)}` v`{_escape(version)}`"
        color_text = status

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Proposal", "emoji": True},
                    "url": f"{base}/proposals/{proposal_id}",
                },
            ],
        },
    ]

    return {
        "text": f"{emoji} Proposal {color_text} for {asset_fqn} v{version}",
        "blocks": blocks,
    }


def format_force_publish(
    asset_fqn: str,
    version: str,
    publisher_team: str,
    publisher_user: str | None,
    reason: str | None,
    contract_id: str,
) -> dict[str, Any]:
    """Format a force_publish event as a Slack Block Kit message.

    Args:
        asset_fqn: Fully qualified asset name.
        version: Published version.
        publisher_team: Team that force-published.
        publisher_user: Individual who force-published (optional).
        reason: Reason for force publishing (optional).
        contract_id: UUID of the contract for deep linking.

    Returns:
        Dict with 'text' and 'blocks'.
    """
    base = _base_url()

    publisher_text = _escape(publisher_team)
    if publisher_user:
        publisher_text = f"*{_escape(publisher_user)}* ({publisher_text})"

    detail = (
        f"`{_escape(asset_fqn)}` v`{_escape(version)}`\n"
        "Published without full consumer acknowledgment."
    )
    if reason:
        detail += f'\n\nReason: "{_escape(reason)}"'
    detail += f"\nPublished by: {publisher_text}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":red_circle: Force Publish (Breaking Change)",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Contract", "emoji": True},
                    "url": f"{base}/contracts/{contract_id}",
                },
            ],
        },
    ]

    return {
        "text": f":red_circle: Force publish: {asset_fqn} v{version} by {publisher_team}",
        "blocks": blocks,
    }


def format_contract_published(
    asset_fqn: str,
    version: str,
    publisher_team: str,
    change_summary: str | None = None,
    contract_id: str | None = None,
) -> dict[str, Any]:
    """Format a contract_published event as a Slack Block Kit message.

    Args:
        asset_fqn: Fully qualified asset name.
        version: Published version.
        publisher_team: Team that published.
        change_summary: Brief summary of what changed (optional).
        contract_id: UUID of the contract for deep linking (optional).

    Returns:
        Dict with 'text' and 'blocks'.
    """
    base = _base_url()

    detail = (
        f":package: *Contract Published:* `{_escape(asset_fqn)}` "
        f"v`{_escape(version)}` by {_escape(publisher_team)}"
    )
    if change_summary:
        detail += f"\n{_escape(change_summary)}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail},
        },
    ]

    if contract_id:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Contract", "emoji": True},
                        "url": f"{base}/contracts/{contract_id}",
                    },
                ],
            }
        )

    return {
        "text": f"Contract published: {asset_fqn} v{version}",
        "blocks": blocks,
    }


def format_repo_sync_failed(
    repo_name: str,
    error_message: str,
    last_synced_at: str | None = None,
    repo_id: str | None = None,
) -> dict[str, Any]:
    """Format a repo_sync_failed event as a Slack Block Kit message.

    Args:
        repo_name: Name of the repository.
        error_message: Error message from the sync failure.
        last_synced_at: Human-readable last successful sync time (optional).
        repo_id: UUID of the repo for deep linking (optional).

    Returns:
        Dict with 'text' and 'blocks'.
    """
    base = _base_url()

    detail = f'*{_escape(repo_name)}* failed to sync from git\nError: "{_escape(error_message)}"'
    if last_synced_at:
        detail += f"\nLast successful sync: {_escape(last_synced_at)}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":x: Repo Sync Failed",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail},
        },
    ]

    if repo_id:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Repo", "emoji": True},
                        "url": f"{base}/repos/{repo_id}",
                    },
                ],
            }
        )

    return {
        "text": f"Repo sync failed: {repo_name}",
        "blocks": blocks,
    }


def format_test_message() -> dict[str, Any]:
    """Format a test message to verify Slack config works.

    Returns:
        Dict with 'text' and 'blocks'.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":white_check_mark: *Tessera Slack Integration Test*\n"
                    "This channel is now connected to Tessera notifications."
                ),
            },
        },
    ]

    return {
        "text": "Tessera Slack integration test — this channel is connected.",
        "blocks": blocks,
    }
