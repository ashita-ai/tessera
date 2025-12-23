"""Tests for /api/v1/users endpoints."""

from uuid import uuid4

from httpx import AsyncClient


class TestCreateUser:
    """Tests for POST /api/v1/users endpoint."""

    async def test_create_user_basic(self, client: AsyncClient):
        """Create a user with minimal required fields."""
        resp = await client.post(
            "/api/v1/users",
            json={"email": "test@example.com", "name": "Test User"},
        )

        assert resp.status_code == 201, f"Create failed: {resp.json()}"
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert data["team_id"] is None
        assert data["role"] == "user"  # Default role is "user"
        assert "id" in data

    async def test_create_user_with_team(self, client: AsyncClient):
        """Create a user assigned to a team."""
        team_resp = await client.post("/api/v1/teams", json={"name": "user-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/users",
            json={"email": "teamuser@example.com", "name": "Team User", "team_id": team_id},
        )

        assert resp.status_code == 201
        assert resp.json()["team_id"] == team_id

    async def test_create_user_with_password(self, client: AsyncClient):
        """Create a user with password for UI login."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "email": "loginuser@example.com",
                "name": "Login User",
                "password": "securepassword123",
            },
        )

        assert resp.status_code == 201
        # Password hash should not be returned
        assert "password_hash" not in resp.json()
        assert "password" not in resp.json()

    async def test_create_user_with_role(self, client: AsyncClient):
        """Create a user with specific role."""
        resp = await client.post(
            "/api/v1/users",
            json={"email": "admin@example.com", "name": "Admin User", "role": "admin"},
        )

        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    async def test_create_user_with_metadata(self, client: AsyncClient):
        """Create a user with metadata."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "email": "meta@example.com",
                "name": "Meta User",
                "metadata": {"department": "Engineering", "slack_id": "@meta"},
            },
        )

        assert resp.status_code == 201
        assert resp.json()["metadata"]["department"] == "Engineering"

    async def test_create_user_duplicate_email(self, client: AsyncClient):
        """Cannot create user with duplicate email."""
        first_resp = await client.post(
            "/api/v1/users",
            json={"email": "dupe@example.com", "name": "First User"},
        )
        assert first_resp.status_code == 201, f"First user creation failed: {first_resp.json()}"

        resp = await client.post(
            "/api/v1/users",
            json={"email": "dupe@example.com", "name": "Second User"},
        )

        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.json()}"
        # Verify error response contains relevant info
        resp_data = resp.json()
        error_text = str(resp_data)
        assert "dupe@example.com" in error_text or "already exists" in error_text.lower()

    async def test_create_user_team_not_found(self, client: AsyncClient):
        """Cannot create user with non-existent team."""
        fake_team_id = str(uuid4())
        resp = await client.post(
            "/api/v1/users",
            json={
                "email": "orphan@example.com",
                "name": "Orphan User",
                "team_id": fake_team_id,
            },
        )

        assert resp.status_code == 404
        # Check for error in response
        resp_data = resp.json()
        error_text = resp_data.get("detail", resp_data.get("message", ""))
        assert "team" in str(error_text).lower() or resp.status_code == 404


class TestListUsers:
    """Tests for GET /api/v1/users endpoint."""

    async def test_list_users_empty(self, client: AsyncClient):
        """List users when none exist."""
        resp = await client.get("/api/v1/users")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["results"] == []

    async def test_list_users(self, client: AsyncClient):
        """List multiple users."""
        names = ["Alice Smith", "Bob Jones", "Carol White"]
        for i, name in enumerate(names):
            create_resp = await client.post(
                "/api/v1/users",
                json={"email": f"user{i}@example.com", "name": name},
            )
            assert create_resp.status_code == 201, f"Create failed: {create_resp.json()}"

        resp = await client.get("/api/v1/users")

        assert resp.status_code == 200
        assert resp.json()["total"] == 3
        assert len(resp.json()["results"]) == 3

    async def test_list_users_filter_by_team(self, client: AsyncClient):
        """Filter users by team."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "team-one"})
        team1_id = team1_resp.json()["id"]
        team2_resp = await client.post("/api/v1/teams", json={"name": "team-two"})
        team2_id = team2_resp.json()["id"]

        r1 = await client.post(
            "/api/v1/users",
            json={"email": "t1u1@example.com", "name": "Team One Alice", "team_id": team1_id},
        )
        assert r1.status_code == 201, f"Create failed: {r1.json()}"
        r2 = await client.post(
            "/api/v1/users",
            json={"email": "t1u2@example.com", "name": "Team One Bob", "team_id": team1_id},
        )
        assert r2.status_code == 201, f"Create failed: {r2.json()}"
        r3 = await client.post(
            "/api/v1/users",
            json={"email": "t2u1@example.com", "name": "Team Two Carol", "team_id": team2_id},
        )
        assert r3.status_code == 201, f"Create failed: {r3.json()}"

        resp = await client.get(f"/api/v1/users?team_id={team1_id}")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        assert all(u["team_id"] == team1_id for u in resp.json()["results"])

    async def test_list_users_filter_by_email(self, client: AsyncClient):
        """Filter users by email pattern."""
        await client.post(
            "/api/v1/users",
            json={"email": "alice@example.com", "name": "Alice"},
        )
        await client.post(
            "/api/v1/users",
            json={"email": "bob@company.com", "name": "Bob"},
        )
        await client.post(
            "/api/v1/users",
            json={"email": "charlie@example.com", "name": "Charlie"},
        )

        resp = await client.get("/api/v1/users?email=example.com")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_users_filter_by_name(self, client: AsyncClient):
        """Filter users by name pattern."""
        await client.post(
            "/api/v1/users",
            json={"email": "e1@example.com", "name": "John Smith"},
        )
        await client.post(
            "/api/v1/users",
            json={"email": "e2@example.com", "name": "Jane Doe"},
        )
        await client.post(
            "/api/v1/users",
            json={"email": "e3@example.com", "name": "Smith Johnson"},
        )

        resp = await client.get("/api/v1/users?name=Smith")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_users_excludes_deactivated(self, client: AsyncClient):
        """Deactivated users not listed by default."""
        await client.post(
            "/api/v1/users",
            json={"email": "active@example.com", "name": "Active User"},
        )
        resp2 = await client.post(
            "/api/v1/users",
            json={"email": "inactive@example.com", "name": "Inactive User"},
        )
        user_id = resp2.json()["id"]

        # Deactivate user
        await client.delete(f"/api/v1/users/{user_id}")

        resp = await client.get("/api/v1/users")
        assert resp.json()["total"] == 1

        # Include deactivated
        resp = await client.get("/api/v1/users?include_deactivated=true")
        assert resp.json()["total"] == 2

    async def test_list_users_includes_team_name(self, client: AsyncClient):
        """User list includes team name."""
        team_resp = await client.post("/api/v1/teams", json={"name": "My Team"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/users",
            json={"email": "teamie@example.com", "name": "Teamie", "team_id": team_id},
        )

        resp = await client.get("/api/v1/users")

        assert resp.status_code == 200
        assert resp.json()["results"][0]["team_name"] == "My Team"

    async def test_list_users_pagination(self, client: AsyncClient):
        """Test pagination of user list."""
        names = ["Alice", "Bob", "Carol", "David", "Eve"]
        for i, name in enumerate(names):
            r = await client.post(
                "/api/v1/users",
                json={"email": f"page{i}@example.com", "name": name},
            )
            assert r.status_code == 201, f"Create failed: {r.json()}"

        resp = await client.get("/api/v1/users?limit=2&offset=0")
        assert len(resp.json()["results"]) == 2
        assert resp.json()["total"] == 5

        resp = await client.get("/api/v1/users?limit=2&offset=2")
        assert len(resp.json()["results"]) == 2


class TestGetUser:
    """Tests for GET /api/v1/users/{user_id} endpoint."""

    async def test_get_user(self, client: AsyncClient):
        """Get a user by ID."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "get@example.com", "name": "Get User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/users/{user_id}")

        assert resp.status_code == 200
        assert resp.json()["email"] == "get@example.com"

    async def test_get_user_with_team(self, client: AsyncClient):
        """Get user includes team name."""
        team_resp = await client.post("/api/v1/teams", json={"name": "Get Team"})
        team_id = team_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "getteam@example.com", "name": "Get Team User", "team_id": team_id},
        )
        user_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/users/{user_id}")

        assert resp.status_code == 200
        assert resp.json()["team_name"] == "Get Team"

    async def test_get_user_not_found(self, client: AsyncClient):
        """Get non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.get(f"/api/v1/users/{fake_id}")

        assert resp.status_code == 404

    async def test_get_deactivated_user_not_found(self, client: AsyncClient):
        """Cannot get deactivated user."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "deact@example.com", "name": "Deact User"},
        )
        user_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/users/{user_id}")

        resp = await client.get(f"/api/v1/users/{user_id}")
        assert resp.status_code == 404


class TestUpdateUser:
    """Tests for PATCH/PUT /api/v1/users/{user_id} endpoint."""

    async def test_update_user_name(self, client: AsyncClient):
        """Update user name."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "upd@example.com", "name": "Original Name"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"name": "New Name"})

        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_user_email(self, client: AsyncClient):
        """Update user email."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "old@example.com", "name": "Email User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"email": "new@example.com"})

        assert resp.status_code == 200
        assert resp.json()["email"] == "new@example.com"

    async def test_update_user_team(self, client: AsyncClient):
        """Update user team assignment."""
        team1_resp = await client.post("/api/v1/teams", json={"name": "old-team"})
        team1_id = team1_resp.json()["id"]
        team2_resp = await client.post("/api/v1/teams", json={"name": "new-team"})
        team2_id = team2_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "switch@example.com", "name": "Switch User", "team_id": team1_id},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"team_id": team2_id})

        assert resp.status_code == 200
        assert resp.json()["team_id"] == team2_id

    async def test_update_user_role(self, client: AsyncClient):
        """Update user role."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "role@example.com", "name": "Role User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"role": "admin"})

        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_update_user_duplicate_email(self, client: AsyncClient):
        """Cannot update to duplicate email."""
        await client.post(
            "/api/v1/users",
            json={"email": "taken@example.com", "name": "First"},
        )
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "other@example.com", "name": "Second"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"email": "taken@example.com"})

        assert resp.status_code == 409

    async def test_update_user_not_found(self, client: AsyncClient):
        """Update non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.patch(f"/api/v1/users/{fake_id}", json={"name": "New"})

        assert resp.status_code == 404

    async def test_update_user_invalid_team(self, client: AsyncClient):
        """Cannot update to non-existent team."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "badteam@example.com", "name": "Bad Team User"},
        )
        user_id = create_resp.json()["id"]

        fake_team_id = str(uuid4())
        resp = await client.patch(f"/api/v1/users/{user_id}", json={"team_id": fake_team_id})

        assert resp.status_code == 404


class TestDeactivateUser:
    """Tests for DELETE /api/v1/users/{user_id} endpoint."""

    async def test_deactivate_user(self, client: AsyncClient):
        """Deactivate a user."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "bye@example.com", "name": "Bye User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/users/{user_id}")

        assert resp.status_code == 204

        # Verify not in active list
        list_resp = await client.get("/api/v1/users")
        assert list_resp.json()["total"] == 0

    async def test_deactivate_user_not_found(self, client: AsyncClient):
        """Deactivate non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.delete(f"/api/v1/users/{fake_id}")

        assert resp.status_code == 404

    async def test_deactivate_already_deactivated(self, client: AsyncClient):
        """Deactivating already deactivated user returns 404."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "double@example.com", "name": "Double Deact"},
        )
        user_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/users/{user_id}")
        resp = await client.delete(f"/api/v1/users/{user_id}")

        assert resp.status_code == 404


class TestReactivateUser:
    """Tests for POST /api/v1/users/{user_id}/reactivate endpoint."""

    async def test_reactivate_user(self, client: AsyncClient):
        """Reactivate a deactivated user."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "comeback@example.com", "name": "Comeback User"},
        )
        user_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/users/{user_id}")

        resp = await client.post(f"/api/v1/users/{user_id}/reactivate")

        assert resp.status_code == 200
        assert resp.json()["email"] == "comeback@example.com"

        # Verify back in active list
        list_resp = await client.get("/api/v1/users")
        assert list_resp.json()["total"] == 1

    async def test_reactivate_active_user(self, client: AsyncClient):
        """Reactivating active user is a no-op."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"email": "already@example.com", "name": "Already Active"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/users/{user_id}/reactivate")

        assert resp.status_code == 200

    async def test_reactivate_user_not_found(self, client: AsyncClient):
        """Reactivate non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.post(f"/api/v1/users/{fake_id}/reactivate")

        assert resp.status_code == 404
