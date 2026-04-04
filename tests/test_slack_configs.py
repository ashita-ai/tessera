"""Tests for Slack config CRUD API and notification pipeline."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────


async def _create_team(client, name: str = "test-team") -> dict:
    resp = await client.post("/api/v1/teams", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _slack_config_body(
    team_id: str,
    channel_id: str = "CABC123",
    webhook_url: str = "https://hooks.slack.com/services/T/B/x",
    **overrides,
) -> dict:
    body = {
        "team_id": team_id,
        "channel_id": channel_id,
        "webhook_url": webhook_url,
        "notify_on": ["proposal_created", "force_publish"],
    }
    body.update(overrides)
    return body


# ── Config CRUD Tests ────────────────────────────────────────────────


class TestCreateSlackConfig:
    """POST /api/v1/slack/configs"""

    async def test_create_config_with_webhook(self, client):
        """Creates a Slack config with a webhook URL."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"])

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            resp = await client.post("/api/v1/slack/configs", json=body)

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["team_id"] == team["id"]
        assert data["channel_id"] == "CABC123"
        assert data["has_webhook_url"] is True
        assert data["has_bot_token"] is False
        assert data["enabled"] is True
        assert "proposal_created" in data["notify_on"]
        # Secrets should not be in response
        assert "webhook_url" not in data
        assert "bot_token" not in data

    async def test_create_config_with_bot_token(self, client):
        """Creates a Slack config with a bot token."""
        team = await _create_team(client)
        body = _slack_config_body(
            team["id"],
            webhook_url=None,
            bot_token="xoxb-test-token-123",
        )
        # Remove webhook_url since we're using bot_token
        del body["webhook_url"]
        body["bot_token"] = "xoxb-test-token-123"

        resp = await client.post("/api/v1/slack/configs", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["has_bot_token"] is True
        assert data["has_webhook_url"] is False

    async def test_create_config_requires_auth_method(self, client):
        """Rejects config with neither webhook_url nor bot_token."""
        team = await _create_team(client)
        body = {
            "team_id": team["id"],
            "channel_id": "CABC123",
            "notify_on": ["proposal_created"],
        }
        resp = await client.post("/api/v1/slack/configs", json=body)
        assert resp.status_code == 422

    async def test_create_config_rejects_both_auth_methods(self, client):
        """Rejects config with both webhook_url and bot_token."""
        team = await _create_team(client)
        body = _slack_config_body(
            team["id"],
            bot_token="xoxb-test-token",
        )
        resp = await client.post("/api/v1/slack/configs", json=body)
        assert resp.status_code == 422

    async def test_create_config_validates_channel_id(self, client):
        """Rejects invalid Slack channel ID format."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"], channel_id="invalid-channel")
        resp = await client.post("/api/v1/slack/configs", json=body)
        assert resp.status_code == 422

    async def test_create_config_validates_event_types(self, client):
        """Rejects invalid event types in notify_on."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"])
        body["notify_on"] = ["proposal_created", "nonexistent_event"]
        resp = await client.post("/api/v1/slack/configs", json=body)
        assert resp.status_code == 422

    async def test_create_config_validates_team_exists(self, client):
        """Returns 404 when team doesn't exist."""
        body = _slack_config_body(str(uuid4()))

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            resp = await client.post("/api/v1/slack/configs", json=body)

        assert resp.status_code == 404

    async def test_create_config_duplicate(self, client):
        """Returns 409 when config already exists for team+channel."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"])

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            resp1 = await client.post("/api/v1/slack/configs", json=body)
            assert resp1.status_code == 201
            resp2 = await client.post("/api/v1/slack/configs", json=body)
            assert resp2.status_code == 409

    async def test_create_config_ssrf_validation(self, client):
        """Rejects webhook URLs that fail SSRF validation."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"], webhook_url="http://169.254.169.254/metadata")

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (False, "IP address is not global")
            resp = await client.post("/api/v1/slack/configs", json=body)

        assert resp.status_code == 400
        assert "Invalid webhook URL" in resp.json()["error"]["message"]


class TestListSlackConfigs:
    """GET /api/v1/slack/configs"""

    async def test_list_configs(self, client):
        """Lists all Slack configs."""
        team = await _create_team(client)
        body = _slack_config_body(team["id"])

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            await client.post("/api/v1/slack/configs", json=body)

        resp = await client.get("/api/v1/slack/configs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["results"]) >= 1

    async def test_list_configs_by_team(self, client):
        """Filters configs by team_id."""
        team1 = await _create_team(client, "team-1")
        team2 = await _create_team(client, "team-2")

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team1["id"], channel_id="CAAA111"),
            )
            await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team2["id"], channel_id="CBBB222"),
            )

        resp = await client.get(f"/api/v1/slack/configs?team_id={team1['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["team_id"] == team1["id"]

    async def test_list_configs_by_enabled(self, client):
        """Filters configs by enabled status."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            r1 = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"], channel_id="CAAA111"),
            )
            assert r1.status_code == 201
            r2 = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"], channel_id="CBBB222", enabled=False),
            )
            assert r2.status_code == 201

        resp = await client.get("/api/v1/slack/configs?enabled=true")
        assert resp.status_code == 200
        data = resp.json()
        for cfg in data["results"]:
            assert cfg["enabled"] is True


class TestGetSlackConfig:
    """GET /api/v1/slack/configs/{id}"""

    async def test_get_config(self, client):
        """Gets a Slack config by ID."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/slack/configs/{config_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == config_id

    async def test_get_config_not_found(self, client):
        """Returns 404 for non-existent config."""
        resp = await client.get(f"/api/v1/slack/configs/{uuid4()}")
        assert resp.status_code == 404


class TestUpdateSlackConfig:
    """PATCH /api/v1/slack/configs/{id}"""

    async def test_update_notify_on(self, client):
        """Updates notify_on event types."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/slack/configs/{config_id}",
            json={"notify_on": ["contract_published", "repo_sync_failed"]},
        )
        assert resp.status_code == 200
        assert resp.json()["notify_on"] == ["contract_published", "repo_sync_failed"]

    async def test_update_enabled(self, client):
        """Toggles enabled flag."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/slack/configs/{config_id}",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_update_webhook_url_clears_bot_token(self, client):
        """Setting webhook_url clears bot_token."""
        team = await _create_team(client)

        # Create with bot token
        create_resp = await client.post(
            "/api/v1/slack/configs",
            json=_slack_config_body(
                team["id"],
                webhook_url=None,
                bot_token="xoxb-initial-token",
            ),
        )
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]
        assert create_resp.json()["has_bot_token"] is True

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            resp = await client.patch(
                f"/api/v1/slack/configs/{config_id}",
                json={"webhook_url": "https://hooks.slack.com/services/T/B/new"},
            )

        assert resp.status_code == 200
        assert resp.json()["has_webhook_url"] is True
        assert resp.json()["has_bot_token"] is False

    async def test_update_rejects_both_auth_methods(self, client):
        """Rejects update with both webhook_url and bot_token."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/slack/configs/{config_id}",
            json={
                "webhook_url": "https://hooks.slack.com/services/T/B/new",
                "bot_token": "xoxb-also-this",
            },
        )
        assert resp.status_code == 422

    async def test_update_not_found(self, client):
        """Returns 404 for non-existent config."""
        resp = await client.patch(
            f"/api/v1/slack/configs/{uuid4()}",
            json={"enabled": False},
        )
        assert resp.status_code == 404


class TestDeleteSlackConfig:
    """DELETE /api/v1/slack/configs/{id}"""

    async def test_delete_config(self, client):
        """Deletes a Slack config."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/slack/configs/{config_id}")
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(f"/api/v1/slack/configs/{config_id}")
        assert get_resp.status_code == 404

    async def test_delete_not_found(self, client):
        """Returns 404 for non-existent config."""
        resp = await client.delete(f"/api/v1/slack/configs/{uuid4()}")
        assert resp.status_code == 404


class TestTestSlackConfig:
    """POST /api/v1/slack/configs/{id}/test"""

    async def test_send_test_message_success(self, client):
        """Sends a test message and returns success."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]

        with patch("tessera.api.slack_configs.deliver_slack_message", new_callable=AsyncMock) as m:
            from tessera.services.slack_delivery import DeliveryResult

            m.return_value = DeliveryResult(success=True)
            resp = await client.post(f"/api/v1/slack/configs/{config_id}/test")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_send_test_message_failure(self, client):
        """Returns failure details when test message fails."""
        team = await _create_team(client)

        with patch("tessera.api.slack_configs.validate_webhook_url", new_callable=AsyncMock) as m:
            m.return_value = (True, "")
            create_resp = await client.post(
                "/api/v1/slack/configs",
                json=_slack_config_body(team["id"]),
            )

        config_id = create_resp.json()["id"]

        with patch("tessera.api.slack_configs.deliver_slack_message", new_callable=AsyncMock) as m:
            from tessera.services.slack_delivery import DeliveryResult

            m.return_value = DeliveryResult(success=False, error="channel_not_found")
            resp = await client.post(f"/api/v1/slack/configs/{config_id}/test")

        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert resp.json()["error"] == "channel_not_found"

    async def test_send_test_message_not_found(self, client):
        """Returns 404 for non-existent config."""
        resp = await client.post(f"/api/v1/slack/configs/{uuid4()}/test")
        assert resp.status_code == 404
