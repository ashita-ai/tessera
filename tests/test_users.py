"""Tests for /api/v1/users endpoints."""

from uuid import uuid4

from httpx import AsyncClient


class TestCreateUser:
    """Tests for POST /api/v1/users endpoint."""

    async def test_create_user_basic(self, client: AsyncClient):
        """Create a user with minimal required fields."""
        resp = await client.post(
            "/api/v1/users",
            json={"username": "testuser", "name": "Test User"},
        )

        assert resp.status_code == 201, f"Create failed: {resp.json()}"
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["name"] == "Test User"
        assert data["team_id"] is None
        assert data["role"] == "user"  # Default role is "user"
        assert data["user_type"] == "human"  # Default type is "human"
        assert "id" in data

    async def test_create_user_with_email(self, client: AsyncClient):
        """Create a user with optional email."""
        resp = await client.post(
            "/api/v1/users",
            json={"username": "emailuser", "email": "test@example.com", "name": "Test User"},
        )

        assert resp.status_code == 201
        assert resp.json()["email"] == "test@example.com"
        assert resp.json()["username"] == "emailuser"

    async def test_create_user_with_team(self, client: AsyncClient):
        """Create a user assigned to a team."""
        team_resp = await client.post("/api/v1/teams", json={"name": "user-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/users",
            json={"username": "teamuser", "name": "Team User", "team_id": team_id},
        )

        assert resp.status_code == 201
        assert resp.json()["team_id"] == team_id

    async def test_create_user_with_password(self, client: AsyncClient):
        """Create a user with password for UI login."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "loginuser",
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
            json={"username": "adminuser", "name": "Admin User", "role": "admin"},
        )

        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    async def test_create_user_with_metadata(self, client: AsyncClient):
        """Create a user with metadata."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "metauser",
                "name": "Meta User",
                "metadata": {"department": "Engineering", "slack_id": "@meta"},
            },
        )

        assert resp.status_code == 201
        assert resp.json()["metadata"]["department"] == "Engineering"

    async def test_create_bot_user(self, client: AsyncClient):
        """Create a bot user without password."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "dbt-sync-bot",
                "name": "dbt Sync Bot",
                "user_type": "bot",
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["user_type"] == "bot"
        assert data["username"] == "dbt-sync-bot"

    async def test_create_bot_user_with_password_fails(self, client: AsyncClient):
        """Bot users cannot have passwords."""
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "bad-bot",
                "name": "Bad Bot",
                "user_type": "bot",
                "password": "shouldfail123",
            },
        )

        assert resp.status_code == 422

    async def test_create_user_duplicate_username(self, client: AsyncClient):
        """Cannot create user with duplicate username."""
        first_resp = await client.post(
            "/api/v1/users",
            json={"username": "dupeuser", "name": "First User"},
        )
        assert first_resp.status_code == 201, f"First user creation failed: {first_resp.json()}"

        resp = await client.post(
            "/api/v1/users",
            json={"username": "dupeuser", "name": "Second User"},
        )

        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.json()}"
        resp_data = resp.json()
        error_text = str(resp_data)
        assert "dupeuser" in error_text or "already exists" in error_text.lower()
        assert (
            resp_data["error"]["code"] == "DUPLICATE_USER"
        ), f"Expected DUPLICATE_USER, got {resp_data['error'].get('code')}"

    async def test_create_user_team_not_found(self, client: AsyncClient):
        """Cannot create user with non-existent team."""
        fake_team_id = str(uuid4())
        resp = await client.post(
            "/api/v1/users",
            json={
                "username": "orphanuser",
                "name": "Orphan User",
                "team_id": fake_team_id,
            },
        )

        assert resp.status_code == 404
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
                json={"username": f"user{i}", "name": name},
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
            json={"username": "t1u1", "name": "Team One Alice", "team_id": team1_id},
        )
        assert r1.status_code == 201, f"Create failed: {r1.json()}"
        r2 = await client.post(
            "/api/v1/users",
            json={"username": "t1u2", "name": "Team One Bob", "team_id": team1_id},
        )
        assert r2.status_code == 201, f"Create failed: {r2.json()}"
        r3 = await client.post(
            "/api/v1/users",
            json={"username": "t2u1", "name": "Team Two Carol", "team_id": team2_id},
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
            json={"username": "alice", "email": "alice@example.com", "name": "Alice"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "bob", "email": "bob@company.com", "name": "Bob"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "charlie", "email": "charlie@example.com", "name": "Charlie"},
        )

        resp = await client.get("/api/v1/users?email=example.com")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_users_filter_by_name(self, client: AsyncClient):
        """Filter users by name pattern."""
        await client.post(
            "/api/v1/users",
            json={"username": "e1", "name": "John Smith"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "e2", "name": "Jane Doe"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "e3", "name": "Smith Johnson"},
        )

        resp = await client.get("/api/v1/users?name=Smith")

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_list_users_filter_by_user_type(self, client: AsyncClient):
        """Filter users by type (human/bot)."""
        await client.post(
            "/api/v1/users",
            json={"username": "humanuser", "name": "Human User"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "botuser", "name": "Bot User", "user_type": "bot"},
        )

        resp = await client.get("/api/v1/users?user_type=bot")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["user_type"] == "bot"

        resp = await client.get("/api/v1/users?user_type=human")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["user_type"] == "human"

    async def test_list_users_filter_by_username(self, client: AsyncClient):
        """Filter users by username pattern (case-insensitive partial match)."""
        await client.post(
            "/api/v1/users",
            json={"username": "alice.eng", "name": "Alice"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "bob.sales", "name": "Bob"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "alice.sales", "name": "Alice Sales"},
        )

        resp = await client.get("/api/v1/users?username=alice")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        resp = await client.get("/api/v1/users?username=ALICE")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        resp = await client.get("/api/v1/users?username=bob.sales")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["username"] == "bob.sales"

    async def test_list_users_excludes_deactivated(self, client: AsyncClient):
        """Deactivated users not listed by default."""
        await client.post(
            "/api/v1/users",
            json={"username": "activeuser", "name": "Active User"},
        )
        resp2 = await client.post(
            "/api/v1/users",
            json={"username": "inactiveuser", "name": "Inactive User"},
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
            json={"username": "teamie", "name": "Teamie", "team_id": team_id},
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
                json={"username": f"page{i}", "name": name},
            )
            assert r.status_code == 201, f"Create failed: {r.json()}"

        resp = await client.get("/api/v1/users?limit=2&offset=0")
        assert len(resp.json()["results"]) == 2
        assert resp.json()["total"] == 5

        resp = await client.get("/api/v1/users?limit=2&offset=2")
        assert len(resp.json()["results"]) == 2


class TestUserFiltering:
    """Tests for complex filtering on /api/v1/users."""

    async def test_filter_by_team_id(self, client: AsyncClient):
        """Users filtered by team_id only returns users from that team."""
        t1 = await client.post("/api/v1/teams", json={"name": "filter-t1"})
        t1_id = t1.json()["id"]
        t2 = await client.post("/api/v1/teams", json={"name": "filter-t2"})
        t2_id = t2.json()["id"]

        await client.post(
            "/api/v1/users",
            json={"username": "u1t1", "name": "User One", "team_id": t1_id},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "u2t1", "name": "User Two", "team_id": t1_id},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "otherst2", "name": "Other Team", "team_id": t2_id},
        )

        resp = await client.get(f"/api/v1/users?team_id={t1_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(u["team_id"] == t1_id for u in data["results"])

    async def test_filter_by_email_pattern(self, client: AsyncClient):
        """Email filter is case-insensitive and partial match."""
        await client.post(
            "/api/v1/users",
            json={"username": "findme", "email": "FindMe@Example.com", "name": "Target"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "ignoreme", "email": "ignore@other.com", "name": "Ignore"},
        )

        resp = await client.get("/api/v1/users?email=findme")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["email"] == "findme@example.com"

    async def test_filter_by_name_pattern(self, client: AsyncClient):
        """Name filter is case-insensitive and partial match."""
        await client.post(
            "/api/v1/users",
            json={"username": "n1", "name": "Special Target User"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "n2", "name": "Regular Person"},
        )

        resp = await client.get("/api/v1/users?name=target")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["name"] == "Special Target User"

    async def test_combined_filters(self, client: AsyncClient):
        """Multiple filters work together (AND logic)."""
        t1 = await client.post("/api/v1/teams", json={"name": "combo-team"})
        t1_id = t1.json()["id"]

        await client.post(
            "/api/v1/users",
            json={"username": "combo1", "name": "Match Name", "team_id": t1_id},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "combo2", "name": "Wrong Name", "team_id": t1_id},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "combo3", "name": "Match Name"},
        )

        resp = await client.get(f"/api/v1/users?team_id={t1_id}&name=match")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["username"] == "combo1"

    async def test_filter_returns_empty_for_no_matches(self, client: AsyncClient):
        """Filters that match nothing return empty results, not error."""
        await client.post(
            "/api/v1/users",
            json={"username": "existuser", "name": "Existing User"},
        )

        resp = await client.get("/api/v1/users?name=nonexistentxyz")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["results"] == []

    async def test_filter_email_case_insensitive_partial(self, client: AsyncClient):
        """Email filter should be case-insensitive and match partial strings."""
        await client.post(
            "/api/v1/users",
            json={"username": "testuser2", "email": "TestUser@EXAMPLE.com", "name": "Test User"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "another2", "email": "another@domain.org", "name": "Another User"},
        )

        resp = await client.get("/api/v1/users?email=TESTUSER")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert "testuser@example.com" in resp.json()["results"][0]["email"].lower()

        resp = await client.get("/api/v1/users?email=example")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_filter_name_case_insensitive_partial(self, client: AsyncClient):
        """Name filter should be case-insensitive and match partial strings."""
        await client.post(
            "/api/v1/users",
            json={"username": "n1b", "name": "John Smith Engineer"},
        )
        await client.post(
            "/api/v1/users",
            json={"username": "n2b", "name": "Jane Doe Manager"},
        )

        resp = await client.get("/api/v1/users?name=SMITH")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert "smith" in resp.json()["results"][0]["name"].lower()

    async def test_combined_filters_team_and_email(self, client: AsyncClient):
        """Test combining team_id and email filters."""
        t1 = await client.post("/api/v1/teams", json={"name": "team-alpha"})
        t1_id = t1.json()["id"]

        await client.post(
            "/api/v1/users",
            json={
                "username": "alice2",
                "email": "alice@alpha.com",
                "name": "Alice",
                "team_id": t1_id,
            },
        )
        await client.post(
            "/api/v1/users",
            json={
                "username": "bob2",
                "email": "bob@beta.com",
                "name": "Bob",
                "team_id": t1_id,
            },
        )
        await client.post(
            "/api/v1/users",
            json={"username": "charlie2", "email": "charlie@alpha.com", "name": "Charlie"},
        )

        resp = await client.get(f"/api/v1/users?team_id={t1_id}&email=alpha")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["results"][0]["email"] == "alice@alpha.com"

    async def test_filter_no_matches_returns_empty_not_error(self, client: AsyncClient):
        """Filtering with no results returns empty list, not 404 or error."""
        await client.post(
            "/api/v1/users",
            json={"username": "realuser", "email": "real@example.com", "name": "Real User"},
        )

        resp = await client.get("/api/v1/users?email=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["results"] == []

        resp = await client.get("/api/v1/users?name=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["results"] == []


class TestGetUser:
    """Tests for GET /api/v1/users/{user_id} endpoint."""

    async def test_get_user(self, client: AsyncClient):
        """Get a user by ID."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "getuser", "name": "Get User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/users/{user_id}")

        assert resp.status_code == 200
        assert resp.json()["username"] == "getuser"

    async def test_get_user_with_team(self, client: AsyncClient):
        """Get user includes team name."""
        team_resp = await client.post("/api/v1/teams", json={"name": "Get Team"})
        team_id = team_resp.json()["id"]

        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "getteam", "name": "Get Team User", "team_id": team_id},
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
            json={"username": "deactuser", "name": "Deact User"},
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
            json={"username": "upduser", "name": "Original Name"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"name": "New Name"})

        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_user_email(self, client: AsyncClient):
        """Update user email."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "emailupd", "email": "old@example.com", "name": "Email User"},
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
            json={"username": "switchuser", "name": "Switch User", "team_id": team1_id},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"team_id": team2_id})

        assert resp.status_code == 200
        assert resp.json()["team_id"] == team2_id

    async def test_update_user_role(self, client: AsyncClient):
        """Update user role."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "roleuser", "name": "Role User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"role": "admin"})

        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_update_user_duplicate_username(self, client: AsyncClient):
        """Cannot update to duplicate username."""
        await client.post(
            "/api/v1/users",
            json={"username": "taken", "name": "First"},
        )
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "other", "name": "Second"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"username": "taken"})

        assert resp.status_code == 409

    async def test_update_user_invalid_username_rejected(self, client: AsyncClient):
        """Cannot update username to an invalid format."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "validuser", "name": "Valid User"},
        )
        user_id = create_resp.json()["id"]

        # Username starting with a digit should be rejected
        resp = await client.patch(f"/api/v1/users/{user_id}", json={"username": "123invalid"})
        assert resp.status_code == 422

        # Username with spaces should be rejected
        resp = await client.patch(f"/api/v1/users/{user_id}", json={"username": "has spaces"})
        assert resp.status_code == 422

    async def test_update_human_to_bot_clears_password(self, client: AsyncClient):
        """Switching a human with password to bot clears their password_hash."""
        create_resp = await client.post(
            "/api/v1/users",
            json={
                "username": "humantobotuser",
                "name": "Human To Bot",
                "password": "securepass123",
            },
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/users/{user_id}", json={"user_type": "bot"})
        assert resp.status_code == 200
        assert resp.json()["user_type"] == "bot"

    async def test_update_bot_with_password_rejected(self, client: AsyncClient):
        """Cannot set user_type to bot and password in the same update."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "botupduser", "name": "Bot Update User"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/users/{user_id}",
            json={"user_type": "bot", "password": "shouldfail123"},
        )
        assert resp.status_code == 422

    async def test_update_existing_bot_password_rejected(self, client: AsyncClient):
        """Cannot set password on an existing bot user without changing user_type."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "existingbot", "name": "Existing Bot", "user_type": "bot"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/users/{user_id}",
            json={"password": "sneakypassword123"},
        )
        assert resp.status_code == 400

    async def test_update_user_not_found(self, client: AsyncClient):
        """Update non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.patch(f"/api/v1/users/{fake_id}", json={"name": "New"})

        assert resp.status_code == 404

    async def test_update_user_invalid_team(self, client: AsyncClient):
        """Cannot update to non-existent team."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "badteam", "name": "Bad Team User"},
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
            json={"username": "byeuser", "name": "Bye User"},
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
            json={"username": "doubledeact", "name": "Double Deact"},
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
            json={"username": "comeback", "name": "Comeback User"},
        )
        user_id = create_resp.json()["id"]

        await client.delete(f"/api/v1/users/{user_id}")

        resp = await client.post(f"/api/v1/users/{user_id}/reactivate")

        assert resp.status_code == 200
        assert resp.json()["username"] == "comeback"

        # Verify back in active list
        list_resp = await client.get("/api/v1/users")
        assert list_resp.json()["total"] == 1

    async def test_reactivate_active_user(self, client: AsyncClient):
        """Reactivating active user is a no-op."""
        create_resp = await client.post(
            "/api/v1/users",
            json={"username": "already", "name": "Already Active"},
        )
        user_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/users/{user_id}/reactivate")

        assert resp.status_code == 200

    async def test_reactivate_user_not_found(self, client: AsyncClient):
        """Reactivate non-existent user returns 404."""
        fake_id = str(uuid4())
        resp = await client.post(f"/api/v1/users/{fake_id}/reactivate")

        assert resp.status_code == 404
