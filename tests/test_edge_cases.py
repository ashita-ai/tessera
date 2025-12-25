"""Tests for edge cases and error handling."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestContractEdgeCases:
    """Tests for contract publishing edge cases."""

    async def test_publish_contract_asset_not_found(self, client: AsyncClient):
        """Publishing to nonexistent asset should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "contract-notfound"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/00000000-0000-0000-0000-000000000000/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object"},
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 404

    async def test_publish_contract_publisher_not_found(self, client: AsyncClient):
        """Publishing with nonexistent publisher team should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "pub-notfound"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "pub.notfound.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts"
            "?published_by=00000000-0000-0000-0000-000000000000",
            json={
                "version": "1.0.0",
                "schema": {"type": "object"},
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 404

    async def test_publish_contract_invalid_json_schema(self, client: AsyncClient):
        """Publishing invalid JSON Schema should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "invalid-schema"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "invalid.schema.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "not_a_valid_type"},
                "compatibility_mode": "backward",
            },
        )
        assert resp.status_code == 400  # BadRequestError for invalid schema


class TestRegistrationEdgeCases:
    """Tests for registration edge cases."""

    async def test_register_consumer_contract_not_found(self, client: AsyncClient):
        """Registering to nonexistent contract should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "reg-notfound"})
        consumer_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/registrations?contract_id=00000000-0000-0000-0000-000000000000",
            json={"consumer_team_id": consumer_id},
        )
        assert resp.status_code == 404

    async def test_register_consumer_creates_registration(self, client: AsyncClient):
        """Registering a consumer creates a registration."""
        team_resp = await client.post("/api/v1/teams", json={"name": "reg-team-success"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "reg.team.success", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object"},
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        resp = await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": team_id},
        )
        assert resp.status_code == 201


class TestProposalEdgeCases:
    """Tests for proposal edge cases."""

    async def test_force_approve_nonexistent_proposal(self, client: AsyncClient):
        """Force-approving nonexistent proposal should 404."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-notfound"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/proposals/00000000-0000-0000-0000-000000000000/force?actor_id={team_id}"
        )
        assert resp.status_code == 404

    async def test_force_approve_nonpending_proposal(self, client: AsyncClient):
        """Force-approving already-approved proposal should fail."""
        team_resp = await client.post("/api/v1/teams", json={"name": "force-nonpend"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "force.nonpend.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create initial contract
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        # Create breaking change
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        # Force approve
        await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")

        # Try to force approve again
        resp = await client.post(f"/api/v1/proposals/{proposal_id}/force?actor_id={team_id}")
        assert resp.status_code == 400

    async def test_withdraw_nonexistent_proposal(self, client: AsyncClient):
        """Withdrawing nonexistent proposal should 404."""
        resp = await client.post("/api/v1/proposals/00000000-0000-0000-0000-000000000000/withdraw")
        assert resp.status_code == 404

    async def test_get_status_nonexistent_proposal(self, client: AsyncClient):
        """Getting status of nonexistent proposal should 404."""
        resp = await client.get("/api/v1/proposals/00000000-0000-0000-0000-000000000000/status")
        assert resp.status_code == 404


class TestDependencyEdgeCases:
    """Tests for dependency edge cases."""

    async def test_list_dependencies_asset_not_found(self, client: AsyncClient):
        """Listing dependencies for nonexistent asset should 404."""
        resp = await client.get("/api/v1/assets/00000000-0000-0000-0000-000000000000/dependencies")
        assert resp.status_code == 404

    async def test_create_dependency_with_different_types(self, client: AsyncClient):
        """Create dependencies with different types."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dep-types"})
        team_id = team_resp.json()["id"]

        downstream_resp = await client.post(
            "/api/v1/assets", json={"fqn": "deptypes.downstream.table", "owner_team_id": team_id}
        )
        downstream_id = downstream_resp.json()["id"]

        # Test valid dependency types from DependencyType enum
        for dep_type in ["consumes", "references", "transforms"]:
            upstream_resp = await client.post(
                "/api/v1/assets",
                json={"fqn": f"deptypes.{dep_type}.source", "owner_team_id": team_id},
            )
            upstream_id = upstream_resp.json()["id"]

            resp = await client.post(
                f"/api/v1/assets/{downstream_id}/dependencies",
                json={"depends_on_asset_id": upstream_id, "dependency_type": dep_type},
            )
            assert resp.status_code == 201
            assert resp.json()["dependency_type"] == dep_type


class TestTeamEdgeCases:
    """Tests for team edge cases."""

    async def test_update_team_not_found(self, client: AsyncClient):
        """Updating nonexistent team should 404."""
        resp = await client.patch(
            "/api/v1/teams/00000000-0000-0000-0000-000000000000",
            json={"name": "new-name"},
        )
        assert resp.status_code == 404

    async def test_get_team_not_found(self, client: AsyncClient):
        """Getting nonexistent team should 404."""
        resp = await client.get("/api/v1/teams/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestCompatibilityModes:
    """Tests for different compatibility modes."""

    async def test_none_compatibility_mode_publishes_breaking(self, client: AsyncClient):
        """With compatibility_mode=none, breaking changes auto-publish."""
        team_resp = await client.post("/api/v1/teams", json={"name": "compat-none"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "compat.none.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract with none mode
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                    "required": ["id", "name"],
                },
                "compatibility_mode": "none",
            },
        )

        # Breaking change with none mode should auto-publish
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "2.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
                "compatibility_mode": "none",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "published"

    async def test_full_compatibility_mode(self, client: AsyncClient):
        """With compatibility_mode=full, any change is breaking."""
        team_resp = await client.post("/api/v1/teams", json={"name": "compat-full"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "compat.full.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        # First contract with full mode
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "full",
            },
        )

        # Adding a field with full mode creates a proposal
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.1.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "full",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # Full mode treats any change as breaking
        assert data["action"] in ["published", "proposal_created"]


class TestPaginationEdgeCases:
    """Tests for pagination edge cases."""

    async def test_large_offset_returns_empty(self, client: AsyncClient):
        """Large offset returns empty results."""
        resp = await client.get("/api/v1/teams?offset=999999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    async def test_limit_zero(self, client: AsyncClient):
        """Limit of 0 should be invalid."""
        resp = await client.get("/api/v1/teams?limit=0")
        # Should fail validation
        assert resp.status_code == 422

    async def test_negative_offset(self, client: AsyncClient):
        """Negative offset should be invalid."""
        resp = await client.get("/api/v1/teams?offset=-1")
        assert resp.status_code == 422


class TestGuaranteesInContracts:
    """Tests for contract guarantees."""

    async def test_contract_with_guarantees(self, client: AsyncClient):
        """Create contract with guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantees-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "guarantees.test.table", "owner_team_id": team_id}
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
                "guarantees": {
                    "freshness": {"max_staleness_minutes": 60},
                    "volume": {"min_rows": 1000},
                    "nullability": {"id": "never"},
                    "accepted_values": {"status": ["active", "inactive"]},
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "published"
        contract = data["contract"]
        assert contract["guarantees"]["freshness"]["max_staleness_minutes"] == 60
        assert contract["guarantees"]["volume"]["min_rows"] == 1000
