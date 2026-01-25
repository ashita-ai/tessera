"""Tests for pagination edge cases across list endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Test data: Valid names (no digits, only letters and spaces)
VALID_NAMES = [
    "Alice Anderson",
    "Bob Baker",
    "Carol Chen",
    "David Davis",
    "Eve Evans",
    "Frank Foster",
    "Grace Garcia",
    "Henry Harris",
    "Iris Ibrahim",
    "Jack Johnson",
]


class TestPaginationEdgeCases:
    """Tests for pagination edge cases and boundary conditions."""

    async def test_offset_beyond_total_returns_empty(self, client: AsyncClient):
        """Offset beyond total count returns empty results, not error."""
        # Create 5 users
        for i in range(5):
            await client.post(
                "/api/v1/users",
                json={"email": f"user{i}@example.com", "name": VALID_NAMES[i]},
            )

        # Request with offset beyond total
        resp = await client.get("/api/v1/users?offset=100&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["offset"] == 100
        assert data["limit"] == 10
        assert data["results"] == []

    async def test_maximum_limit_works(self, client: AsyncClient):
        """Maximum limit (100) is accepted and works correctly."""
        # Create more than 100 users would be slow, so create 10 and test max limit
        for i in range(10):
            await client.post(
                "/api/v1/users",
                json={"email": f"user{i}@example.com", "name": VALID_NAMES[i]},
            )

        resp = await client.get("/api/v1/users?limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 100
        assert len(data["results"]) == 10  # Only 10 exist

    async def test_limit_zero_fails_validation(self, client: AsyncClient):
        """Limit of 0 should fail validation."""
        resp = await client.get("/api/v1/users?limit=0")
        assert resp.status_code == 422  # Validation error

    async def test_negative_limit_fails_validation(self, client: AsyncClient):
        """Negative limit should fail validation."""
        resp = await client.get("/api/v1/users?limit=-1")
        assert resp.status_code == 422

    async def test_negative_offset_fails_validation(self, client: AsyncClient):
        """Negative offset should fail validation."""
        resp = await client.get("/api/v1/users?offset=-1")
        assert resp.status_code == 422

    async def test_limit_exceeds_max_fails_validation(self, client: AsyncClient):
        """Limit exceeding maximum (100) should fail validation."""
        resp = await client.get("/api/v1/users?limit=101")
        assert resp.status_code == 422

    async def test_pagination_consistency_users(self, client: AsyncClient):
        """Paginated results are consistent and complete."""
        # Create 10 users
        created_emails = []
        for i in range(10):
            email = f"page{i}@example.com"
            created_emails.append(email)
            await client.post(
                "/api/v1/users",
                json={"email": email, "name": VALID_NAMES[i]},
            )

        # Fetch all via pagination (3 + 3 + 3 + 1)
        all_emails = []
        offset = 0
        limit = 3
        while True:
            resp = await client.get(f"/api/v1/users?limit={limit}&offset={offset}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["limit"] == limit
            assert data["offset"] == offset

            if not data["results"]:
                break

            all_emails.extend([u["email"] for u in data["results"]])
            offset += limit

        # Verify all users retrieved
        assert len(all_emails) == 10
        assert set(all_emails) == set(created_emails)

    async def test_pagination_consistency_teams(self, client: AsyncClient):
        """Pagination consistency for teams list endpoint."""
        # Create 8 teams
        created_names = []
        for i in range(8):
            name = f"page-team-{i}"
            created_names.append(name)
            await client.post("/api/v1/teams", json={"name": name})

        # Fetch all via pagination (5 + 3)
        all_names = []
        offset = 0
        limit = 5
        while True:
            resp = await client.get(f"/api/v1/teams?limit={limit}&offset={offset}")
            assert resp.status_code == 200
            data = resp.json()

            if not data["results"]:
                break

            all_names.extend([t["name"] for t in data["results"]])
            offset += limit

        # Verify all teams retrieved
        assert len(all_names) >= 8
        assert all(name in all_names for name in created_names)

    async def test_pagination_total_count_correct(self, client: AsyncClient):
        """Total count is correct regardless of limit/offset."""
        # Create 7 users
        for i in range(7):
            await client.post(
                "/api/v1/users",
                json={"email": f"count{i}@example.com", "name": VALID_NAMES[i]},
            )

        # Different pagination params should all report total=7
        params = [
            {"limit": 2, "offset": 0},
            {"limit": 5, "offset": 0},
            {"limit": 2, "offset": 5},
            {"limit": 10, "offset": 0},
            {"limit": 1, "offset": 6},
        ]

        for param in params:
            resp = await client.get(
                f"/api/v1/users?limit={param['limit']}&offset={param['offset']}"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 7, f"Failed for params {param}"

    async def test_empty_list_pagination(self, client: AsyncClient):
        """Pagination works correctly on empty results."""
        resp = await client.get("/api/v1/users?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["limit"] == 10
        assert data["offset"] == 0
        assert data["results"] == []

    async def test_single_result_pagination(self, client: AsyncClient):
        """Pagination works with exactly one result."""
        await client.post(
            "/api/v1/users",
            json={"email": "single@example.com", "name": "Single User"},
        )

        resp = await client.get("/api/v1/users?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["results"]) == 1

        # Offset 1 should be empty
        resp = await client.get("/api/v1/users?limit=10&offset=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["results"]) == 0


class TestPaginationWithFilters:
    """Test pagination combined with filters."""

    async def test_pagination_with_filter_consistency(self, client: AsyncClient):
        """Pagination + filtering returns consistent results."""
        team_resp = await client.post("/api/v1/teams", json={"name": "filtered-team"})
        team_id = team_resp.json()["id"]

        # Create 6 users in team, 4 outside
        for i in range(6):
            await client.post(
                "/api/v1/users",
                json={"email": f"in{i}@team.com", "name": VALID_NAMES[i], "team_id": team_id},
            )
        for i in range(4):
            await client.post(
                "/api/v1/users",
                json={"email": f"out{i}@other.com", "name": VALID_NAMES[i + 6]},
            )

        # Paginate filtered results
        resp1 = await client.get(f"/api/v1/users?team_id={team_id}&limit=3&offset=0")
        resp2 = await client.get(f"/api/v1/users?team_id={team_id}&limit=3&offset=3")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1 = resp1.json()
        data2 = resp2.json()

        # Total should be 6 for filtered query
        assert data1["total"] == 6
        assert data2["total"] == 6

        # First page has 3 results, second page has 3
        assert len(data1["results"]) == 3
        assert len(data2["results"]) == 3

        # All results belong to the team
        all_results = data1["results"] + data2["results"]
        assert all(u["team_id"] == team_id for u in all_results)
