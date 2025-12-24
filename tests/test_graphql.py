"""Tests for GraphQL import functionality."""

from uuid import uuid4

import pytest

from tessera.models.enums import ResourceType
from tessera.services.graphql import (
    generate_fqn,
    operations_to_assets,
    parse_graphql_introspection,
)


class TestGraphQLParser:
    """Tests for GraphQL introspection parsing."""

    def test_parse_simple_introspection(self) -> None:
        """Test parsing a simple GraphQL introspection response."""
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
                                "description": "List all users",
                                "args": [],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {
                                        "kind": "OBJECT",
                                        "name": "User",
                                    },
                                },
                            },
                            {
                                "name": "user",
                                "description": "Get a user by ID",
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
                                "description": "Create a new user",
                                "args": [
                                    {
                                        "name": "input",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "ofType": {
                                                "kind": "INPUT_OBJECT",
                                                "name": "CreateUserInput",
                                            },
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
                            {
                                "name": "id",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "ID"},
                                },
                            },
                            {
                                "name": "name",
                                "type": {"kind": "SCALAR", "name": "String"},
                            },
                            {
                                "name": "email",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "String"},
                                },
                            },
                        ],
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "CreateUserInput",
                        "inputFields": [
                            {
                                "name": "name",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "String"},
                                },
                            },
                            {
                                "name": "email",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "String"},
                                },
                            },
                        ],
                    },
                ],
            }
        }

        result = parse_graphql_introspection(introspection)

        assert len(result.errors) == 0
        assert len(result.operations) == 3  # 2 queries + 1 mutation

        # Check operations by name
        ops_by_name = {op.name: op for op in result.operations}

        # users query
        users_op = ops_by_name["users"]
        assert users_op.operation_type == "query"
        assert users_op.description == "List all users"
        assert len(users_op.args) == 0

        # user query with ID arg
        user_op = ops_by_name["user"]
        assert user_op.operation_type == "query"
        assert len(user_op.args) == 1
        assert user_op.args[0]["name"] == "id"
        assert user_op.args[0]["required"] is True

        # createUser mutation
        create_op = ops_by_name["createUser"]
        assert create_op.operation_type == "mutation"
        assert len(create_op.args) == 1

    def test_parse_with_enums(self) -> None:
        """Test parsing a schema with enum types."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "usersByStatus",
                                "args": [
                                    {
                                        "name": "status",
                                        "type": {"kind": "ENUM", "name": "UserStatus"},
                                    }
                                ],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {"kind": "OBJECT", "name": "User"},
                                },
                            }
                        ],
                    },
                    {
                        "kind": "ENUM",
                        "name": "UserStatus",
                        "enumValues": [
                            {"name": "ACTIVE"},
                            {"name": "INACTIVE"},
                            {"name": "PENDING"},
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "fields": [
                            {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
                            {"name": "status", "type": {"kind": "ENUM", "name": "UserStatus"}},
                        ],
                    },
                ],
            }
        }

        result = parse_graphql_introspection(introspection)

        assert len(result.errors) == 0
        assert len(result.operations) == 1

        op = result.operations[0]
        assert op.name == "usersByStatus"
        assert len(op.args) == 1

        # Check that enum was parsed correctly
        status_arg = op.args[0]
        assert status_arg["name"] == "status"
        assert status_arg["type"]["type"] == "string"
        assert status_arg["type"]["enum"] == ["ACTIVE", "INACTIVE", "PENDING"]

    def test_parse_data_wrapper(self) -> None:
        """Test parsing introspection wrapped in data object."""
        introspection = {
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "mutationType": None,
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
        }

        result = parse_graphql_introspection(introspection)

        assert len(result.errors) == 0
        assert len(result.operations) == 1
        assert result.operations[0].name == "hello"

    def test_parse_no_schema(self) -> None:
        """Test error handling when no schema is found."""
        introspection = {"invalid": "data"}

        result = parse_graphql_introspection(introspection)

        assert len(result.errors) > 0
        assert "No __schema found" in result.errors[0]

    def test_scalar_type_mapping(self) -> None:
        """Test that scalar types are mapped correctly to JSON Schema."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "getData",
                                "args": [],
                                "type": {"kind": "OBJECT", "name": "Data"},
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Data",
                        "fields": [
                            {"name": "id", "type": {"kind": "SCALAR", "name": "ID"}},
                            {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
                            {"name": "count", "type": {"kind": "SCALAR", "name": "Int"}},
                            {"name": "price", "type": {"kind": "SCALAR", "name": "Float"}},
                            {"name": "active", "type": {"kind": "SCALAR", "name": "Boolean"}},
                        ],
                    },
                ],
            }
        }

        result = parse_graphql_introspection(introspection)

        assert len(result.errors) == 0

        # Check type mappings in the types dict
        data_schema = result.types.get("Data", {})
        assert data_schema.get("type") == "object"

        props = data_schema.get("properties", {})
        assert props["id"]["type"] == "string"
        assert props["name"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["price"]["type"] == "number"
        assert props["active"]["type"] == "boolean"


class TestGenerateFqn:
    """Tests for FQN generation from GraphQL operations."""

    def test_simple_query(self) -> None:
        """Test FQN for a simple query."""
        fqn = generate_fqn("Users API", "listUsers", "query")
        assert fqn == "graphql.users_api.query_listusers"

    def test_mutation(self) -> None:
        """Test FQN for a mutation."""
        fqn = generate_fqn("Users API", "createUser", "mutation")
        assert fqn == "graphql.users_api.mutation_createuser"

    def test_special_characters_in_name(self) -> None:
        """Test that special characters in schema name are handled."""
        fqn = generate_fqn("My Cool API v2.0", "getData", "query")
        assert fqn == "graphql.my_cool_api_v20.query_getdata"

    def test_empty_schema_name(self) -> None:
        """Test handling of empty schema name."""
        fqn = generate_fqn("", "test", "query")
        assert fqn == "graphql.unknown.query_test"


class TestOperationsToAssets:
    """Tests for converting parsed operations to asset definitions."""

    def test_converts_operations_to_assets(self) -> None:
        """Test basic conversion of operations to assets."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "items",
                                "description": "List items",
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

        parse_result = parse_graphql_introspection(introspection)
        team_id = uuid4()
        assets = operations_to_assets(parse_result, team_id, "staging")

        assert len(assets) == 1
        asset = assets[0]

        assert asset.fqn == "graphql.graphql_api.query_items"
        assert asset.resource_type == ResourceType.GRAPHQL_QUERY
        assert asset.metadata["graphql_source"]["operation_name"] == "items"
        assert asset.metadata["graphql_source"]["operation_type"] == "query"
        assert asset.metadata["graphql_source"]["description"] == "List items"

    def test_schema_in_asset(self) -> None:
        """Test that combined schema is included in asset."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "getUser",
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
                            {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
                        ],
                    },
                ],
            }
        }

        parse_result = parse_graphql_introspection(introspection)
        assets = operations_to_assets(parse_result, uuid4(), "production")

        assert len(assets) == 1
        schema = assets[0].schema_def

        assert schema["type"] == "object"
        assert "arguments" in schema["properties"]
        assert "response" in schema["properties"]
        assert schema["properties"]["arguments"]["properties"]["id"]["type"] == "string"

    def test_schema_name_override(self) -> None:
        """Test that schema_name_override is used in FQN."""
        introspection = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
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

        parse_result = parse_graphql_introspection(introspection)
        assets = operations_to_assets(
            parse_result, uuid4(), "production", schema_name_override="Custom API"
        )

        assert len(assets) == 1
        assert assets[0].fqn == "graphql.custom_api.query_hello"


class TestGraphQLImportEndpoint:
    """Tests for the GraphQL import API endpoint."""

    @pytest.fixture
    def sample_introspection(self) -> dict:
        """Sample GraphQL introspection for testing."""
        return {
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
                                "description": "List users",
                                "args": [],
                                "type": {
                                    "kind": "LIST",
                                    "ofType": {"kind": "OBJECT", "name": "User"},
                                },
                            },
                            {
                                "name": "user",
                                "description": "Get user by ID",
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
                                "description": "Create a new user",
                                "args": [
                                    {
                                        "name": "name",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "ofType": {"kind": "SCALAR", "name": "String"},
                                        },
                                    },
                                    {
                                        "name": "email",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "ofType": {"kind": "SCALAR", "name": "String"},
                                        },
                                    },
                                ],
                                "type": {"kind": "OBJECT", "name": "User"},
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "fields": [
                            {
                                "name": "id",
                                "type": {
                                    "kind": "NON_NULL",
                                    "ofType": {"kind": "SCALAR", "name": "ID"},
                                },
                            },
                            {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
                            {"name": "email", "type": {"kind": "SCALAR", "name": "String"}},
                        ],
                    },
                ],
            }
        }

    async def test_import_graphql_dry_run(self, client, sample_introspection) -> None:
        """Test dry run import of GraphQL schema."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "GraphQL Team"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": sample_introspection,
                "schema_name": "Users API",
                "owner_team_id": team_id,
                "dry_run": True,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["schema_name"] == "Users API"
        assert data["operations_found"] == 3
        assert data["assets_created"] == 3
        assert data["contracts_published"] == 3

        # All actions should be "would_create" in dry run
        for op in data["operations"]:
            assert op["action"] == "would_create"

    async def test_import_graphql_creates_assets(self, client, sample_introspection) -> None:
        """Test that GraphQL import creates assets and contracts."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "GraphQL Team 2"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": sample_introspection,
                "schema_name": "Users API",
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["assets_created"] == 3
        assert data["contracts_published"] == 3

        # Verify assets via API
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assert assets_resp.status_code == 200
        assets = assets_resp.json()["results"]
        assert len(assets) == 3

        # Verify contracts via API
        for asset in assets:
            assert asset["resource_type"] == "graphql_query"
            contracts_resp = await client.get(f"/api/v1/assets/{asset['id']}/contracts")
            assert contracts_resp.status_code == 200
            contracts = contracts_resp.json()["results"]
            assert len(contracts) == 1
            assert contracts[0]["version"] == "1.0.0"

    async def test_import_graphql_without_contracts(self, client, sample_introspection) -> None:
        """Test GraphQL import without auto-publishing contracts."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "GraphQL Team 3"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": sample_introspection,
                "schema_name": "Users API",
                "owner_team_id": team_id,
                "auto_publish_contracts": False,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["assets_created"] == 3
        assert data["contracts_published"] == 0

        # Verify assets were created but no contracts
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assert assets_resp.status_code == 200
        assets = assets_resp.json()["results"]
        assert len(assets) == 3

        for asset in assets:
            contracts_resp = await client.get(f"/api/v1/assets/{asset['id']}/contracts")
            assert contracts_resp.status_code == 200
            contracts = contracts_resp.json()["results"]
            assert len(contracts) == 0

    async def test_import_graphql_team_not_found(self, client, sample_introspection) -> None:
        """Test that import fails if team doesn't exist."""
        response = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": sample_introspection,
                "schema_name": "Users API",
                "owner_team_id": str(uuid4()),
            },
        )

        assert response.status_code == 404

    async def test_import_graphql_invalid_introspection(self, client) -> None:
        """Test that import fails with invalid introspection."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "GraphQL Team 4"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": {"invalid": "data"},
                "schema_name": "Bad API",
                "owner_team_id": team_id,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
