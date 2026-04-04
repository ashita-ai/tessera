"""Tests for /api/v1/services endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


async def _create_team(client: AsyncClient, name: str = "svc-team") -> str:
    resp = await client.post("/api/v1/teams", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
async def repo_id(client: AsyncClient, test_engine) -> str:
    """Create a team and repo in the database, return the repo ID.

    Since there's no repo HTTP endpoint, we insert directly into the DB.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tessera.db.models import RepoDB, TeamDB

    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        team = TeamDB(name="svc-test-team")
        session.add(team)
        await session.flush()

        repo = RepoDB(
            name="test-repo",
            git_url="https://github.com/acme/test-repo",
            owner_team_id=team.id,
        )
        session.add(repo)
        await session.flush()
        await session.commit()
        return str(repo.id)


@pytest.fixture
async def team_and_repo(client: AsyncClient, test_engine) -> tuple[str, str]:
    """Create a team and repo, returning (team_id, repo_id)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tessera.db.models import RepoDB, TeamDB

    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        team = TeamDB(name="svc-fixture-team")
        session.add(team)
        await session.flush()

        repo = RepoDB(
            name="fixture-repo",
            git_url="https://github.com/acme/fixture-repo",
            owner_team_id=team.id,
        )
        session.add(repo)
        await session.flush()
        await session.commit()
        return str(team.id), str(repo.id)


class TestCreateService:
    """POST /api/v1/services"""

    async def test_create_service(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        resp = await client.post(
            "/api/v1/services",
            json={
                "name": "order-service",
                "repo_id": repo_id,
                "root_path": "/services/order",
                "otel_service_name": "order-svc",
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "order-service"
        assert data["repo_id"] == repo_id
        assert data["root_path"] == "/services/order"
        assert data["otel_service_name"] == "order-svc"
        assert data["owner_team_id"] == team_id
        assert "id" in data
        assert "created_at" in data

    async def test_create_service_defaults(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        resp = await client.post(
            "/api/v1/services",
            json={
                "name": "simple-svc",
                "repo_id": repo_id,
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["root_path"] == "/"
        assert data["otel_service_name"] is None

    async def test_create_duplicate_name_in_same_repo(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        payload = {
            "name": "dup-svc",
            "repo_id": repo_id,
            "owner_team_id": team_id,
        }
        resp1 = await client.post("/api/v1/services", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/api/v1/services", json=payload)
        assert resp2.status_code == 409

    async def test_create_same_name_different_repo(self, client: AsyncClient, test_engine):
        """Same service name is allowed in different repos."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from tessera.db.models import RepoDB, TeamDB

        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            team = TeamDB(name="multi-repo-team")
            session.add(team)
            await session.flush()

            repo_a = RepoDB(
                name="repo-a",
                git_url="https://github.com/acme/repo-a",
                owner_team_id=team.id,
            )
            repo_b = RepoDB(
                name="repo-b",
                git_url="https://github.com/acme/repo-b",
                owner_team_id=team.id,
            )
            session.add_all([repo_a, repo_b])
            await session.flush()
            await session.commit()

            t_id, ra_id, rb_id = str(team.id), str(repo_a.id), str(repo_b.id)

        resp1 = await client.post(
            "/api/v1/services",
            json={"name": "shared-name", "repo_id": ra_id, "owner_team_id": t_id},
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/v1/services",
            json={"name": "shared-name", "repo_id": rb_id, "owner_team_id": t_id},
        )
        assert resp2.status_code == 201

    async def test_create_service_nonexistent_repo(self, client: AsyncClient):
        team_id = await _create_team(client, "orphan-team")
        resp = await client.post(
            "/api/v1/services",
            json={
                "name": "orphan-svc",
                "repo_id": ZERO_UUID,
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 404


class TestListServices:
    """GET /api/v1/services"""

    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_list_services(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        for name in ["alpha-svc", "beta-svc"]:
            await client.post(
                "/api/v1/services",
                json={"name": name, "repo_id": repo_id, "owner_team_id": team_id},
            )

        resp = await client.get("/api/v1/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        names = [s["name"] for s in data["results"]]
        assert "alpha-svc" in names
        assert "beta-svc" in names

    async def test_list_filter_by_repo_id(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        await client.post(
            "/api/v1/services",
            json={"name": "filtered-svc", "repo_id": repo_id, "owner_team_id": team_id},
        )

        resp = await client.get(f"/api/v1/services?repo_id={repo_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for svc in data["results"]:
            assert svc["repo_id"] == repo_id

    async def test_list_filter_by_team_id(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        await client.post(
            "/api/v1/services",
            json={"name": "team-filtered", "repo_id": repo_id, "owner_team_id": team_id},
        )

        resp = await client.get(f"/api/v1/services?team_id={team_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for svc in data["results"]:
            assert svc["owner_team_id"] == team_id

    async def test_list_filter_by_otel_service_name(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        await client.post(
            "/api/v1/services",
            json={
                "name": "otel-svc",
                "repo_id": repo_id,
                "owner_team_id": team_id,
                "otel_service_name": "my-otel-name",
            },
        )

        resp = await client.get("/api/v1/services?otel_service_name=my-otel-name")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["results"][0]["otel_service_name"] == "my-otel-name"

    async def test_list_pagination(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        for i in range(5):
            await client.post(
                "/api/v1/services",
                json={"name": f"page-svc-{i}", "repo_id": repo_id, "owner_team_id": team_id},
            )

        resp = await client.get("/api/v1/services?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["total"] >= 5
        assert data["limit"] == 2
        assert data["offset"] == 0


class TestGetService:
    """GET /api/v1/services/{id}"""

    async def test_get_service(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "get-me", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/services/{svc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "get-me"
        assert data["asset_count"] == 0

    async def test_get_service_asset_count_zero(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        """Asset count is 0 when no assets are linked."""
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "no-assets-svc", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/services/{svc_id}")
        assert resp.status_code == 200
        assert resp.json()["asset_count"] == 0

    async def test_get_nonexistent_service(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/services/{ZERO_UUID}")
        assert resp.status_code == 404


class TestListServiceAssets:
    """GET /api/v1/services/{id}/assets"""

    async def test_list_assets_empty(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "empty-assets", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/services/{svc_id}/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_list_assets_nonexistent_service(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/services/{ZERO_UUID}/assets")
        assert resp.status_code == 404


class TestUpdateService:
    """PATCH /api/v1/services/{id}"""

    async def test_update_root_path(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "update-me", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/services/{svc_id}",
            json={"root_path": "/new/path"},
        )
        assert resp.status_code == 200
        assert resp.json()["root_path"] == "/new/path"

    async def test_update_otel_service_name(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "otel-update", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/services/{svc_id}",
            json={"otel_service_name": "new-otel-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["otel_service_name"] == "new-otel-name"

    async def test_update_nonexistent_service(self, client: AsyncClient):
        resp = await client.patch(
            f"/api/v1/services/{ZERO_UUID}",
            json={"root_path": "/nope"},
        )
        assert resp.status_code == 404


class TestDeleteService:
    """DELETE /api/v1/services/{id}"""

    async def test_delete_service(self, client: AsyncClient, team_and_repo: tuple[str, str]):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "delete-me", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/services/{svc_id}")
        assert resp.status_code == 204

        # Should no longer be findable
        get_resp = await client.get(f"/api/v1/services/{svc_id}")
        assert get_resp.status_code == 404

    async def test_delete_service_not_in_list(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "ghost-svc", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/services/{svc_id}")

        list_resp = await client.get("/api/v1/services")
        ids = [s["id"] for s in list_resp.json()["results"]]
        assert svc_id not in ids

    async def test_delete_nonexistent_service(self, client: AsyncClient):
        resp = await client.delete(f"/api/v1/services/{ZERO_UUID}")
        assert resp.status_code == 404

    async def test_delete_is_idempotent_guard(
        self, client: AsyncClient, team_and_repo: tuple[str, str]
    ):
        """Deleting an already-deleted service returns 404 (soft delete is invisible)."""
        team_id, repo_id = team_and_repo
        create_resp = await client.post(
            "/api/v1/services",
            json={"name": "double-del", "repo_id": repo_id, "owner_team_id": team_id},
        )
        svc_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/services/{svc_id}")
        resp = await client.delete(f"/api/v1/services/{svc_id}")
        assert resp.status_code == 404
