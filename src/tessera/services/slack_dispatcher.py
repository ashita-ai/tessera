"""Slack notification dispatcher.

Looks up SlackConfig entries for affected teams, filters by event type,
formats the message, and delivers it. This is the main entry point for
all Slack notifications from event hooks.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db.models import SlackConfigDB
from tessera.services.slack_delivery import deliver_slack_message
from tessera.services.slack_formatter import (
    format_contract_published,
    format_force_publish,
    format_proposal_created,
    format_proposal_resolved,
    format_repo_sync_failed,
)

logger = logging.getLogger(__name__)


async def _get_configs_for_teams(
    session: AsyncSession,
    team_ids: list[UUID],
    event_type: str,
) -> list[SlackConfigDB]:
    """Fetch enabled Slack configs for given teams that subscribe to the event type.

    Uses a JSON array containment check to filter by notify_on. For SQLite
    (used in tests), falls back to a LIKE check since SQLite lacks JSON
    array operators.
    """
    if not team_ids:
        return []

    result = await session.execute(
        select(SlackConfigDB).where(
            SlackConfigDB.team_id.in_(team_ids),
            SlackConfigDB.enabled.is_(True),
            SlackConfigDB.deleted_at.is_(None),
        )
    )
    configs = list(result.scalars().all())

    # Filter by notify_on in Python — works consistently across SQLite and PostgreSQL
    # and the volume of configs per team is small enough that this is fine.
    return [c for c in configs if event_type in (c.notify_on or [])]


async def dispatch_slack_notifications(
    session: AsyncSession,
    event_type: str,
    team_ids: list[UUID],
    payload: dict[str, Any],
) -> None:
    """Dispatch Slack notifications to all matching team configs.

    This is a fire-and-forget operation: failures are logged but do not
    propagate exceptions to the caller. The caller's transaction should
    not be affected by notification delivery failures.

    Args:
        session: Database session for looking up configs.
        event_type: One of the SlackNotificationEventType values.
        team_ids: List of team UUIDs to notify.
        payload: Event-specific data passed to the formatter.
    """
    if not settings.slack_enabled:
        return

    if not team_ids:
        return

    try:
        configs = await _get_configs_for_teams(session, team_ids, event_type)
        if not configs:
            return

        formatter = _FORMATTERS.get(event_type)
        if formatter is None:
            logger.warning("No Slack formatter for event type: %s", event_type)
            return

        message = formatter(payload)

        # Deliver to all matching configs concurrently
        tasks = [deliver_slack_message(config, message) for config in configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for config, result in zip(configs, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Slack delivery failed for team %s channel %s: %s",
                    config.team_id,
                    config.channel_id,
                    result,
                )
            elif not result.success:
                logger.warning(
                    "Slack delivery unsuccessful for team %s channel %s: %s",
                    config.team_id,
                    config.channel_id,
                    result.error,
                )
    except Exception:
        logger.error("Slack dispatch failed for event %s", event_type, exc_info=True)


def _format_proposal_created(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapter from event payload to proposal_created formatter."""
    return format_proposal_created(
        asset_fqn=payload["asset_fqn"],
        version=payload["version"],
        producer_team=payload["producer_team"],
        affected_consumers=payload.get("affected_consumers", []),
        breaking_changes=payload.get("breaking_changes", []),
        proposal_id=payload["proposal_id"],
    )


def _format_proposal_resolved(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapter from event payload to proposal_resolved formatter."""
    return format_proposal_resolved(
        asset_fqn=payload["asset_fqn"],
        version=payload.get("version", "unknown"),
        status=payload["status"],
        proposal_id=payload["proposal_id"],
        blocker_team=payload.get("blocker_team"),
        blocker_reason=payload.get("blocker_reason"),
    )


def _format_force_publish(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapter from event payload to force_publish formatter."""
    return format_force_publish(
        asset_fqn=payload["asset_fqn"],
        version=payload["version"],
        publisher_team=payload["publisher_team"],
        publisher_user=payload.get("publisher_user"),
        reason=payload.get("reason"),
        contract_id=payload["contract_id"],
    )


def _format_contract_published(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapter from event payload to contract_published formatter."""
    return format_contract_published(
        asset_fqn=payload["asset_fqn"],
        version=payload["version"],
        publisher_team=payload["publisher_team"],
        change_summary=payload.get("change_summary"),
        contract_id=payload.get("contract_id"),
    )


def _format_repo_sync_failed(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapter from event payload to repo_sync_failed formatter."""
    return format_repo_sync_failed(
        repo_name=payload["repo_name"],
        error_message=payload["error_message"],
        last_synced_at=payload.get("last_synced_at"),
        repo_id=payload.get("repo_id"),
    )


_FORMATTERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "proposal.created": _format_proposal_created,
    "proposal.resolved": _format_proposal_resolved,
    "force.publish": _format_force_publish,
    "contract.published": _format_contract_published,
    "repo.sync_failed": _format_repo_sync_failed,
}
