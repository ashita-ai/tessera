"""Tests for asset dependency and lineage endpoints."""

import pytest
from httpx import AsyncClient

from tests.conftest import make_asset, make_team

pytestmark = pytest.mark.asyncio


async def _setup_teams_and_assets(client: AsyncClient) -> dict:
    """Create a team with an upstream and downstream asset pair."""
    resp = await client.post("/api/v1/teams", json=make_team("dep-team"))
    team_id = resp.json()["id"]

    upstream_resp = await client.post(
        "/api/v1/assets", json=make_asset("dep.upstream.source", team_id)
    )
    upstream_id = upstream_resp.json()["id"]

    downstream_resp = await client.post(
        "/api/v1/assets", json=make_asset("dep.downstream.target", team_id)
    )
    downstream_id = downstream_resp.json()["id"]

    return {
        "team_id": team_id,
        "upstream_id": upstream_id,
        "downstream_id": downstream_id,
    }


class TestCreateDependency:
    """Tests for POST /{asset_id}/dependencies."""

    @pytest.mark.parametrize(
        "dep_type",
        ["consumes", "references", "transforms"],
        ids=["consumes", "references", "transforms"],
    )
    async def test_create_with_each_type(self, client: AsyncClient, dep_type: str) -> None:
        """All valid dependency types can be created."""
        resp = await client.post("/api/v1/teams", json=make_team(f"dep-{dep_type}"))
        team_id = resp.json()["id"]

        upstream = await client.post(
            "/api/v1/assets", json=make_asset(f"dep.{dep_type}.src", team_id)
        )
        downstream = await client.post(
            "/api/v1/assets", json=make_asset(f"dep.{dep_type}.dst", team_id)
        )

        resp = await client.post(
            f"/api/v1/assets/{downstream.json()['id']}/dependencies",
            json={
                "depends_on_asset_id": upstream.json()["id"],
                "dependency_type": dep_type,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["dependency_type"] == dep_type

    async def test_self_dependency_rejected(self, client: AsyncClient) -> None:
        """An asset cannot depend on itself."""
        resp = await client.post("/api/v1/teams", json=make_team("self-dep"))
        team_id = resp.json()["id"]

        asset_resp = await client.post("/api/v1/assets", json=make_asset("dep.self.table", team_id))
        asset_id = asset_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/dependencies",
            json={"depends_on_asset_id": asset_id, "dependency_type": "consumes"},
        )
        assert resp.status_code == 400
        assert "SELF_DEPENDENCY" in resp.text

    async def test_duplicate_dependency_rejected(self, client: AsyncClient) -> None:
        """Creating the same dependency twice is rejected."""
        ctx = await _setup_teams_and_assets(client)

        body = {
            "depends_on_asset_id": ctx["upstream_id"],
            "dependency_type": "consumes",
        }
        resp1 = await client.post(f"/api/v1/assets/{ctx['downstream_id']}/dependencies", json=body)
        assert resp1.status_code == 201

        resp2 = await client.post(f"/api/v1/assets/{ctx['downstream_id']}/dependencies", json=body)
        assert resp2.status_code == 409
        assert "DUPLICATE_DEPENDENCY" in resp2.text

    async def test_dependency_on_nonexistent_asset(self, client: AsyncClient) -> None:
        """Creating a dependency on a missing upstream asset returns 404."""
        resp = await client.post("/api/v1/teams", json=make_team("dep-ghost"))
        team_id = resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json=make_asset("dep.ghost.table", team_id)
        )

        resp = await client.post(
            f"/api/v1/assets/{asset_resp.json()['id']}/dependencies",
            json={
                "depends_on_asset_id": "00000000-0000-0000-0000-000000000000",
                "dependency_type": "consumes",
            },
        )
        assert resp.status_code == 404

    async def test_dependency_from_nonexistent_asset(self, client: AsyncClient) -> None:
        """Creating a dependency from a nonexistent asset returns 404."""
        resp = await client.post(
            "/api/v1/assets/00000000-0000-0000-0000-000000000000/dependencies",
            json={
                "depends_on_asset_id": "00000000-0000-0000-0000-000000000001",
                "dependency_type": "consumes",
            },
        )
        assert resp.status_code == 404


class TestListDependencies:
    """Tests for GET /{asset_id}/dependencies."""

    async def test_list_empty(self, client: AsyncClient) -> None:
        """An asset with no dependencies returns an empty list."""
        resp = await client.post("/api/v1/teams", json=make_team("dep-empty"))
        team_id = resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json=make_asset("dep.empty.table", team_id)
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.get(f"/api/v1/assets/{asset_id}/dependencies")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    async def test_list_returns_created_dependencies(self, client: AsyncClient) -> None:
        """Listed dependencies match what was created."""
        ctx = await _setup_teams_and_assets(client)

        await client.post(
            f"/api/v1/assets/{ctx['downstream_id']}/dependencies",
            json={
                "depends_on_asset_id": ctx["upstream_id"],
                "dependency_type": "consumes",
            },
        )

        resp = await client.get(f"/api/v1/assets/{ctx['downstream_id']}/dependencies")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["dependency_asset_id"] == ctx["upstream_id"]

    async def test_list_for_nonexistent_asset(self, client: AsyncClient) -> None:
        """Listing dependencies for a missing asset returns 404."""
        resp = await client.get("/api/v1/assets/00000000-0000-0000-0000-000000000000/dependencies")
        assert resp.status_code == 404


class TestDeleteDependency:
    """Tests for DELETE /{asset_id}/dependencies/{dependency_id}."""

    async def test_delete_existing_dependency(self, client: AsyncClient) -> None:
        """Deleting an existing dependency succeeds and removes it from listings."""
        ctx = await _setup_teams_and_assets(client)

        create_resp = await client.post(
            f"/api/v1/assets/{ctx['downstream_id']}/dependencies",
            json={
                "depends_on_asset_id": ctx["upstream_id"],
                "dependency_type": "consumes",
            },
        )
        dep_id = create_resp.json()["id"]

        del_resp = await client.delete(
            f"/api/v1/assets/{ctx['downstream_id']}/dependencies/{dep_id}"
        )
        assert del_resp.status_code == 204

        # Verify it no longer appears in listings
        list_resp = await client.get(f"/api/v1/assets/{ctx['downstream_id']}/dependencies")
        assert list_resp.json()["results"] == []

    async def test_delete_nonexistent_dependency(self, client: AsyncClient) -> None:
        """Deleting a nonexistent dependency returns 404."""
        resp = await client.post("/api/v1/teams", json=make_team("dep-del-ghost"))
        team_id = resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json=make_asset("dep.del.ghost.table", team_id)
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/assets/{asset_id}/dependencies/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404


class TestGetLineage:
    """Tests for GET /{asset_id}/lineage."""

    async def test_lineage_empty(self, client: AsyncClient) -> None:
        """An asset with no dependencies or consumers has empty lineage."""
        resp = await client.post("/api/v1/teams", json=make_team("lineage-empty"))
        team_id = resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json=make_asset("lineage.empty.table", team_id)
        )
        asset_id = asset_resp.json()["id"]

        resp = await client.get(f"/api/v1/assets/{asset_id}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_id"] == asset_id
        assert data["upstream"] == []
        assert data["downstream"] == []
        assert data["downstream_assets"] == []

    async def test_lineage_shows_upstream(self, client: AsyncClient) -> None:
        """Lineage includes upstream dependencies."""
        ctx = await _setup_teams_and_assets(client)

        await client.post(
            f"/api/v1/assets/{ctx['downstream_id']}/dependencies",
            json={
                "depends_on_asset_id": ctx["upstream_id"],
                "dependency_type": "consumes",
            },
        )

        resp = await client.get(f"/api/v1/assets/{ctx['downstream_id']}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["upstream"]) == 1
        assert data["upstream"][0]["asset_id"] == ctx["upstream_id"]

    async def test_lineage_shows_downstream_assets(self, client: AsyncClient) -> None:
        """Lineage includes assets that depend on this asset."""
        ctx = await _setup_teams_and_assets(client)

        await client.post(
            f"/api/v1/assets/{ctx['downstream_id']}/dependencies",
            json={
                "depends_on_asset_id": ctx["upstream_id"],
                "dependency_type": "transforms",
            },
        )

        resp = await client.get(f"/api/v1/assets/{ctx['upstream_id']}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["downstream_assets"]) == 1
        assert data["downstream_assets"][0]["asset_id"] == ctx["downstream_id"]

    async def test_lineage_nonexistent_asset(self, client: AsyncClient) -> None:
        """Lineage for a nonexistent asset returns 404."""
        resp = await client.get("/api/v1/assets/00000000-0000-0000-0000-000000000000/lineage")
        assert resp.status_code == 404
