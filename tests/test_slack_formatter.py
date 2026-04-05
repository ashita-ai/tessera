"""Tests for Slack Block Kit message formatters."""

from unittest.mock import patch

import pytest

from tessera.services.slack_formatter import (
    format_contract_published,
    format_force_publish,
    format_proposal_acknowledged,
    format_proposal_created,
    format_proposal_resolved,
    format_repo_sync_failed,
    format_test_message,
)


@pytest.fixture(autouse=True)
def _mock_settings():
    """Mock tessera_base_url for all formatter tests."""
    with patch("tessera.services.slack_formatter.settings") as mock_settings:
        mock_settings.tessera_base_url = "https://tessera.example.com"
        yield


class TestFormatProposalCreated:
    """Tests for proposal_created message formatting."""

    def test_basic_format(self):
        """Formats a basic proposal_created message."""
        result = format_proposal_created(
            asset_fqn="analytics.users",
            version="2.0.0",
            producer_team="data-team",
            affected_consumers=["marketing", "finance"],
            breaking_changes=[
                {"path": "$.email", "change": "removed"},
                {"path": "$.name", "change": "type changed"},
            ],
            proposal_id="abc-123",
        )

        assert "text" in result
        assert "blocks" in result
        assert "analytics.users" in result["text"]
        assert "2.0.0" in result["text"]
        assert len(result["blocks"]) >= 4

        # Check header block
        header = result["blocks"][0]
        assert header["type"] == "header"
        assert "Breaking Change" in header["text"]["text"]

        # Check deep link
        actions = [b for b in result["blocks"] if b["type"] == "actions"]
        assert len(actions) >= 1
        assert "abc-123" in actions[0]["elements"][0]["url"]

    def test_truncates_long_lists(self):
        """Truncates breaking changes beyond 5 items."""
        changes = [{"path": f"$.field{i}", "change": "removed"} for i in range(10)]
        result = format_proposal_created(
            asset_fqn="test.asset",
            version="3.0.0",
            producer_team="team",
            affected_consumers=["c1"],
            breaking_changes=changes,
            proposal_id="xyz",
        )

        # The breaking changes section should mention "and X more"
        changes_block = result["blocks"][2]
        assert "...and 5 more" in changes_block["text"]["text"]

    def test_escapes_special_characters(self):
        """Escapes mrkdwn special chars to prevent injection."""
        result = format_proposal_created(
            asset_fqn="test<script>alert(1)</script>",
            version="1.0.0",
            producer_team="team",
            affected_consumers=[],
            breaking_changes=[],
            proposal_id="id",
        )

        # Angle brackets should be escaped
        assert "<script>" not in str(result["blocks"])
        assert "&lt;script&gt;" in str(result["blocks"])


class TestFormatProposalResolved:
    """Tests for proposal_resolved message formatting."""

    def test_approved(self):
        """Formats an approved resolution."""
        result = format_proposal_resolved(
            asset_fqn="analytics.orders",
            version="2.0.0",
            status="approved",
            proposal_id="abc-123",
        )
        assert ":white_check_mark:" in result["text"]
        assert "approved" in result["text"].lower()

    def test_rejected_with_blocker(self):
        """Formats a rejected resolution with blocker details."""
        result = format_proposal_resolved(
            asset_fqn="analytics.orders",
            version="2.0.0",
            status="rejected",
            proposal_id="abc-123",
            blocker_team="finance-team",
            blocker_reason="Migration not complete",
        )
        assert ":no_entry:" in result["text"]
        detail_block = result["blocks"][1]
        assert "finance-team" in detail_block["text"]["text"]
        assert "Migration not complete" in detail_block["text"]["text"]

    def test_expired(self):
        """Formats an expired resolution."""
        result = format_proposal_resolved(
            asset_fqn="analytics.orders",
            version="2.0.0",
            status="expired",
            proposal_id="abc-123",
        )
        assert ":hourglass:" in result["text"]


class TestFormatForcePublish:
    """Tests for force_publish message formatting."""

    def test_basic_format(self):
        """Formats a force publish notification."""
        result = format_force_publish(
            asset_fqn="warehouse.orders",
            version="3.0.0",
            publisher_team="commerce-team",
            publisher_user="jane.doe",
            reason="Hotfix for payment processing bug",
            contract_id="contract-456",
        )

        assert ":red_circle:" in result["text"]
        assert "warehouse.orders" in result["text"]

        detail_block = result["blocks"][1]
        assert "jane.doe" in detail_block["text"]["text"]
        assert "Hotfix" in detail_block["text"]["text"]

    def test_without_optional_fields(self):
        """Formats without publisher_user and reason."""
        result = format_force_publish(
            asset_fqn="test.asset",
            version="2.0.0",
            publisher_team="team",
            publisher_user=None,
            reason=None,
            contract_id="id",
        )
        assert "text" in result
        assert "blocks" in result


class TestFormatContractPublished:
    """Tests for contract_published message formatting."""

    def test_basic_format(self):
        """Formats a contract published notification."""
        result = format_contract_published(
            asset_fqn="analytics.users",
            version="1.5.0",
            publisher_team="data-platform",
        )
        assert "analytics.users" in result["text"]
        assert ":package:" in str(result["blocks"])

    def test_with_deep_link(self):
        """Includes deep link when contract_id provided."""
        result = format_contract_published(
            asset_fqn="test.asset",
            version="1.0.0",
            publisher_team="team",
            contract_id="contract-789",
        )
        actions = [b for b in result["blocks"] if b["type"] == "actions"]
        assert len(actions) == 1
        assert "contract-789" in actions[0]["elements"][0]["url"]


class TestFormatRepoSyncFailed:
    """Tests for repo_sync_failed message formatting."""

    def test_basic_format(self):
        """Formats a repo sync failure notification."""
        result = format_repo_sync_failed(
            repo_name="acme/order-service",
            error_message="Could not parse api/openapi.yaml",
        )
        assert "acme/order-service" in result["text"]
        assert ":x:" in str(result["blocks"])

    def test_with_last_synced(self):
        """Includes last sync time when available."""
        result = format_repo_sync_failed(
            repo_name="repo",
            error_message="parse error",
            last_synced_at="2h ago",
        )
        detail = result["blocks"][1]["text"]["text"]
        assert "2h ago" in detail


class TestFormatProposalAcknowledged:
    """Tests for proposal_acknowledged message formatting."""

    def test_approved(self):
        """Formats an approved acknowledgment."""
        result = format_proposal_acknowledged(
            asset_fqn="analytics.users",
            consumer_team="marketing",
            response="approved",
            proposal_id="abc-123",
        )
        assert "text" in result
        assert "blocks" in result
        assert ":white_check_mark:" in str(result["blocks"])
        assert "marketing" in result["text"]
        assert "approved" in result["text"]
        assert "analytics.users" in result["text"]

    def test_blocked(self):
        """Formats a blocked acknowledgment."""
        result = format_proposal_acknowledged(
            asset_fqn="analytics.orders",
            consumer_team="finance",
            response="blocked",
            proposal_id="xyz-456",
        )
        assert ":no_entry:" in str(result["blocks"])
        assert "blocked" in result["text"]

    def test_migrating(self):
        """Formats a migrating acknowledgment."""
        result = format_proposal_acknowledged(
            asset_fqn="analytics.orders",
            consumer_team="finance",
            response="migrating",
        )
        assert ":hourglass_flowing_sand:" in str(result["blocks"])
        assert "migrating" in result["text"]

    def test_includes_notes(self):
        """Appends a context block when notes are provided."""
        result = format_proposal_acknowledged(
            asset_fqn="analytics.users",
            consumer_team="marketing",
            response="approved",
            notes="Will migrate by Friday",
        )
        context_blocks = [b for b in result["blocks"] if b["type"] == "context"]
        notes_text = str(context_blocks)
        assert "Will migrate by Friday" in notes_text

    def test_includes_deep_link(self):
        """Includes deep link when proposal_id is provided."""
        result = format_proposal_acknowledged(
            asset_fqn="analytics.users",
            consumer_team="marketing",
            response="approved",
            proposal_id="deep-link-id",
        )
        context_blocks = [b for b in result["blocks"] if b["type"] == "context"]
        link_text = str(context_blocks)
        assert "deep-link-id" in link_text
        assert "View proposal" in link_text

    def test_escapes_special_characters(self):
        """Escapes mrkdwn special chars to prevent injection."""
        result = format_proposal_acknowledged(
            asset_fqn="test<script>",
            consumer_team="team<b>",
            response="approved",
        )
        blocks_str = str(result["blocks"])
        assert "<script>" not in blocks_str
        assert "&lt;script&gt;" in blocks_str
        assert "&lt;b&gt;" in blocks_str

    def test_without_optional_fields(self):
        """Formats with only required fields."""
        result = format_proposal_acknowledged(
            asset_fqn="test.asset",
            consumer_team="team",
            response="approved",
        )
        assert "text" in result
        assert "blocks" in result
        # No notes context block, no deep link
        context_blocks = [b for b in result["blocks"] if b["type"] == "context"]
        assert len(context_blocks) == 0


class TestFormatTestMessage:
    """Tests for test message formatting."""

    def test_format(self):
        """Formats a test message."""
        result = format_test_message()
        assert "text" in result
        assert "blocks" in result
        assert "Tessera" in result["text"]
