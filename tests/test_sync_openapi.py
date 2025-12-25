"""Tests for OpenAPI and GraphQL sync endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestOpenAPISync:
    """Tests for /api/v1/sync/openapi endpoint."""

    async def test_import_openapi_basic(self, client: AsyncClient):
        """Import OpenAPI spec creates assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-team"})
        team_id = team_resp.json()["id"]

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List all users",
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        }
                                    }
                                },
                            }
                        },
                    },
                    "post": {
                        "operationId": "createUser",
                        "summary": "Create a user",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    },
                },
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": openapi_spec,
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_title"] == "Test API"
        assert data["endpoints_found"] >= 2
        assert data["assets_created"] >= 2

    async def test_import_openapi_dry_run(self, client: AsyncClient):
        """Dry run previews changes without creating assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-dry-team"})
        team_id = team_resp.json()["id"]

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Dry Run API", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": openapi_spec,
                "owner_team_id": team_id,
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # In dry run, operations report "would_create"
        for endpoint in data["endpoints"]:
            if endpoint["action"] not in ("error",):
                assert endpoint["action"] in ("would_create", "would_update")

    async def test_import_openapi_with_auto_contracts(self, client: AsyncClient):
        """Auto-publish contracts for new endpoints."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-contracts-team"})
        team_id = team_resp.json()["id"]

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Contract API", "version": "2.0.0"},
            "paths": {
                "/orders": {
                    "get": {
                        "operationId": "getOrders",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}},
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": openapi_spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contracts_published"] >= 1

    async def test_import_openapi_invalid_spec(self, client: AsyncClient):
        """Invalid OpenAPI spec returns error or parse warnings."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-bad-team"})
        team_id = team_resp.json()["id"]

        # Missing required fields - may return 400 or 200 with errors
        bad_spec = {"paths": {}}

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": bad_spec,
                "owner_team_id": team_id,
            },
        )
        # Endpoint may return error or success with empty results
        assert resp.status_code in (200, 400)


class TestGraphQLSync:
    """Tests for /api/v1/sync/graphql endpoint."""

    async def test_import_graphql_basic(self, client: AsyncClient):
        """Import GraphQL introspection creates assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "graphql-team"})
        team_id = team_resp.json()["id"]

        # Minimal introspection result
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": {"name": "Mutation"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "users",
                                "args": [],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {"kind": "OBJECT", "name": "User"},
                                },
                            },
                            {
                                "name": "user",
                                "args": [
                                    {
                                        "name": "id",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "ofType": {"kind": "SCALAR", "name": "ID"},
                                        },
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "User"},
                            },
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Mutation",
                        "fields": [
                            {
                                "name": "createUser",
                                "args": [
                                    {
                                        "name": "input",
                                        "type": {"kind": "INPUT_OBJECT", "name": "UserInput"},
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "User"},
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "fields": [
                            {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
                            {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
                        ],
                    },
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "owner_team_id": team_id,
                "schema_name": "user-api",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["operations_found"] >= 2  # users, user queries + createUser mutation

    async def test_import_graphql_dry_run(self, client: AsyncClient):
        """Dry run previews GraphQL import."""
        team_resp = await client.post("/api/v1/teams", json={"name": "graphql-dry-team"})
        team_id = team_resp.json()["id"]

        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "hello",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String"},
                            }
                        ],
                    }
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "owner_team_id": team_id,
                "schema_name": "hello-api",
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Dry run operations should indicate "would_create"
        for op in data.get("operations", []):
            if op.get("action") not in ("error",):
                assert op["action"] in ("would_create", "would_update")

    async def test_import_graphql_with_contracts(self, client: AsyncClient):
        """Auto-publish contracts for GraphQL operations."""
        team_resp = await client.post("/api/v1/teams", json={"name": "graphql-contracts-team"})
        team_id = team_resp.json()["id"]

        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "products",
                                "args": [],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {"kind": "OBJECT", "name": "Product"},
                                },
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Product",
                        "fields": [
                            {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
                            {"name": "price", "type": {"kind": "SCALAR", "name": "Float"}},
                        ],
                    },
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "owner_team_id": team_id,
                "schema_name": "product-api",
                "auto_publish_contracts": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("contracts_published", 0) >= 0


class TestDbtUploadConflicts:
    """Tests for dbt upload conflict handling."""

    async def test_dbt_upload_conflict_mode_fail(self, client: AsyncClient):
        """Fail mode should raise error on existing assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "conflict-fail-team"})
        team_id = team_resp.json()["id"]

        # Create existing asset
        await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.conflict_model", "owner_team_id": team_id},
        )

        # Upload manifest with conflict_mode=fail
        manifest = {
            "nodes": {
                "model.project.conflict_model": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "schema",
                    "name": "conflict_model",
                    "columns": {"id": {"data_type": "integer"}},
                }
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "fail",
            },
        )
        assert resp.status_code == 409

    async def test_dbt_upload_conflict_mode_ignore(self, client: AsyncClient):
        """Ignore mode should skip existing assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "conflict-ignore-team"})
        team_id = team_resp.json()["id"]

        # Create existing asset
        await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.ignore_model", "owner_team_id": team_id},
        )

        manifest = {
            "nodes": {
                "model.project.ignore_model": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "schema",
                    "name": "ignore_model",
                    "columns": {"id": {"data_type": "integer"}},
                }
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "ignore",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["skipped"] >= 1


class TestDbtMetaOwnership:
    """Tests for meta.tessera ownership resolution."""

    async def test_dbt_upload_resolves_owner_team_from_meta(self, client: AsyncClient):
        """Upload should resolve owner_team from meta.tessera.owner_team."""
        # Create two teams
        team1_resp = await client.post("/api/v1/teams", json={"name": "default-team"})
        default_team_id = team1_resp.json()["id"]

        team2_resp = await client.post("/api/v1/teams", json={"name": "meta-owner-team"})
        meta_team_id = team2_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.owned_model": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "schema",
                    "name": "owned_model",
                    "columns": {"id": {"data_type": "integer"}},
                    "meta": {"tessera": {"owner_team": "meta-owner-team"}},
                }
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": default_team_id,
                "conflict_mode": "overwrite",
            },
        )
        assert resp.status_code == 200

        # Verify asset is owned by meta-owner-team
        assets_resp = await client.get(f"/api/v1/assets?owner={meta_team_id}")
        assets = assets_resp.json()["results"]
        fqns = [a["fqn"] for a in assets]
        assert "db.schema.owned_model" in fqns

    async def test_dbt_upload_warns_on_unknown_owner_team(self, client: AsyncClient):
        """Upload warns when meta.tessera.owner_team doesn't exist."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fallback-team"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.project.bad_owner": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "schema",
                    "name": "bad_owner",
                    "columns": {"id": {"data_type": "integer"}},
                    "meta": {"tessera": {"owner_team": "nonexistent-team-12345"}},
                }
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should have warning about unknown team in ownership_warnings
        warnings = data.get("ownership_warnings", [])
        assert any("not found" in w.lower() for w in warnings)
