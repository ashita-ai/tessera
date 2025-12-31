"""Tests for semantic versioning enforcement (Issue #19)."""

from httpx import AsyncClient

from tests.conftest import make_asset, make_schema, make_team


class TestSemverModes:
    """Test semantic versioning enforcement modes."""

    async def test_create_asset_with_default_semver_mode(self, client: AsyncClient):
        """Assets default to AUTO semver mode."""
        # Create team
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        assert resp.status_code == 201
        team_id = resp.json()["id"]

        # Create asset (no explicit semver_mode)
        resp = await client.post(
            "/api/v1/assets",
            json=make_asset("db.schema.table", team_id),
        )
        assert resp.status_code == 201
        asset = resp.json()
        assert asset["semver_mode"] == "auto"

    async def test_create_asset_with_explicit_semver_mode(self, client: AsyncClient):
        """Can create asset with explicit semver mode."""
        # Create team
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        # Create asset with ENFORCE mode
        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.enforce_table", team_id), "semver_mode": "enforce"},
        )
        assert resp.status_code == 201
        assert resp.json()["semver_mode"] == "enforce"

        # Create asset with SUGGEST mode
        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.suggest_table", team_id), "semver_mode": "suggest"},
        )
        assert resp.status_code == 201
        assert resp.json()["semver_mode"] == "suggest"

    async def test_update_asset_semver_mode(self, client: AsyncClient):
        """Can update asset's semver mode."""
        # Create team and asset
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json=make_asset("db.schema.table", team_id),
        )
        asset_id = resp.json()["id"]

        # Update semver_mode
        resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"semver_mode": "enforce"},
        )
        assert resp.status_code == 200
        assert resp.json()["semver_mode"] == "enforce"


class TestAutoSemverMode:
    """Test AUTO semver mode (default behavior)."""

    async def test_first_contract_auto_version(self, client: AsyncClient):
        """First contract gets version 1.0.0 when not specified."""
        # Setup
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json=make_asset("db.schema.table", team_id),
        )
        asset_id = resp.json()["id"]

        # Publish first contract without version
        schema = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "published"
        assert data["contract"]["version"] == "1.0.0"
        assert data["version_auto_generated"] is True

    async def test_minor_change_auto_bumps_version(self, client: AsyncClient):
        """Adding fields auto-bumps minor version."""
        # Setup
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json=make_asset("db.schema.table", team_id),
        )
        asset_id = resp.json()["id"]

        # Publish first contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Add optional field (minor change)
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},  # New optional field
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2},  # No version - should auto-bump
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["contract"]["version"] == "1.1.0"
        assert data["version_auto_generated"] is True


class TestSuggestSemverMode:
    """Test SUGGEST semver mode."""

    async def test_suggest_mode_returns_suggestion(self, client: AsyncClient):
        """SUGGEST mode returns version suggestion when no version provided."""
        # Setup with SUGGEST mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "suggest"},
        )
        asset_id = resp.json()["id"]

        # First contract - should return version_required action
        schema = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema},
        )
        # SUGGEST mode returns version_required action with suggestion
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "version_required"
        assert "version_suggestion" in data
        assert data["version_suggestion"]["suggested_version"] == "1.0.0"
        assert data["version_suggestion"]["is_first_contract"] is True

    async def test_suggest_mode_with_explicit_version(self, client: AsyncClient):
        """SUGGEST mode accepts explicit version."""
        # Setup with SUGGEST mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "suggest"},
        )
        asset_id = resp.json()["id"]

        # First contract with explicit version
        schema = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema, "version": "1.0.0"},
        )
        assert resp.status_code == 201
        assert resp.json()["contract"]["version"] == "1.0.0"

    async def test_suggest_mode_suggests_minor_bump(self, client: AsyncClient):
        """SUGGEST mode suggests minor bump for compatible additions."""
        # Setup with SUGGEST mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "suggest"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Add optional field (minor change) without version
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "version_required"
        assert data["version_suggestion"]["suggested_version"] == "1.1.0"
        assert data["version_suggestion"]["change_type"] == "minor"


class TestEnforceSemverMode:
    """Test ENFORCE semver mode."""

    async def test_enforce_mode_rejects_wrong_version(self, client: AsyncClient):
        """ENFORCE mode rejects version that doesn't match change type."""
        # Setup with ENFORCE mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "enforce"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Try to publish minor change with patch version (should fail)
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2, "version": "1.0.1"},  # Wrong - should be 1.1.0
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["code"] == "INVALID_VERSION"
        assert "version_suggestion" in data["details"]
        assert data["details"]["version_suggestion"]["suggested_version"] == "1.1.0"

    async def test_enforce_mode_accepts_correct_version(self, client: AsyncClient):
        """ENFORCE mode accepts version that matches change type."""
        # Setup with ENFORCE mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "enforce"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Publish minor change with correct version
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2, "version": "1.1.0"},
        )
        assert resp.status_code == 201
        assert resp.json()["contract"]["version"] == "1.1.0"

    async def test_enforce_mode_allows_major_for_minor_change(self, client: AsyncClient):
        """ENFORCE mode allows major bump for minor changes (more conservative)."""
        # Setup with ENFORCE mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "enforce"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Publish minor change with major version (should be allowed)
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2, "version": "2.0.0"},  # Major bump for minor change is OK
        )
        assert resp.status_code == 201
        assert resp.json()["contract"]["version"] == "2.0.0"

    async def test_enforce_mode_requires_major_for_breaking(self, client: AsyncClient):
        """ENFORCE mode requires major bump for breaking changes."""
        # Setup with ENFORCE mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "enforce"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "1.0.0"},
        )
        assert resp.status_code == 201

        # Remove required field (breaking change)
        schema_v2 = make_schema(id="integer")  # Removed 'name'
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id, "force": "true"},  # force to skip proposal
            json={"schema": schema_v2, "version": "1.1.0"},  # Wrong - should be 2.0.0
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["code"] == "INVALID_VERSION"
        assert "major version bump" in data["detail"].lower()


class TestVersionValidation:
    """Test version validation helper functions."""

    async def test_version_must_be_greater(self, client: AsyncClient):
        """Version must be greater than current version."""
        # Setup with ENFORCE mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "enforce"},
        )
        asset_id = resp.json()["id"]

        # First contract
        schema_v1 = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v1, "version": "2.0.0"},  # Start at 2.0.0
        )
        assert resp.status_code == 201

        # Try to publish with lower version
        schema_v2 = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema_v2, "version": "1.5.0"},  # Lower than 2.0.0
        )
        assert resp.status_code == 400
        assert "must be greater than" in resp.json()["detail"].lower()


class TestVersionSuggestionModel:
    """Test the VersionSuggestion response model."""

    async def test_version_suggestion_includes_reason(self, client: AsyncClient):
        """Version suggestion includes human-readable reason."""
        # Setup with SUGGEST mode
        resp = await client.post("/api/v1/teams", json=make_team("test-team"))
        team_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={**make_asset("db.schema.table", team_id), "semver_mode": "suggest"},
        )
        asset_id = resp.json()["id"]

        # First contract request
        schema = make_schema(id="integer", name="string")
        resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={"schema": schema},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reason" in data["version_suggestion"]
        assert len(data["version_suggestion"]["reason"]) > 0
