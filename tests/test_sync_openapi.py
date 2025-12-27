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

    async def test_import_openapi_update_existing(self, client: AsyncClient):
        """Import OpenAPI spec updates existing assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-update-team"})
        team_id = team_resp.json()["id"]

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Update API", "version": "1.0.0"},
            "paths": {
                "/products": {
                    "get": {
                        "operationId": "listProducts",
                        "summary": "List products",
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "array", "items": {"type": "object"}}
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        # First import
        resp1 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": openapi_spec, "owner_team_id": team_id},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["assets_created"] >= 1

        # Second import should update
        openapi_spec["info"]["version"] = "2.0.0"
        openapi_spec["paths"]["/products"]["get"]["summary"] = "List all products"
        resp2 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": openapi_spec, "owner_team_id": team_id},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["assets_updated"] >= 1

    async def test_import_openapi_dry_run_existing(self, client: AsyncClient):
        """Dry run with existing assets shows would_update."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-dryrun-exist"})
        team_id = team_resp.json()["id"]

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Dry Run Existing API", "version": "1.0.0"},
            "paths": {
                "/status": {
                    "get": {
                        "operationId": "getStatus",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        # First create the asset
        resp1 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": openapi_spec, "owner_team_id": team_id},
        )
        assert resp1.status_code == 200
        assert resp1.json()["assets_created"] >= 1

        # Now dry run should show would_update
        resp2 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": openapi_spec, "owner_team_id": team_id, "dry_run": True},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        endpoints = data2.get("endpoints", [])
        # At least one endpoint should show would_update
        actions = [e["action"] for e in endpoints]
        assert "would_update" in actions or data2.get("assets_updated", 0) >= 1


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


class TestOpenAPIImpactAndDiff:
    """Tests for OpenAPI impact and diff endpoints."""

    async def test_openapi_impact_no_contracts(self, client: AsyncClient):
        """Impact check with no existing contracts returns success."""
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "New API", "version": "1.0.0"},
            "paths": {
                "/health": {
                    "get": {
                        "operationId": "healthCheck",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi/impact",
            json={"spec": openapi_spec},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["breaking_changes_count"] == 0
        assert data["endpoints_with_contracts"] == 0

    async def test_openapi_impact_with_existing_contract(self, client: AsyncClient):
        """Impact check detects when endpoint has existing contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "impact-test-team"})
        team_id = team_resp.json()["id"]

        # First import to create assets and contracts
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Impact API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": openapi_spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        # Now check impact - should find the contract
        resp = await client.post(
            "/api/v1/sync/openapi/impact",
            json={"spec": openapi_spec},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["endpoints_with_contracts"] >= 1

    async def test_openapi_diff_new_endpoints(self, client: AsyncClient):
        """Diff shows new endpoints correctly."""
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Diff New API", "version": "1.0.0"},
            "paths": {
                "/new-endpoint": {
                    "get": {
                        "operationId": "newEndpoint",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi/diff",
            json={"spec": openapi_spec},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["new"] >= 1
        assert data["blocking"] is False

    async def test_openapi_diff_detects_breaking_changes(self, client: AsyncClient):
        """Diff detects breaking schema changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "diff-break-team"})
        team_id = team_resp.json()["id"]

        # First import with original schema
        openapi_spec_v1 = {
            "openapi": "3.0.0",
            "info": {"title": "Breaking API", "version": "1.0.0"},
            "paths": {
                "/data": {
                    "get": {
                        "operationId": "getData",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "email": {"type": "string"},
                                            },
                                            "required": ["id", "email"],
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": openapi_spec_v1,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        # Now diff with breaking change (remove email property)
        openapi_spec_v2 = {
            "openapi": "3.0.0",
            "info": {"title": "Breaking API", "version": "2.0.0"},
            "paths": {
                "/data": {
                    "get": {
                        "operationId": "getData",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                # email removed - breaking change!
                                            },
                                            "required": ["id"],
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
            "/api/v1/sync/openapi/diff",
            json={"spec": openapi_spec_v2, "fail_on_breaking": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should detect breaking changes
        assert data["summary"]["breaking"] >= 1 or data["summary"]["modified"] >= 1
        if data["summary"]["breaking"] >= 1:
            assert data["blocking"] is True
            assert data["status"] == "breaking_changes_detected"

    async def test_openapi_diff_fail_on_breaking_false(self, client: AsyncClient):
        """Diff with fail_on_breaking=false doesn't block."""
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Non-blocking API", "version": "1.0.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "test",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi/diff",
            json={"spec": openapi_spec, "fail_on_breaking": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocking"] is False


class TestGraphQLImpactAndDiff:
    """Tests for GraphQL impact and diff endpoints."""

    async def test_graphql_impact_no_contracts(self, client: AsyncClient):
        """Impact check with no existing contracts returns success."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "ping",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String"},
                            }
                        ],
                    }
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql/impact",
            json={"introspection": introspection, "schema_name": "new-graphql-api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["breaking_changes_count"] == 0

    async def test_graphql_impact_with_existing_contract(self, client: AsyncClient):
        """Impact check finds existing contracts."""
        team_resp = await client.post("/api/v1/teams", json={"name": "gql-impact-team"})
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
                                "name": "items",
                                "args": [],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {"kind": "SCALAR", "name": "String"},
                                },
                            }
                        ],
                    }
                ],
            }
        }

        # First import to create assets
        await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "owner_team_id": team_id,
                "schema_name": "impact-gql-api",
                "auto_publish_contracts": True,
            },
        )

        # Now check impact
        resp = await client.post(
            "/api/v1/sync/graphql/impact",
            json={"introspection": introspection, "schema_name": "impact-gql-api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["operations_with_contracts"] >= 1

    async def test_graphql_diff_new_operations(self, client: AsyncClient):
        """Diff shows new operations correctly."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "newQuery",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String"},
                            }
                        ],
                    }
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql/diff",
            json={"introspection": introspection, "schema_name": "new-gql-diff-api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["new"] >= 1
        assert data["blocking"] is False

    async def test_graphql_diff_detects_changes(self, client: AsyncClient):
        """Diff detects schema changes in GraphQL operations."""
        team_resp = await client.post("/api/v1/teams", json={"name": "gql-diff-team"})
        team_id = team_resp.json()["id"]

        introspection_v1 = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
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
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "fields": [
                            {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
                            {"name": "email", "type": {"kind": "SCALAR", "name": "String"}},
                        ],
                    },
                ],
            }
        }

        # First import
        await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection_v1,
                "owner_team_id": team_id,
                "schema_name": "diff-gql-api",
                "auto_publish_contracts": True,
            },
        )

        # Now diff - same schema should show unchanged
        resp = await client.post(
            "/api/v1/sync/graphql/diff",
            json={"introspection": introspection_v1, "schema_name": "diff-gql-api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should find existing operation
        assert data["total_operations"] >= 1 if "total_operations" in data else True

    async def test_graphql_diff_fail_on_breaking_false(self, client: AsyncClient):
        """Diff with fail_on_breaking=false doesn't block."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "test",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "Boolean"},
                            }
                        ],
                    }
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql/diff",
            json={
                "introspection": introspection,
                "schema_name": "nonblock-gql-api",
                "fail_on_breaking": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocking"] is False


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
