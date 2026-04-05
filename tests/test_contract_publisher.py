"""Unit tests for contract_publisher internals.

Tests cover: _extract_field_paths composition keyword traversal
(allOf, anyOf, oneOf) and _notify_contract_published dispatch logic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, ContractDB, RegistrationDB, TeamDB
from tessera.services.contract_publisher import (
    ContractPublishingWorkflow,
    _extract_field_paths,
)

# ---------------------------------------------------------------------------
# _extract_field_paths — composition keyword tests
# ---------------------------------------------------------------------------


class TestExtractFieldPathsComposition:
    """Tests for allOf/anyOf/oneOf traversal in _extract_field_paths."""

    def test_allof_merges_field_paths(self):
        """allOf subschemas (OpenAPI inheritance) contribute their fields."""
        schema: dict[str, Any] = {
            "allOf": [
                {
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    }
                },
                {
                    "properties": {
                        "email": {"type": "string"},
                    }
                },
            ]
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.id" in paths
        assert "$.properties.name" in paths
        assert "$.properties.email" in paths

    def test_anyof_merges_field_paths(self):
        """anyOf subschemas (GraphQL unions) contribute their fields."""
        schema: dict[str, Any] = {
            "anyOf": [
                {"properties": {"width": {"type": "number"}}},
                {"properties": {"radius": {"type": "number"}}},
            ]
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.width" in paths
        assert "$.properties.radius" in paths

    def test_oneof_merges_field_paths(self):
        """oneOf subschemas contribute their fields."""
        schema: dict[str, Any] = {
            "oneOf": [
                {"properties": {"card_number": {"type": "string"}}},
                {"properties": {"account_id": {"type": "string"}}},
            ]
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.card_number" in paths
        assert "$.properties.account_id" in paths

    def test_composition_combined_with_top_level_properties(self):
        """Composition keywords and top-level properties are both discovered."""
        schema: dict[str, Any] = {
            "properties": {
                "status": {"type": "string"},
            },
            "allOf": [
                {"properties": {"created_at": {"type": "string"}}},
            ],
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.status" in paths
        assert "$.properties.created_at" in paths

    def test_nested_composition_in_object_property(self):
        """Composition keywords inside a nested object property are traversed."""
        schema: dict[str, Any] = {
            "properties": {
                "metadata": {
                    "type": "object",
                    "properties": {
                        "tags": {
                            "allOf": [
                                {"properties": {"key": {"type": "string"}}},
                                {"properties": {"value": {"type": "string"}}},
                            ]
                        }
                    },
                }
            }
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.metadata" in paths

    def test_composition_skips_non_dict_subschemas(self):
        """Non-dict entries in allOf/anyOf/oneOf are safely skipped."""
        schema: dict[str, Any] = {
            "allOf": [
                {"properties": {"id": {"type": "integer"}}},
                True,  # boolean schema (valid JSON Schema, not a dict)
                "not-a-schema",
            ]
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.id" in paths
        assert len(paths) == 1

    def test_empty_composition_keywords(self):
        """Empty allOf/anyOf/oneOf arrays produce no extra paths."""
        schema: dict[str, Any] = {
            "allOf": [],
            "anyOf": [],
            "oneOf": [],
            "properties": {"id": {"type": "integer"}},
        }
        paths = _extract_field_paths(schema)
        assert paths == {"$.properties.id"}

    def test_overlapping_fields_across_composition_branches(self):
        """Duplicate field names across branches are deduplicated (set)."""
        schema: dict[str, Any] = {
            "allOf": [
                {"properties": {"id": {"type": "integer"}}},
                {"properties": {"id": {"type": "string"}}},
            ]
        }
        paths = _extract_field_paths(schema)
        assert "$.properties.id" in paths
        assert len(paths) == 1


# ---------------------------------------------------------------------------
# _notify_contract_published
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyContractPublished:
    """Tests for the _notify_contract_published dispatch method."""

    def _make_workflow(
        self,
        session: AsyncMock,
        asset: AssetDB | None = None,
        published_by: Any = None,
    ) -> ContractPublishingWorkflow:
        """Build a workflow with mocked internals."""
        wf = object.__new__(ContractPublishingWorkflow)
        wf.session = session
        wf.asset = asset or MagicMock(spec=AssetDB, id=uuid4(), fqn="test.asset")
        wf.published_by = published_by or uuid4()
        return wf

    @patch(
        "tessera.services.contract_publisher.dispatch_slack_notifications", new_callable=AsyncMock
    )
    @patch("tessera.services.contract_publisher.send_contract_published", new_callable=AsyncMock)
    async def test_sends_webhook_and_slack_to_consumers(
        self, mock_webhook: AsyncMock, mock_slack: AsyncMock
    ):
        """Notifies via webhook and dispatches Slack to consumer teams."""
        team_id = uuid4()
        publisher_team = MagicMock(spec=TeamDB, name="publisher-team")
        consumer_reg = MagicMock(spec=RegistrationDB, team_id=uuid4())

        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=publisher_team)

        contract = MagicMock(spec=ContractDB, id=uuid4(), version="2.0.0")

        wf = self._make_workflow(session, published_by=team_id)
        wf._get_impacted_consumers = AsyncMock(return_value=[consumer_reg])

        await wf._notify_contract_published(contract)

        mock_webhook.assert_awaited_once()
        webhook_kwargs = mock_webhook.call_args.kwargs
        assert webhook_kwargs["contract_id"] == contract.id
        assert webhook_kwargs["version"] == "2.0.0"

        mock_slack.assert_awaited_once()
        slack_kwargs = mock_slack.call_args.kwargs
        assert slack_kwargs["event_type"] == "contract.published"
        assert slack_kwargs["team_ids"] == [consumer_reg.team_id]
        assert slack_kwargs["payload"]["version"] == "2.0.0"

    @patch(
        "tessera.services.contract_publisher.dispatch_slack_notifications", new_callable=AsyncMock
    )
    @patch("tessera.services.contract_publisher.send_contract_published", new_callable=AsyncMock)
    async def test_no_slack_when_no_consumers(self, mock_webhook: AsyncMock, mock_slack: AsyncMock):
        """Slack is not dispatched when there are no impacted consumers."""
        publisher_team = MagicMock(spec=TeamDB, name="solo-team")
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=publisher_team)

        contract = MagicMock(spec=ContractDB, id=uuid4(), version="1.0.0")

        wf = self._make_workflow(session)
        wf._get_impacted_consumers = AsyncMock(return_value=[])

        await wf._notify_contract_published(contract)

        mock_webhook.assert_awaited_once()
        mock_slack.assert_not_awaited()

    @patch(
        "tessera.services.contract_publisher.dispatch_slack_notifications", new_callable=AsyncMock
    )
    @patch("tessera.services.contract_publisher.send_contract_published", new_callable=AsyncMock)
    async def test_unknown_publisher_team_fallback(
        self, mock_webhook: AsyncMock, mock_slack: AsyncMock
    ):
        """Publisher team name falls back to 'unknown' when team not found."""
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=None)  # Team not found

        consumer_reg = MagicMock(spec=RegistrationDB, team_id=uuid4())
        contract = MagicMock(spec=ContractDB, id=uuid4(), version="3.0.0")

        wf = self._make_workflow(session)
        wf._get_impacted_consumers = AsyncMock(return_value=[consumer_reg])

        await wf._notify_contract_published(contract)

        webhook_kwargs = mock_webhook.call_args.kwargs
        assert webhook_kwargs["producer_team_name"] == "unknown"

        slack_kwargs = mock_slack.call_args.kwargs
        assert slack_kwargs["payload"]["publisher_team"] == "unknown"
