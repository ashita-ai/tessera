"""Tests for TesseraClient and AsyncTesseraClient."""

import pytest
from pytest_httpx import HTTPXMock

from tessera_sdk import (
    AsyncTesseraClient,
    CompatibilityMode,
    NotFoundError,
    TesseraClient,
    TesseraError,
    ValidationError,
)


class TestTesseraClient:
    """Tests for sync client."""

    def test_client_initialization(self) -> None:
        """Test client can be initialized."""
        client = TesseraClient(base_url="http://localhost:8000")
        assert client._http.base_url == "http://localhost:8000"
        client.close()

    def test_client_context_manager(self) -> None:
        """Test client works as context manager."""
        with TesseraClient(base_url="http://localhost:8000") as client:
            assert client._http.base_url == "http://localhost:8000"

    def test_health_check(self, httpx_mock: HTTPXMock) -> None:
        """Test health check endpoint."""
        httpx_mock.add_response(
            url="http://test.local/health",
            json={"status": "healthy"},
        )
        with TesseraClient(base_url="http://test.local") as client:
            result = client.health()
            assert result == {"status": "healthy"}


class TestTeamsResource:
    """Tests for teams resource."""

    def test_create_team(self, httpx_mock: HTTPXMock) -> None:
        """Test creating a team."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/teams",
            method="POST",
            json={
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "data-platform",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            team = client.teams.create(name="data-platform")
            assert team.name == "data-platform"
            assert str(team.id) == "550e8400-e29b-41d4-a716-446655440000"

    def test_list_teams(self, httpx_mock: HTTPXMock) -> None:
        """Test listing teams."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/teams?limit=100&offset=0",
            json=[
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "name": "data-platform",
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ],
        )
        with TesseraClient(base_url="http://test.local") as client:
            teams = client.teams.list()
            assert len(teams) == 1
            assert teams[0].name == "data-platform"

    def test_get_team(self, httpx_mock: HTTPXMock) -> None:
        """Test getting a team by ID."""
        team_id = "550e8400-e29b-41d4-a716-446655440000"
        httpx_mock.add_response(
            url=f"http://test.local/api/v1/teams/{team_id}",
            json={
                "id": team_id,
                "name": "data-platform",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            team = client.teams.get(team_id)
            assert team.name == "data-platform"

    def test_get_team_not_found(self, httpx_mock: HTTPXMock) -> None:
        """Test 404 error handling."""
        team_id = "550e8400-e29b-41d4-a716-446655440000"
        httpx_mock.add_response(
            url=f"http://test.local/api/v1/teams/{team_id}",
            status_code=404,
            json={"detail": "Team not found"},
        )
        with TesseraClient(base_url="http://test.local") as client:
            with pytest.raises(NotFoundError) as exc_info:
                client.teams.get(team_id)
            assert "Team not found" in str(exc_info.value)


class TestAssetsResource:
    """Tests for assets resource."""

    def test_create_asset(self, httpx_mock: HTTPXMock) -> None:
        """Test creating an asset."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/assets",
            method="POST",
            json={
                "id": "660e8400-e29b-41d4-a716-446655440000",
                "fqn": "warehouse.analytics.dim_customers",
                "owner_team_id": "550e8400-e29b-41d4-a716-446655440000",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            asset = client.assets.create(
                fqn="warehouse.analytics.dim_customers",
                owner_team_id="550e8400-e29b-41d4-a716-446655440000",
            )
            assert asset.fqn == "warehouse.analytics.dim_customers"

    def test_publish_contract(self, httpx_mock: HTTPXMock) -> None:
        """Test publishing a contract."""
        asset_id = "660e8400-e29b-41d4-a716-446655440000"
        httpx_mock.add_response(
            url=f"http://test.local/api/v1/assets/{asset_id}/contracts",
            method="POST",
            json={
                "contract": {
                    "id": "770e8400-e29b-41d4-a716-446655440000",
                    "asset_id": asset_id,
                    "version": "1.0.0",
                    "schema": {"type": "object"},
                    "compatibility_mode": "backward",
                    "status": "active",
                    "published_at": "2024-01-01T00:00:00Z",
                    "published_by": "550e8400-e29b-41d4-a716-446655440000",
                },
                "proposal": None,
                "message": "Contract published",
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            result = client.assets.publish_contract(
                asset_id=asset_id,
                schema={"type": "object"},
                version="1.0.0",
            )
            assert result.contract is not None
            assert result.contract.version == "1.0.0"

    def test_check_impact(self, httpx_mock: HTTPXMock) -> None:
        """Test impact analysis."""
        asset_id = "660e8400-e29b-41d4-a716-446655440000"
        httpx_mock.add_response(
            url=f"http://test.local/api/v1/assets/{asset_id}/impact",
            method="POST",
            json={
                "asset_id": asset_id,
                "safe_to_publish": False,
                "change_type": "major",
                "breaking_changes": [
                    {"type": "type_change", "column": "id", "details": {}}
                ],
                "impacted_consumers": [],
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            impact = client.assets.check_impact(
                asset_id=asset_id,
                proposed_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
            assert not impact.safe_to_publish
            assert len(impact.breaking_changes) == 1


class TestContractsResource:
    """Tests for contracts resource."""

    def test_compare_schemas(self, httpx_mock: HTTPXMock) -> None:
        """Test schema comparison."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/contracts/compare",
            method="POST",
            json={
                "compatible": False,
                "change_type": "major",
                "breaking_changes": [{"type": "type_change"}],
            },
        )
        with TesseraClient(base_url="http://test.local") as client:
            result = client.contracts.compare(
                old_schema={"type": "object"},
                new_schema={"type": "array"},
                compatibility_mode=CompatibilityMode.BACKWARD,
            )
            assert result["compatible"] is False


class TestErrorHandling:
    """Tests for error handling."""

    def test_validation_error(self, httpx_mock: HTTPXMock) -> None:
        """Test 422 validation error."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/teams",
            method="POST",
            status_code=422,
            json={"detail": "Validation failed"},
        )
        with TesseraClient(base_url="http://test.local") as client:
            with pytest.raises(ValidationError):
                client.teams.create(name="x")

    def test_generic_error(self, httpx_mock: HTTPXMock) -> None:
        """Test generic error."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/teams",
            method="POST",
            status_code=400,
            json={"detail": "Bad request"},
        )
        with TesseraClient(base_url="http://test.local") as client:
            with pytest.raises(TesseraError):
                client.teams.create(name="test")


class TestAsyncClient:
    """Tests for async client."""

    @pytest.mark.asyncio
    async def test_async_health_check(self, httpx_mock: HTTPXMock) -> None:
        """Test async health check."""
        httpx_mock.add_response(
            url="http://test.local/health",
            json={"status": "healthy"},
        )
        async with AsyncTesseraClient(base_url="http://test.local") as client:
            result = await client.health()
            assert result == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_async_create_team(self, httpx_mock: HTTPXMock) -> None:
        """Test async team creation."""
        httpx_mock.add_response(
            url="http://test.local/api/v1/teams",
            method="POST",
            json={
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "data-platform",
                "metadata": {},
                "created_at": "2024-01-01T00:00:00Z",
            },
        )
        async with AsyncTesseraClient(base_url="http://test.local") as client:
            team = await client.teams.create(name="data-platform")
            assert team.name == "data-platform"
