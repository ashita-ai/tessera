"""Tests for POST /api/v1/compat/check-compat endpoint."""

import json

import pytest
import yaml
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    "required": ["id", "name"],
}

BREAKING_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "string"}},  # type changed from integer
    "required": ["id"],
}

COMPATIBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "email": {"type": "string"},  # additive, backward-compatible
    },
    "required": ["id", "name"],
}


def _openapi_spec(paths: dict, title: str = "test-svc") -> str:
    """Build a minimal OpenAPI 3.0 spec as YAML."""
    return yaml.dump(
        {
            "openapi": "3.0.0",
            "info": {"title": title, "version": "1.0.0"},
            "paths": paths,
        }
    )


_team_counter = 0


async def _setup_asset_with_contract(
    client: AsyncClient,
    fqn: str,
    schema: dict,
    *,
    compatibility_mode: str = "backward",
) -> tuple[str, str]:
    """Create a team, asset, and publish a contract. Returns (asset_id, team_id)."""
    global _team_counter  # noqa: PLW0603
    _team_counter += 1
    team_resp = await client.post("/api/v1/teams", json={"name": f"compat-team-{_team_counter}"})
    assert (
        team_resp.status_code == 201
    ), f"Team creation failed: {team_resp.status_code} {team_resp.text}"
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets",
        json={"fqn": fqn, "owner_team_id": team_id},
    )
    assert (
        asset_resp.status_code == 201
    ), f"Asset creation failed: {asset_resp.status_code} {asset_resp.text}"
    asset_id = asset_resp.json()["id"]

    pub_resp = await client.post(
        f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
        json={
            "version": "1.0.0",
            "schema": schema,
            "compatibility_mode": compatibility_mode,
        },
    )
    assert pub_resp.status_code == 201, pub_resp.text
    return asset_id, team_id


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestCompatCheckErrors:
    """Validation and error-path tests."""

    async def test_invalid_yaml(self, client: AsyncClient):
        """Malformed YAML returns 400."""
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": "{{not valid yaml",
                "spec_format": "openapi",
            },
        )
        assert resp.status_code == 400

    async def test_non_object_yaml(self, client: AsyncClient):
        """YAML that parses to a non-dict returns 400."""
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": "- just\n- a\n- list",
                "spec_format": "openapi",
            },
        )
        assert resp.status_code == 400

    async def test_invalid_graphql_json(self, client: AsyncClient):
        """Non-JSON GraphQL input returns 400."""
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": "type Query { hello: String }",
                "spec_format": "graphql",
            },
        )
        assert resp.status_code == 400

    async def test_asset_fqn_not_found(self, client: AsyncClient):
        """Specifying a non-existent asset_fqn returns 404."""
        spec = _openapi_spec({"/users": {"get": {"responses": {"200": {"description": "ok"}}}}})
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "asset_fqn": "production.nonexistent.asset",
            },
        )
        assert resp.status_code == 404

    async def test_empty_spec_content_rejected(self, client: AsyncClient):
        """Empty spec_content violates min_length validation."""
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": "",
                "spec_format": "openapi",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Success cases — new endpoints (no existing contracts)
# ---------------------------------------------------------------------------


class TestCompatCheckNewEndpoints:
    """Tests for specs that don't match any existing assets."""

    async def test_unmatched_endpoints_reported_as_new(self, client: AsyncClient):
        """Endpoints with no matching Tessera asset are marked as new."""
        spec = _openapi_spec({"/widgets": {"get": {"responses": {"200": {"description": "ok"}}}}})
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_breaking"] is False
        assert data["new_endpoints"] >= 1
        assert data["total_endpoints"] >= 1
        assert all(r["change_type"] == "new" for r in data["results"])

    async def test_asset_without_contract_is_new(self, client: AsyncClient):
        """An asset that exists but has no published contract is treated as new."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-contract-team"})
        team_id = team_resp.json()["id"]

        fqn = "production.test_svc.no_contract"
        await client.post(
            "/api/v1/assets",
            json={"fqn": fqn, "owner_team_id": team_id},
        )

        spec = _openapi_spec(
            {"/no_contract": {"get": {"responses": {"200": {"description": "ok"}}}}}
        )
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "service_name": "test-svc",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_breaking"] is False


# ---------------------------------------------------------------------------
# Success cases — diffing against existing contracts
# ---------------------------------------------------------------------------


class TestCompatCheckDiff:
    """Tests that diff a proposed spec against an active contract."""

    async def test_compatible_change_not_breaking(self, client: AsyncClient):
        """Adding an optional field to a backward-compatible contract is fine."""
        fqn = "production.compat_svc.users"
        await _setup_asset_with_contract(client, fqn, SIMPLE_SCHEMA)

        spec = _openapi_spec(
            {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": COMPATIBLE_SCHEMA,
                                    }
                                },
                            }
                        }
                    }
                }
            }
        )
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "asset_fqn": fqn,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["checked"] == 1
        assert data["total_endpoints"] == 1
        assert data["results"][0]["current_version"] == "1.0.0"

    async def test_breaking_change_detected(self, client: AsyncClient):
        """Changing a field type is detected as breaking under backward mode."""
        fqn = "production.break_svc.items"
        await _setup_asset_with_contract(client, fqn, SIMPLE_SCHEMA)

        spec = _openapi_spec(
            {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": BREAKING_SCHEMA,
                                    }
                                },
                            }
                        }
                    }
                }
            }
        )
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "asset_fqn": fqn,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_breaking"] is True
        assert data["results"][0]["is_breaking"] is True
        assert len(data["results"][0]["breaking_changes"]) > 0

    async def test_compatibility_mode_override(self, client: AsyncClient):
        """Overriding mode to 'none' makes any change non-breaking."""
        fqn = "production.override_svc.orders"
        await _setup_asset_with_contract(client, fqn, SIMPLE_SCHEMA)

        spec = _openapi_spec(
            {
                "/orders": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": BREAKING_SCHEMA,
                                    }
                                },
                            }
                        }
                    }
                }
            }
        )
        resp = await client.post(
            "/api/v1/compat/check-compat?compatibility_mode_override=none",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "asset_fqn": fqn,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_breaking"] is False

    async def test_asset_fqn_uses_single_schema(self, client: AsyncClient):
        """When asset_fqn is set, only one result is returned regardless of spec size."""
        fqn = "production.single_svc.health"
        await _setup_asset_with_contract(client, fqn, SIMPLE_SCHEMA)

        spec = _openapi_spec(
            {
                "/health": {
                    "get": {"responses": {"200": {"description": "ok"}}},
                },
                "/metrics": {
                    "get": {"responses": {"200": {"description": "ok"}}},
                },
                "/status": {
                    "get": {"responses": {"200": {"description": "ok"}}},
                },
            }
        )
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
                "asset_fqn": fqn,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # asset_fqn narrows to a single result — the first parsed endpoint
        assert data["total_endpoints"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["fqn"] == fqn


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


class TestCompatCheckResponseShape:
    """Verify the response model fields are populated correctly."""

    async def test_response_includes_all_fields(self, client: AsyncClient):
        """Verify the shape of a successful response."""
        spec = _openapi_spec({"/ping": {"get": {"responses": {"200": {"description": "pong"}}}}})
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": spec,
                "spec_format": "openapi",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "is_breaking" in data
        assert "spec_format" in data
        assert "total_endpoints" in data
        assert "checked" in data
        assert "new_endpoints" in data
        assert "results" in data
        assert "parse_errors" in data
        assert data["spec_format"] == "openapi"
        assert isinstance(data["parse_errors"], list)

    async def test_graphql_invalid_json_introspection(self, client: AsyncClient):
        """GraphQL with valid JSON but invalid introspection shape returns 400."""
        resp = await client.post(
            "/api/v1/compat/check-compat",
            json={
                "spec_content": json.dumps({"not": "introspection"}),
                "spec_format": "graphql",
            },
        )
        # parse_graphql_introspection returns an error when __schema is missing,
        # which _parse_graphql propagates as a BadRequestError (400).
        assert resp.status_code == 400
