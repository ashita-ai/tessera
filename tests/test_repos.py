"""Tests for /api/v1/repos endpoints."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import _USE_SQLITE, create_tables, drop_tables

pytestmark = pytest.mark.asyncio

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


async def _create_team(client: AsyncClient, name: str = "repo-owner") -> str:
    """Helper: create a team and return its ID."""
    resp = await client.post("/api/v1/teams", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_repo(
    client: AsyncClient,
    team_id: str,
    name: str = "my-repo",
    git_url: str = "https://github.com/org/my-repo.git",
    **kwargs: object,
) -> dict:
    """Helper: create a repo and return the response body."""
    payload: dict[str, object] = {
        "name": name,
        "git_url": git_url,
        "owner_team_id": team_id,
        **kwargs,
    }
    resp = await client.post("/api/v1/repos", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateRepo:
    """Tests for POST /api/v1/repos."""

    async def test_create_repo(self, client: AsyncClient):
        """Register a repository with required fields."""
        team_id = await _create_team(client)
        data = await _create_repo(client, team_id)

        assert data["name"] == "my-repo"
        assert data["git_url"] == "https://github.com/org/my-repo.git"
        assert data["owner_team_id"] == team_id
        assert data["default_branch"] == "main"
        assert data["spec_paths"] == []
        assert data["sync_enabled"] is True
        assert data["codeowners_path"] is None
        assert "id" in data
        assert "created_at" in data

    async def test_create_repo_all_fields(self, client: AsyncClient):
        """Register a repository with all optional fields specified."""
        team_id = await _create_team(client)
        data = await _create_repo(
            client,
            team_id,
            name="full-repo",
            git_url="https://github.com/org/full-repo.git",
            default_branch="develop",
            spec_paths=["openapi/v1.yaml", "proto/service.proto"],
            codeowners_path=".github/CODEOWNERS",
            sync_enabled=False,
        )

        assert data["default_branch"] == "develop"
        assert data["spec_paths"] == ["openapi/v1.yaml", "proto/service.proto"]
        assert data["codeowners_path"] == ".github/CODEOWNERS"
        assert data["sync_enabled"] is False

    async def test_create_repo_owner_team_not_found(self, client: AsyncClient):
        """Creating a repo with a nonexistent owner team should 404."""
        resp = await client.post(
            "/api/v1/repos",
            json={
                "name": "orphan-repo",
                "git_url": "https://github.com/org/orphan.git",
                "owner_team_id": _ZERO_UUID,
            },
        )
        assert resp.status_code == 404

    async def test_create_duplicate_name_fails(self, client: AsyncClient):
        """Creating a repo with a duplicate name should 409."""
        team_id = await _create_team(client)
        await _create_repo(client, team_id, name="dup-name", git_url="https://a.git")
        resp = await client.post(
            "/api/v1/repos",
            json={
                "name": "dup-name",
                "git_url": "https://b.git",
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 409

    async def test_create_duplicate_git_url_fails(self, client: AsyncClient):
        """Creating a repo with a duplicate git URL should 409."""
        team_id = await _create_team(client)
        await _create_repo(client, team_id, name="repo-a", git_url="https://dup.git")
        resp = await client.post(
            "/api/v1/repos",
            json={
                "name": "repo-b",
                "git_url": "https://dup.git",
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 409

    async def test_create_repo_empty_name_fails(self, client: AsyncClient):
        """Creating a repo with empty name should fail validation."""
        team_id = await _create_team(client)
        resp = await client.post(
            "/api/v1/repos",
            json={
                "name": "",
                "git_url": "https://example.git",
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 422


class TestListRepos:
    """Tests for GET /api/v1/repos."""

    async def test_list_repos_empty(self, client: AsyncClient):
        """List repos when none exist."""
        resp = await client.get("/api/v1/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_list_repos(self, client: AsyncClient):
        """List repos returns created repos."""
        team_id = await _create_team(client)
        await _create_repo(client, team_id, name="repo-1", git_url="https://1.git")
        await _create_repo(client, team_id, name="repo-2", git_url="https://2.git")

        resp = await client.get("/api/v1/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2
        # Ordered by name
        names = [r["name"] for r in data["results"]]
        assert names == sorted(names)

    async def test_list_repos_filter_by_team(self, client: AsyncClient):
        """Filter repos by owner team."""
        team_a = await _create_team(client, name="team-a")
        team_b = await _create_team(client, name="team-b")
        await _create_repo(client, team_a, name="a-repo", git_url="https://a.git")
        await _create_repo(client, team_b, name="b-repo", git_url="https://b.git")

        resp = await client.get(f"/api/v1/repos?team_id={team_a}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["name"] == "a-repo"

    async def test_list_repos_filter_by_sync_enabled(self, client: AsyncClient):
        """Filter repos by sync_enabled flag."""
        team_id = await _create_team(client)
        await _create_repo(
            client, team_id, name="sync-on", git_url="https://on.git", sync_enabled=True
        )
        await _create_repo(
            client, team_id, name="sync-off", git_url="https://off.git", sync_enabled=False
        )

        resp = await client.get("/api/v1/repos?sync_enabled=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["name"] == "sync-off"

    async def test_list_repos_pagination(self, client: AsyncClient):
        """List repos with pagination."""
        team_id = await _create_team(client)
        for i in range(5):
            await _create_repo(
                client, team_id, name=f"page-repo-{i:02d}", git_url=f"https://{i}.git"
            )

        resp = await client.get("/api/v1/repos?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["results"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_list_repos_excludes_soft_deleted(self, client: AsyncClient):
        """Soft-deleted repos should not appear in the list."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id, name="to-delete", git_url="https://del.git")

        # Delete
        resp = await client.delete(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 204

        # Verify not in list
        resp = await client.get("/api/v1/repos")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetRepo:
    """Tests for GET /api/v1/repos/{id}."""

    async def test_get_repo(self, client: AsyncClient):
        """Get a single repo by ID."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.get(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "my-repo"
        assert data["services_count"] == 0

    async def test_get_repo_not_found(self, client: AsyncClient):
        """Getting a nonexistent repo should 404."""
        resp = await client.get(f"/api/v1/repos/{_ZERO_UUID}")
        assert resp.status_code == 404

    async def test_get_deleted_repo_not_found(self, client: AsyncClient):
        """Getting a soft-deleted repo should 404."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)
        await client.delete(f"/api/v1/repos/{repo['id']}")

        resp = await client.get(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 404


class TestUpdateRepo:
    """Tests for PATCH /api/v1/repos/{id}."""

    async def test_update_default_branch(self, client: AsyncClient):
        """Update the default branch."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.patch(
            f"/api/v1/repos/{repo['id']}",
            json={"default_branch": "develop"},
        )
        assert resp.status_code == 200
        assert resp.json()["default_branch"] == "develop"

    async def test_update_spec_paths(self, client: AsyncClient):
        """Update spec_paths."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.patch(
            f"/api/v1/repos/{repo['id']}",
            json={"spec_paths": ["openapi.yaml", "proto/svc.proto"]},
        )
        assert resp.status_code == 200
        assert resp.json()["spec_paths"] == ["openapi.yaml", "proto/svc.proto"]

    async def test_update_sync_enabled(self, client: AsyncClient):
        """Toggle sync_enabled."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.patch(
            f"/api/v1/repos/{repo['id']}",
            json={"sync_enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["sync_enabled"] is False

    async def test_update_codeowners_path(self, client: AsyncClient):
        """Update codeowners_path."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.patch(
            f"/api/v1/repos/{repo['id']}",
            json={"codeowners_path": "CODEOWNERS"},
        )
        assert resp.status_code == 200
        assert resp.json()["codeowners_path"] == "CODEOWNERS"

    async def test_update_repo_not_found(self, client: AsyncClient):
        """Updating a nonexistent repo should 404."""
        resp = await client.patch(
            f"/api/v1/repos/{_ZERO_UUID}",
            json={"sync_enabled": False},
        )
        assert resp.status_code == 404

    async def test_update_noop(self, client: AsyncClient):
        """PATCH with empty body should succeed (no changes)."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.patch(f"/api/v1/repos/{repo['id']}", json={})
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-repo"


class TestDeleteRepo:
    """Tests for DELETE /api/v1/repos/{id}."""

    async def test_delete_repo(self, client: AsyncClient):
        """Soft-delete a repo."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.delete(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 404

    async def test_delete_repo_not_found(self, client: AsyncClient):
        """Deleting a nonexistent repo should 404."""
        resp = await client.delete(f"/api/v1/repos/{_ZERO_UUID}")
        assert resp.status_code == 404

    async def test_delete_repo_idempotent(self, client: AsyncClient):
        """Deleting an already-deleted repo should 404 (soft-delete is filtered)."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.delete(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 204

        resp = await client.delete(f"/api/v1/repos/{repo['id']}")
        assert resp.status_code == 404

    async def test_deleted_repo_name_can_be_reused(self, client: AsyncClient):
        """After soft-deleting, the same name+url can be re-registered."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id, name="reuse-me", git_url="https://reuse.git")

        await client.delete(f"/api/v1/repos/{repo['id']}")

        # Re-create with same name and URL — partial unique indexes should allow this
        data = await _create_repo(client, team_id, name="reuse-me", git_url="https://reuse.git")
        assert data["name"] == "reuse-me"


class TestTriggerSync:
    """Tests for POST /api/v1/repos/{id}/sync."""

    async def test_trigger_sync(self, client: AsyncClient):
        """Trigger sync returns 202."""
        team_id = await _create_team(client)
        repo = await _create_repo(client, team_id)

        resp = await client.post(f"/api/v1/repos/{repo['id']}/sync")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"

    async def test_trigger_sync_not_found(self, client: AsyncClient):
        """Triggering sync on nonexistent repo should 404."""
        resp = await client.post(f"/api/v1/repos/{_ZERO_UUID}/sync")
        assert resp.status_code == 404


class TestFullCrudCycle:
    """Integration test: full create → read → update → delete cycle."""

    async def test_full_lifecycle(self, client: AsyncClient):
        """Walk through the entire CRUD lifecycle."""
        team_id = await _create_team(client)

        # Create
        repo = await _create_repo(
            client,
            team_id,
            name="lifecycle-repo",
            git_url="https://github.com/org/lifecycle.git",
            spec_paths=["v1.yaml"],
        )
        repo_id = repo["id"]

        # Read
        resp = await client.get(f"/api/v1/repos/{repo_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "lifecycle-repo"
        assert resp.json()["services_count"] == 0

        # List
        resp = await client.get("/api/v1/repos")
        assert resp.json()["total"] >= 1

        # Update
        resp = await client.patch(
            f"/api/v1/repos/{repo_id}",
            json={
                "default_branch": "release",
                "spec_paths": ["v1.yaml", "v2.yaml"],
                "sync_enabled": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_branch"] == "release"
        assert data["spec_paths"] == ["v1.yaml", "v2.yaml"]
        assert data["sync_enabled"] is False

        # Trigger sync
        resp = await client.post(f"/api/v1/repos/{repo_id}/sync")
        assert resp.status_code == 202

        # Delete
        resp = await client.delete(f"/api/v1/repos/{repo_id}")
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(f"/api/v1/repos/{repo_id}")
        assert resp.status_code == 404


class TestAuthScopes:
    """Tests that auth scopes are enforced when auth is enabled."""

    @pytest.fixture
    async def auth_client(self, test_engine) -> AsyncGenerator[AsyncClient, None]:
        """Client with auth enabled — all requests without API key should fail."""
        from tessera.config import settings
        from tessera.db import database
        from tessera.main import app

        original_auth_disabled = settings.auth_disabled
        settings.auth_disabled = False

        async with test_engine.begin() as conn:
            if not _USE_SQLITE:
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
            await conn.run_sync(create_tables)

        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
            async with session_maker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[database.get_session] = get_test_session

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c

        app.dependency_overrides.clear()
        settings.auth_disabled = original_auth_disabled

        async with test_engine.begin() as conn:
            await conn.run_sync(drop_tables)

    async def test_list_repos_requires_auth(self, auth_client: AsyncClient):
        """GET /repos without auth should 401."""
        resp = await auth_client.get("/api/v1/repos")
        assert resp.status_code == 401

    async def test_create_repo_requires_auth(self, auth_client: AsyncClient):
        """POST /repos without auth should 401."""
        resp = await auth_client.post(
            "/api/v1/repos",
            json={
                "name": "no-auth",
                "git_url": "https://nope.git",
                "owner_team_id": _ZERO_UUID,
            },
        )
        assert resp.status_code == 401

    async def test_delete_repo_requires_auth(self, auth_client: AsyncClient):
        """DELETE /repos/{id} without auth should 401."""
        resp = await auth_client.delete(f"/api/v1/repos/{_ZERO_UUID}")
        assert resp.status_code == 401

    async def test_trigger_sync_requires_auth(self, auth_client: AsyncClient):
        """POST /repos/{id}/sync without auth should 401."""
        resp = await auth_client.post(f"/api/v1/repos/{_ZERO_UUID}/sync")
        assert resp.status_code == 401
