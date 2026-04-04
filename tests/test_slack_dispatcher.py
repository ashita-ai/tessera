"""Tests for Slack notification dispatcher."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import SlackConfigDB, TeamDB
from tessera.services.slack_dispatcher import dispatch_slack_notifications

pytestmark = pytest.mark.asyncio


async def _create_team_and_config(
    session: AsyncSession,
    team_name: str = "test-team",
    channel_id: str = "CABC123",
    notify_on: list[str] | None = None,
    enabled: bool = True,
) -> tuple[TeamDB, SlackConfigDB]:
    """Create a team and Slack config in the test DB."""
    team = TeamDB(name=team_name)
    session.add(team)
    await session.flush()
    await session.refresh(team)

    config = SlackConfigDB(
        team_id=team.id,
        channel_id=channel_id,
        webhook_url="https://hooks.slack.com/services/T/B/x",
        notify_on=notify_on or ["proposal_created", "proposal_resolved", "force_publish"],
        enabled=enabled,
    )
    session.add(config)
    await session.flush()
    await session.refresh(config)

    return team, config


class TestDispatchSlackNotifications:
    """Tests for the dispatch_slack_notifications function."""

    async def test_dispatches_to_matching_team(self, test_session):
        """Sends notification to team with matching event type in notify_on."""
        team, config = await _create_team_and_config(test_session)

        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True
            mock_settings.tessera_base_url = "https://test.example.com"
            mock_deliver.return_value = AsyncMock(success=True)

            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[team.id],
                payload={
                    "asset_fqn": "analytics.users",
                    "version": "2.0.0",
                    "producer_team": "data-team",
                    "affected_consumers": ["marketing"],
                    "breaking_changes": [{"path": "$.email", "change": "removed"}],
                    "proposal_id": str(uuid4()),
                },
            )

            mock_deliver.assert_called_once()

    async def test_skips_when_slack_disabled(self, test_session):
        """Does nothing when slack_enabled is False."""
        team, _config = await _create_team_and_config(test_session)

        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = False

            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[team.id],
                payload={},
            )

            mock_deliver.assert_not_called()

    async def test_skips_disabled_config(self, test_session):
        """Does not send to disabled configs."""
        team, _config = await _create_team_and_config(test_session, enabled=False)

        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True
            mock_settings.tessera_base_url = "https://test.example.com"

            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[team.id],
                payload={
                    "asset_fqn": "test",
                    "version": "1.0.0",
                    "producer_team": "team",
                    "affected_consumers": [],
                    "breaking_changes": [],
                    "proposal_id": str(uuid4()),
                },
            )

            mock_deliver.assert_not_called()

    async def test_respects_notify_on_filter(self, test_session):
        """Only dispatches for event types in the config's notify_on."""
        team, _config = await _create_team_and_config(
            test_session,
            notify_on=["force_publish"],  # Only subscribed to force_publish
        )

        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True
            mock_settings.tessera_base_url = "https://test.example.com"

            # Send proposal_created event — should be skipped
            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[team.id],
                payload={
                    "asset_fqn": "test",
                    "version": "1.0.0",
                    "producer_team": "team",
                    "affected_consumers": [],
                    "breaking_changes": [],
                    "proposal_id": str(uuid4()),
                },
            )

            mock_deliver.assert_not_called()

    async def test_skips_when_no_teams(self, test_session):
        """Does nothing when team_ids list is empty."""
        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True

            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[],
                payload={},
            )

            mock_deliver.assert_not_called()

    async def test_no_config_for_team_silently_skipped(self, test_session):
        """No error when team has no Slack config."""
        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True
            mock_settings.tessera_base_url = "https://test.example.com"

            # Use a UUID that has no config
            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[uuid4()],
                payload={},
            )

            mock_deliver.assert_not_called()

    async def test_delivery_failure_does_not_propagate(self, test_session):
        """Delivery failures are logged but don't raise to caller."""
        team, _config = await _create_team_and_config(test_session)

        with (
            patch("tessera.services.slack_dispatcher.settings") as mock_settings,
            patch(
                "tessera.services.slack_dispatcher.deliver_slack_message",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            mock_settings.slack_enabled = True
            mock_settings.tessera_base_url = "https://test.example.com"
            mock_deliver.side_effect = Exception("Network failure")

            # Should not raise
            await dispatch_slack_notifications(
                session=test_session,
                event_type="proposal_created",
                team_ids=[team.id],
                payload={
                    "asset_fqn": "test",
                    "version": "1.0.0",
                    "producer_team": "team",
                    "affected_consumers": [],
                    "breaking_changes": [],
                    "proposal_id": str(uuid4()),
                },
            )
