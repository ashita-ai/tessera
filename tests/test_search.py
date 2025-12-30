"""Tests for global search API endpoint."""

from httpx import AsyncClient


class TestSearchEndpoint:
    """Tests for /api/v1/search endpoint."""

    async def test_search_requires_query(self, client: AsyncClient):
        """Search requires a query parameter."""
        response = await client.get("/api/v1/search")
        assert response.status_code == 422

    async def test_search_returns_structure(self, client: AsyncClient):
        """Search returns proper structure with empty results."""
        response = await client.get("/api/v1/search?q=nonexistent12345")
        assert response.status_code == 200

        data = response.json()
        assert "query" in data
        assert data["query"] == "nonexistent12345"
        assert "results" in data
        assert "counts" in data
        assert set(data["results"].keys()) == {"teams", "users", "assets", "contracts"}
        assert set(data["counts"].keys()) == {"teams", "users", "assets", "contracts", "total"}

    async def test_search_finds_teams(self, client: AsyncClient):
        """Search finds teams by name."""
        # Create a team
        team_resp = await client.post("/api/v1/teams", json={"name": "SearchTestTeam"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # Search for it
        response = await client.get("/api/v1/search?q=SearchTest")
        assert response.status_code == 200

        data = response.json()
        assert data["counts"]["teams"] >= 1
        team_ids = [t["id"] for t in data["results"]["teams"]]
        assert team_id in team_ids

    async def test_search_finds_users_by_name(self, client: AsyncClient):
        """Search finds users by name."""
        # Create a user
        user_resp = await client.post(
            "/api/v1/users", json={"name": "SearchableUser", "email": "searchable@test.com"}
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        # Search by name
        response = await client.get("/api/v1/search?q=Searchable")
        assert response.status_code == 200

        data = response.json()
        assert data["counts"]["users"] >= 1
        user_ids = [u["id"] for u in data["results"]["users"]]
        assert user_id in user_ids

    async def test_search_finds_users_by_email(self, client: AsyncClient):
        """Search finds users by email."""
        # Create a user
        user_resp = await client.post(
            "/api/v1/users", json={"name": "EmailUser", "email": "uniqueemail123@test.com"}
        )
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        # Search by email
        response = await client.get("/api/v1/search?q=uniqueemail123")
        assert response.status_code == 200

        data = response.json()
        assert data["counts"]["users"] >= 1
        user_ids = [u["id"] for u in data["results"]["users"]]
        assert user_id in user_ids

    async def test_search_finds_assets(self, client: AsyncClient):
        """Search finds assets by FQN."""
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "AssetSearchTeam"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "searchable.schema.my_model_xyz", "owner_team_id": team_id},
        )
        assert asset_resp.status_code == 201
        asset_id = asset_resp.json()["id"]

        # Search by FQN
        response = await client.get("/api/v1/search?q=my_model_xyz")
        assert response.status_code == 200

        data = response.json()
        assert data["counts"]["assets"] >= 1
        asset_ids = [a["id"] for a in data["results"]["assets"]]
        assert asset_id in asset_ids

    async def test_search_case_insensitive(self, client: AsyncClient):
        """Search is case-insensitive."""
        team_resp = await client.post("/api/v1/teams", json={"name": "CaseTeamTest"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # Search with different case
        response = await client.get("/api/v1/search?q=caseteamtest")
        assert response.status_code == 200

        data = response.json()
        assert data["counts"]["teams"] >= 1
        team_ids = [t["id"] for t in data["results"]["teams"]]
        assert team_id in team_ids

    async def test_search_respects_limit(self, client: AsyncClient):
        """Search respects the limit parameter."""
        # Create multiple teams
        for i in range(5):
            await client.post("/api/v1/teams", json={"name": f"LimitTestTeam{i}"})

        # Search with limit
        response = await client.get("/api/v1/search?q=LimitTestTeam&limit=2")
        assert response.status_code == 200

        data = response.json()
        assert len(data["results"]["teams"]) <= 2

    async def test_search_filters_entity_types(self, client: AsyncClient):
        """Search can limit results to specific entity types."""
        team_resp = await client.post("/api/v1/teams", json={"name": "TypeFilterTeam"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        user_resp = await client.post(
            "/api/v1/users", json={"name": "TypeFilterUser", "email": "typefilter@test.com"}
        )
        assert user_resp.status_code == 201

        response = await client.get("/api/v1/search?q=TypeFilter&types=teams")
        assert response.status_code == 200

        data = response.json()
        team_ids = [t["id"] for t in data["results"]["teams"]]
        assert team_id in team_ids
        assert data["results"]["users"] == []
        assert data["results"]["assets"] == []
        assert data["results"]["contracts"] == []

    async def test_search_limit_validation(self, client: AsyncClient):
        """Search validates limit parameter."""
        # Too high
        response = await client.get("/api/v1/search?q=test&limit=100")
        assert response.status_code == 422

        # Too low
        response = await client.get("/api/v1/search?q=test&limit=0")
        assert response.status_code == 422

    async def test_search_type_validation(self, client: AsyncClient):
        """Search validates entity types parameter."""
        response = await client.get("/api/v1/search?q=test&types=widgets")
        assert response.status_code == 422

    async def test_search_partial_match(self, client: AsyncClient):
        """Search matches partial strings."""
        team_resp = await client.post("/api/v1/teams", json={"name": "PartialMatchTeam"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        # Search with partial term
        response = await client.get("/api/v1/search?q=Match")
        assert response.status_code == 200

        data = response.json()
        team_ids = [t["id"] for t in data["results"]["teams"]]
        assert team_id in team_ids

    async def test_search_excludes_deleted_teams(self, client: AsyncClient):
        """Search excludes soft-deleted teams."""
        # Create and delete a team
        team_resp = await client.post("/api/v1/teams", json={"name": "DeletedSearchTeam"})
        team_id = team_resp.json()["id"]

        # Delete the team
        await client.delete(f"/api/v1/teams/{team_id}")

        # Search should not find it
        response = await client.get("/api/v1/search?q=DeletedSearch")
        assert response.status_code == 200

        data = response.json()
        team_ids = [t["id"] for t in data["results"]["teams"]]
        assert team_id not in team_ids

    async def test_search_excludes_deleted_assets(self, client: AsyncClient):
        """Search excludes soft-deleted assets."""
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "AssetDeleteTeam"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "deleted.search.test_asset", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Delete the asset
        await client.delete(f"/api/v1/assets/{asset_id}")

        # Search should not find it
        response = await client.get("/api/v1/search?q=deleted.search.test_asset")
        assert response.status_code == 200

        data = response.json()
        asset_ids = [a["id"] for a in data["results"]["assets"]]
        assert asset_id not in asset_ids

    async def test_search_uses_cache(self, client: AsyncClient, monkeypatch):
        """Search returns cached results when available."""
        from tessera.api import search as search_module

        cached = {
            "query": "cached",
            "results": {"teams": [], "users": [], "assets": [], "contracts": []},
            "counts": {"teams": 0, "users": 0, "assets": 0, "contracts": 0, "total": 0},
        }

        async def fake_get_cached_global_search(_q: str, _limit: int):
            return cached

        async def fake_cache_global_search(_q: str, _limit: int, _results: dict):
            return True

        monkeypatch.setattr(
            search_module,
            "get_cached_global_search",
            fake_get_cached_global_search,
        )
        monkeypatch.setattr(search_module, "cache_global_search", fake_cache_global_search)

        response = await client.get("/api/v1/search?q=cached")
        assert response.status_code == 200
        assert response.json() == cached
