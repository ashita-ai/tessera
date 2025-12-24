"""Tests for OpenAPI import functionality."""

from uuid import uuid4

import pytest

from tessera.models.enums import ResourceType
from tessera.services.openapi import (
    endpoints_to_assets,
    generate_fqn,
    parse_openapi,
)


class TestOpenAPIParser:
    """Tests for OpenAPI spec parsing."""

    def test_parse_simple_spec(self) -> None:
        """Test parsing a simple OpenAPI 3.x spec."""
        spec = {
            "openapi": "3.0.0",
            "info": {
                "title": "Pet Store API",
                "version": "1.0.0",
                "description": "A sample pet store API",
            },
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "summary": "List all pets",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/Pet"},
                                        }
                                    }
                                }
                            }
                        },
                    },
                    "post": {
                        "operationId": "createPet",
                        "summary": "Create a pet",
                        "requestBody": {
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                            }
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Pet"}
                                    }
                                }
                            }
                        },
                    },
                },
                "/pets/{petId}": {
                    "get": {
                        "operationId": "getPet",
                        "summary": "Get a pet by ID",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Pet"}
                                    }
                                }
                            }
                        },
                    },
                },
            },
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                        },
                        "required": ["id", "name"],
                    }
                }
            },
        }

        result = parse_openapi(spec)

        assert result.title == "Pet Store API"
        assert result.version == "1.0.0"
        assert result.description == "A sample pet store API"
        assert len(result.endpoints) == 3
        assert len(result.errors) == 0

        # Check endpoints
        endpoints_by_path_method = {(e.path, e.method): e for e in result.endpoints}

        # GET /pets
        get_pets = endpoints_by_path_method[("/pets", "GET")]
        assert get_pets.operation_id == "listPets"
        assert get_pets.summary == "List all pets"
        assert get_pets.response_schema is not None
        assert get_pets.response_schema["type"] == "array"

        # POST /pets
        post_pets = endpoints_by_path_method[("/pets", "POST")]
        assert post_pets.operation_id == "createPet"
        assert post_pets.request_schema is not None
        assert post_pets.response_schema is not None

    def test_parse_spec_with_no_schemas(self) -> None:
        """Test parsing a spec with endpoints that have no schemas."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Simple API", "version": "1.0.0"},
            "paths": {
                "/health": {
                    "get": {
                        "summary": "Health check",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        result = parse_openapi(spec)

        assert result.title == "Simple API"
        assert len(result.endpoints) == 1
        assert result.endpoints[0].request_schema is None
        assert result.endpoints[0].response_schema is None
        assert result.endpoints[0].combined_schema == {"type": "object"}

    def test_parse_invalid_openapi_version(self) -> None:
        """Test that non-3.x OpenAPI specs are rejected."""
        spec = {
            "swagger": "2.0",
            "info": {"title": "Old API", "version": "1.0.0"},
            "paths": {},
        }

        result = parse_openapi(spec)

        assert len(result.errors) > 0
        assert "3.x" in result.errors[0].lower() or "3." in result.errors[0]

    def test_parse_spec_with_refs(self) -> None:
        """Test that $ref pointers are properly resolved."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Ref Test API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            }
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/User"}
                                    }
                                }
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string", "format": "email"},
                        },
                    }
                }
            },
        }

        result = parse_openapi(spec)

        assert len(result.endpoints) == 1
        endpoint = result.endpoints[0]

        # Check that $ref was resolved
        assert endpoint.request_schema is not None
        assert endpoint.request_schema.get("type") == "object"
        assert "properties" in endpoint.request_schema
        assert "id" in endpoint.request_schema["properties"]


class TestGenerateFqn:
    """Tests for FQN generation from API endpoints."""

    def test_simple_path(self) -> None:
        """Test FQN for a simple path."""
        fqn = generate_fqn("Users API", "/users", "GET")
        assert fqn == "api.users_api.get_users"

    def test_path_with_parameters(self) -> None:
        """Test FQN for a path with URL parameters."""
        fqn = generate_fqn("Users API", "/users/{userId}/posts/{postId}", "GET")
        assert fqn == "api.users_api.get_users_userid_posts_postid"

    def test_root_path(self) -> None:
        """Test FQN for root path."""
        fqn = generate_fqn("Health API", "/", "GET")
        assert fqn == "api.health_api.get_root"

    def test_special_characters_in_title(self) -> None:
        """Test that special characters in title are handled."""
        fqn = generate_fqn("My Cool API v2.0", "/data", "POST")
        assert fqn == "api.my_cool_api_v20.post_data"

    def test_empty_title(self) -> None:
        """Test handling of empty title."""
        fqn = generate_fqn("", "/test", "PUT")
        assert fqn == "api.unknown.put_test"


class TestEndpointsToAssets:
    """Tests for converting parsed endpoints to asset definitions."""

    def test_converts_endpoints_to_assets(self) -> None:
        """Test basic conversion of endpoints to assets."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "2.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }

        parse_result = parse_openapi(spec)
        team_id = uuid4()
        assets = endpoints_to_assets(parse_result, team_id, "staging")

        assert len(assets) == 1
        asset = assets[0]

        assert asset.fqn == "api.test_api.get_items"
        assert asset.resource_type == ResourceType.API_ENDPOINT
        assert asset.metadata["openapi_source"]["api_title"] == "Test API"
        assert asset.metadata["openapi_source"]["api_version"] == "2.0.0"
        assert asset.metadata["openapi_source"]["path"] == "/items"
        assert asset.metadata["openapi_source"]["method"] == "GET"
        assert asset.metadata["openapi_source"]["operation_id"] == "listItems"

    def test_schema_in_asset(self) -> None:
        """Test that combined schema is included in asset."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/data": {
                    "post": {
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
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}},
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }

        parse_result = parse_openapi(spec)
        assets = endpoints_to_assets(parse_result, uuid4(), "production")

        assert len(assets) == 1
        schema = assets[0].schema_def

        assert schema["type"] == "object"
        assert "request" in schema["properties"]
        assert "response" in schema["properties"]
        assert schema["properties"]["request"]["properties"]["name"]["type"] == "string"
        assert schema["properties"]["response"]["properties"]["id"]["type"] == "integer"


class TestOpenAPIImportEndpoint:
    """Tests for the OpenAPI import API endpoint."""

    @pytest.fixture
    def sample_openapi_spec(self) -> dict:
        """Sample OpenAPI spec for testing."""
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Sample API",
                "version": "1.0.0",
            },
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List users",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "id": {"type": "integer"},
                                                    "name": {"type": "string"},
                                                },
                                            },
                                        }
                                    }
                                }
                            }
                        },
                    },
                    "post": {
                        "operationId": "createUser",
                        "summary": "Create user",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                        "required": ["name"],
                                    }
                                }
                            }
                        },
                        "responses": {
                            "201": {
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
                                }
                            }
                        },
                    },
                },
            },
        }

    async def test_import_openapi_dry_run(self, client, sample_openapi_spec) -> None:
        """Test dry run import of OpenAPI spec."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "API Team"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": sample_openapi_spec,
                "owner_team_id": team_id,
                "dry_run": True,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["api_title"] == "Sample API"
        assert data["api_version"] == "1.0.0"
        assert data["endpoints_found"] == 2
        assert data["assets_created"] == 2
        assert data["contracts_published"] == 2

        # All actions should be "would_create" in dry run
        for endpoint in data["endpoints"]:
            assert endpoint["action"] == "would_create"

    async def test_import_openapi_creates_assets(self, client, sample_openapi_spec) -> None:
        """Test that OpenAPI import creates assets and contracts."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "API Team 2"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": sample_openapi_spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["assets_created"] == 2
        assert data["contracts_published"] == 2

        # Verify assets via API
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assert assets_resp.status_code == 200
        assets = assets_resp.json()["results"]
        assert len(assets) == 2

        # Verify contracts via API
        for asset in assets:
            assert asset["resource_type"] == "api_endpoint"
            contracts_resp = await client.get(f"/api/v1/assets/{asset['id']}/contracts")
            assert contracts_resp.status_code == 200
            contracts = contracts_resp.json()["results"]
            assert len(contracts) == 1
            assert contracts[0]["version"] == "1.0.0"

    async def test_import_openapi_without_contracts(self, client, sample_openapi_spec) -> None:
        """Test OpenAPI import without auto-publishing contracts."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "API Team 3"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": sample_openapi_spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": False,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["assets_created"] == 2
        assert data["contracts_published"] == 0

        # Verify assets were created but no contracts
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        assert assets_resp.status_code == 200
        assets = assets_resp.json()["results"]
        assert len(assets) == 2

        for asset in assets:
            contracts_resp = await client.get(f"/api/v1/assets/{asset['id']}/contracts")
            assert contracts_resp.status_code == 200
            contracts = contracts_resp.json()["results"]
            assert len(contracts) == 0

    async def test_import_openapi_team_not_found(self, client, sample_openapi_spec) -> None:
        """Test that import fails if team doesn't exist."""
        response = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": sample_openapi_spec,
                "owner_team_id": str(uuid4()),
            },
        )

        assert response.status_code == 404

    async def test_import_openapi_invalid_spec(self, client) -> None:
        """Test that import fails with invalid OpenAPI spec."""
        # Create a team first using the API
        team_resp = await client.post("/api/v1/teams", json={"name": "API Team 4"})
        assert team_resp.status_code == 201
        team_id = team_resp.json()["id"]

        response = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": {
                    "swagger": "2.0",
                    "info": {"title": "Old", "version": "1.0"},
                    "paths": {},
                },
                "owner_team_id": team_id,
            },
        )

        assert response.status_code == 400
        data = response.json()
        # Error structure is: {"error": {"code": ..., "details": {"errors": [...]}}}
        assert "error" in data
        assert data["error"]["code"] == "INVALID_OPENAPI_SPEC"
        assert "errors" in data["error"]["details"]
