"""Tests for the Tessera CLI."""

import json
import re
from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from tessera.cli import app

runner = CliRunner()


def clean_ansi(text: str) -> str:
    """Strip ANSI color codes from string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestVersion:
    """Tests for the version command."""

    def test_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "tessera 0.1.0" in clean_ansi(result.output)


class TestTeamCommands:
    """Tests for team subcommands."""

    def test_team_create_success(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "team-123",
            "name": "Data Platform",
            "created_at": "2024-01-01T00:00:00Z",
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "create", "Data Platform"])
            assert result.exit_code == 0
            assert "Created team:" in result.output
            assert "Data Platform" in result.output

    def test_team_create_with_metadata(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "team-123",
            "name": "Data Platform",
            "metadata": {"slack": "#data-platform"},
            "created_at": "2024-01-01T00:00:00Z",
        }

        with patch("tessera.cli.make_request", return_value=mock_response) as mock_req:
            result = runner.invoke(
                app, ["team", "create", "Data Platform", "-m", '{"slack": "#data-platform"}']
            )
            assert result.exit_code == 0
            # Verify metadata was passed
            call_args = mock_req.call_args
            assert call_args[1]["json_data"]["metadata"] == {"slack": "#data-platform"}

    def test_team_list_empty(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "list"])
            assert result.exit_code == 0
            assert "No teams found" in result.output

    def test_team_list_with_teams(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "team-1", "name": "Team A", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "team-2", "name": "Team B", "created_at": "2024-01-02T00:00:00Z"},
        ]

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "list"])
            assert result.exit_code == 0
            assert "Team A" in result.output
            assert "Team B" in result.output

    def test_team_get(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "team-123",
            "name": "Data Platform",
            "created_at": "2024-01-01T00:00:00Z",
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "get", "team-123"])
            assert result.exit_code == 0
            assert "team-123" in result.output


class TestAssetCommands:
    """Tests for asset subcommands."""

    def test_asset_create_success(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "asset-123",
            "fqn": "warehouse.schema.users",
            "owner_team_id": "team-1",
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(
                app, ["asset", "create", "warehouse.schema.users", "--team", "team-1"]
            )
            assert result.exit_code == 0
            assert "Created asset:" in result.output
            assert "warehouse.schema.users" in result.output

    def test_asset_list_empty(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["asset", "list"])
            assert result.exit_code == 0
            assert "No assets found" in result.output

    def test_asset_list_with_assets(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": "a1", "fqn": "db.schema.table1", "owner_team_id": "t1"},
                {"id": "a2", "fqn": "db.schema.table2", "owner_team_id": "t2"},
            ]
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["asset", "list"])
            assert result.exit_code == 0
            assert "table1" in result.output
            assert "table2" in result.output

    def test_asset_search(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"id": "a1", "fqn": "db.schema.users"}]}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["asset", "search", "users"])
            assert result.exit_code == 0
            assert "users" in result.output


class TestContractCommands:
    """Tests for contract subcommands."""

    def test_contract_publish_file_not_found(self, tmp_path: pytest.TempPathFactory) -> None:
        result = runner.invoke(
            app,
            [
                "contract",
                "publish",
                "--asset",
                "a1",
                "--version",
                "1.0.0",
                "--schema",
                "/nonexistent/schema.json",
                "--team",
                "t1",
            ],
        )
        assert result.exit_code == 1
        assert "Schema file not found" in result.output

    def test_contract_publish_success(self, tmp_path: pytest.TempPathFactory) -> None:
        # Create a temporary schema file
        schema_file = tmp_path / "schema.json"  # type: ignore[operator]
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        schema_file.write_text(json.dumps(schema))

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "contract": {"id": "c1", "version": "1.0.0", "status": "active"}
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(
                app,
                [
                    "contract",
                    "publish",
                    "--asset",
                    "a1",
                    "--version",
                    "1.0.0",
                    "--schema",
                    str(schema_file),
                    "--team",
                    "t1",
                ],
            )
            assert result.exit_code == 0
            assert "Published contract:" in result.output
            assert "v1.0.0" in clean_ansi(result.output)

    def test_contract_publish_breaking_change(self, tmp_path: pytest.TempPathFactory) -> None:
        schema_file = tmp_path / "schema.json"  # type: ignore[operator]
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        schema_file.write_text(json.dumps(schema))

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "proposal": {"id": "p1", "status": "pending"},
            "breaking_changes": [
                {"change_type": "field_removed", "message": "Field 'name' removed"}
            ],
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(
                app,
                [
                    "contract",
                    "publish",
                    "--asset",
                    "a1",
                    "--version",
                    "2.0.0",
                    "--schema",
                    str(schema_file),
                    "--team",
                    "t1",
                ],
            )
            assert result.exit_code == 0
            assert "Breaking change detected" in result.output
            assert "field_removed" in result.output

    def test_contract_list_empty(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [], "total": 0, "limit": 50, "offset": 0}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["contract", "list", "asset-123"])
            assert result.exit_code == 0
            assert "No contracts found" in result.output

    def test_contract_list_with_contracts(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "c1",
                    "version": "1.0.0",
                    "status": "deprecated",
                    "published_at": "2024-01-01T00:00:00Z",
                },
                {
                    "id": "c2",
                    "version": "2.0.0",
                    "status": "active",
                    "published_at": "2024-01-02T00:00:00Z",
                },
            ],
            "total": 2,
            "limit": 50,
            "offset": 0,
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["contract", "list", "asset-123"])
            assert result.exit_code == 0
            assert "1.0.0" in result.output
            assert "2.0.0" in result.output

    def test_contract_diff(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "change_type": "minor",
            "is_breaking": False,
            "changes": [
                {"change_type": "field_added", "message": "Added field 'email'", "breaking": False}
            ],
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["contract", "diff", "asset-123"])
            assert result.exit_code == 0
            output = clean_ansi(result.output)
            assert "1.0.0" in output
            assert "2.0.0" in output
            assert "field_added" in output


class TestProposalCommands:
    """Tests for proposal subcommands."""

    def test_proposal_list_empty(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["proposal", "list"])
            assert result.exit_code == 0
            assert "No proposals found" in result.output

    def test_proposal_status(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "proposal_id": "p1",
            "status": "pending",
            "pending_count": 2,
            "acknowledged_count": 1,
            "can_publish": False,
            "acknowledgments": [
                {"consumer_team_name": "Team A", "response": "approved"},
            ],
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["proposal", "status", "p1"])
            assert result.exit_code == 0
            assert "pending" in result.output
            assert "Team A" in result.output

    def test_proposal_acknowledge(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "ack-1", "response": "approved"}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(
                app, ["proposal", "acknowledge", "p1", "--team", "t1", "--response", "approved"]
            )
            assert result.exit_code == 0
            assert "Acknowledged:" in result.output

    def test_proposal_force(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "p1", "status": "force_approved"}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["proposal", "force", "p1", "--team", "t1"])
            assert result.exit_code == 0
            assert "Force approved:" in result.output


class TestRegisterCommand:
    """Tests for the register command."""

    def test_register_success(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "reg-1",
            "asset_id": "a1",
            "consumer_team_id": "t1",
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["register", "--asset", "a1", "--team", "t1"])
            assert result.exit_code == 0
            assert "Registered:" in result.output

    def test_register_with_pin(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "reg-1",
            "asset_id": "a1",
            "consumer_team_id": "t1",
            "pinned_version": "1.0.0",
        }

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(
                app, ["register", "--asset", "a1", "--team", "t1", "--pin", "1.0.0"]
            )
            assert result.exit_code == 0
            assert "Pinned to:" in result.output
            assert "v1.0.0" in clean_ansi(result.output)


class TestErrorHandling:
    """Tests for error handling."""

    def test_api_error_response(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.text = "Not found"
        mock_response.json.return_value = {"detail": "Team not found"}

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "get", "nonexistent"])
            assert result.exit_code == 1
            output = clean_ansi(result.output)
            assert "Error (404)" in output
            assert "Team not found" in output

    def test_api_error_no_json(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.side_effect = Exception("Invalid JSON")

        with patch("tessera.cli.make_request", return_value=mock_response):
            result = runner.invoke(app, ["team", "get", "team-1"])
            assert result.exit_code == 1
            assert "Error (500)" in clean_ansi(result.output)


class TestHelpOutput:
    """Tests for help output."""

    def test_main_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Data contract coordination" in result.output
        assert "team" in result.output
        assert "asset" in result.output
        assert "contract" in result.output
        assert "proposal" in result.output

    def test_team_help(self) -> None:
        result = runner.invoke(app, ["team", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "get" in result.output

    def test_contract_help(self) -> None:
        result = runner.invoke(app, ["contract", "--help"])
        assert result.exit_code == 0
        assert "publish" in result.output
        assert "list" in result.output
        assert "diff" in result.output
        assert "impact" in result.output
