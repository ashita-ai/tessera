"""Tests for semantic metadata: asset tags, field_descriptions, field_tags.

Covers:
- Publishing contracts with field_descriptions and field_tags
- Carry-forward of metadata for unchanged fields on new versions
- Dropped metadata for removed fields
- Asset tags CRUD via PATCH
- Search with tag filtering
- dbt sync extraction of column descriptions and tags
- OpenAPI sync extraction of property descriptions and tags
- GraphQL sync extraction of field descriptions
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestPublishWithFieldMetadata:
    """Test publishing contracts with field_descriptions and field_tags."""

    async def test_publish_with_field_descriptions(self, client: AsyncClient) -> None:
        """Publish a contract that carries field_descriptions."""
        team_resp = await client.post("/api/v1/teams", json={"name": "desc-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.desc_table",
                "owner_team_id": team_id,
            },
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer"},
                        "email": {"type": "string"},
                    },
                },
                "field_descriptions": {
                    "$.properties.customer_id": "Unique customer identifier",
                    "$.properties.email": "Customer email address",
                },
                "field_tags": {
                    "$.properties.customer_id": ["join-key"],
                    "$.properties.email": ["pii", "gdpr-deletable"],
                },
            },
        )
        assert contract_resp.status_code == 201
        data = contract_resp.json()
        contract = data["contract"]
        assert (
            contract["field_descriptions"]["$.properties.customer_id"]
            == "Unique customer identifier"
        )
        assert contract["field_tags"]["$.properties.email"] == ["pii", "gdpr-deletable"]

    async def test_publish_without_field_metadata_defaults_empty(self, client: AsyncClient) -> None:
        """Publishing without field metadata uses empty defaults."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-meta-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.no_meta", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
            },
        )
        assert contract_resp.status_code == 201
        contract = contract_resp.json()["contract"]
        assert contract["field_descriptions"] == {}
        assert contract["field_tags"] == {}


@pytest.mark.asyncio
class TestFieldMetadataCarryForward:
    """Test that field metadata carries forward on new contract versions."""

    async def test_carry_forward_unchanged_fields(self, client: AsyncClient) -> None:
        """Metadata carries forward for fields that still exist."""
        team_resp = await client.post("/api/v1/teams", json={"name": "carry-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.carry_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish v1 with metadata on customer_id and email
        v1_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer"},
                        "email": {"type": "string"},
                    },
                },
                "field_descriptions": {
                    "$.properties.customer_id": "Unique customer ID",
                    "$.properties.email": "Customer email",
                },
                "field_tags": {
                    "$.properties.customer_id": ["join-key"],
                    "$.properties.email": ["pii"],
                },
            },
        )
        assert v1_resp.status_code == 201

        # Publish v2: add a new field, keep existing fields
        v2_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer"},
                        "email": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            },
        )
        assert v2_resp.status_code == 201
        v2_contract = v2_resp.json()["contract"]

        # customer_id and email descriptions should carry forward
        assert v2_contract["field_descriptions"]["$.properties.customer_id"] == "Unique customer ID"
        assert v2_contract["field_descriptions"]["$.properties.email"] == "Customer email"
        # Tags should carry forward
        assert v2_contract["field_tags"]["$.properties.customer_id"] == ["join-key"]
        assert v2_contract["field_tags"]["$.properties.email"] == ["pii"]
        # New field has no metadata
        assert "$.properties.name" not in v2_contract["field_descriptions"]

    async def test_removed_field_metadata_dropped(self, client: AsyncClient) -> None:
        """Metadata is dropped for fields that are removed."""
        team_resp = await client.post("/api/v1/teams", json={"name": "drop-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.drop_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish v1 with metadata on both fields
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "keep_field": {"type": "string"},
                        "remove_field": {"type": "string"},
                    },
                },
                "field_descriptions": {
                    "$.properties.keep_field": "This stays",
                    "$.properties.remove_field": "This goes",
                },
            },
        )

        # Publish v2: remove remove_field (force publish since breaking)
        v2_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id, "force": True},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "keep_field": {"type": "string"},
                    },
                },
            },
        )
        assert v2_resp.status_code == 201
        v2_contract = v2_resp.json()["contract"]

        # keep_field description should carry forward
        assert v2_contract["field_descriptions"]["$.properties.keep_field"] == "This stays"
        # remove_field description should be dropped
        assert "$.properties.remove_field" not in v2_contract["field_descriptions"]

    async def test_explicit_metadata_overrides_carry_forward(self, client: AsyncClient) -> None:
        """Explicitly provided metadata overrides carried-forward values."""
        team_resp = await client.post("/api/v1/teams", json={"name": "override-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.override_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish v1 with description
        await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                "field_descriptions": {
                    "$.properties.status": "Old description",
                },
            },
        )

        # Publish v2 with updated description
        v2_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "extra": {"type": "integer"},
                    },
                },
                "field_descriptions": {
                    "$.properties.status": "Updated description",
                },
            },
        )
        assert v2_resp.status_code == 201
        assert (
            v2_resp.json()["contract"]["field_descriptions"]["$.properties.status"]
            == "Updated description"
        )


@pytest.mark.asyncio
class TestAssetTags:
    """Test asset tags CRUD."""

    async def test_create_asset_with_tags(self, client: AsyncClient) -> None:
        """Create an asset with tags."""
        team_resp = await client.post("/api/v1/teams", json={"name": "tags-create-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.tagged_asset",
                "owner_team_id": team_id,
                "tags": ["pii", "financial", "sla:p1"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["tags"] == ["pii", "financial", "sla:p1"]

    async def test_update_asset_tags(self, client: AsyncClient) -> None:
        """Update asset tags via PATCH."""
        team_resp = await client.post("/api/v1/teams", json={"name": "tags-update-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.update_tags",
                "owner_team_id": team_id,
                "tags": ["old-tag"],
            },
        )
        asset_id = asset_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"tags": ["new-tag-1", "new-tag-2"]},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["tags"] == ["new-tag-1", "new-tag-2"]

    async def test_clear_asset_tags(self, client: AsyncClient) -> None:
        """Clear asset tags by setting to empty list."""
        team_resp = await client.post("/api/v1/teams", json={"name": "tags-clear-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.clear_tags",
                "owner_team_id": team_id,
                "tags": ["will-be-removed"],
            },
        )
        asset_id = asset_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"tags": []},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["tags"] == []

    async def test_get_asset_includes_tags(self, client: AsyncClient) -> None:
        """GET asset returns tags."""
        team_resp = await client.post("/api/v1/teams", json={"name": "tags-get-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.schema.get_tagged",
                "owner_team_id": team_id,
                "tags": ["visible-tag"],
            },
        )
        asset_id = asset_resp.json()["id"]

        get_resp = await client.get(f"/api/v1/assets/{asset_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["tags"] == ["visible-tag"]


@pytest.mark.asyncio
class TestSearchWithTags:
    """Test search with tag filtering."""

    async def test_search_filter_by_tags(self, client: AsyncClient) -> None:
        """Search assets filtered by tags."""
        team_resp = await client.post("/api/v1/teams", json={"name": "search-tags-team"})
        team_id = team_resp.json()["id"]

        # Create assets with different tags
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.search.pii_asset",
                "owner_team_id": team_id,
                "tags": ["pii", "financial"],
            },
        )
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.search.financial_only",
                "owner_team_id": team_id,
                "tags": ["financial"],
            },
        )
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.search.no_tags",
                "owner_team_id": team_id,
            },
        )

        # Search with pii tag - should find only pii_asset
        resp = await client.get("/api/v1/search", params={"q": "search", "tags": "pii"})
        assert resp.status_code == 200
        asset_fqns = [a["fqn"] for a in resp.json()["results"]["assets"]]
        assert "db.search.pii_asset" in asset_fqns
        assert "db.search.financial_only" not in asset_fqns
        assert "db.search.no_tags" not in asset_fqns

    async def test_search_filter_by_multiple_tags(self, client: AsyncClient) -> None:
        """Search with multiple tags requires all tags to match."""
        team_resp = await client.post("/api/v1/teams", json={"name": "multi-tags-team"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.multi.both_tags",
                "owner_team_id": team_id,
                "tags": ["pii", "financial"],
            },
        )
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.multi.one_tag",
                "owner_team_id": team_id,
                "tags": ["pii"],
            },
        )

        resp = await client.get(
            "/api/v1/search",
            params={"q": "multi", "tags": "pii,financial"},
        )
        assert resp.status_code == 200
        asset_fqns = [a["fqn"] for a in resp.json()["results"]["assets"]]
        assert "db.multi.both_tags" in asset_fqns
        assert "db.multi.one_tag" not in asset_fqns

    async def test_search_without_tags_returns_all(self, client: AsyncClient) -> None:
        """Search without tags parameter returns all matching assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-filter-team"})
        team_id = team_resp.json()["id"]

        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.nofilter.tagged",
                "owner_team_id": team_id,
                "tags": ["some-tag"],
            },
        )
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.nofilter.untagged",
                "owner_team_id": team_id,
            },
        )

        resp = await client.get("/api/v1/search", params={"q": "nofilter"})
        assert resp.status_code == 200
        asset_fqns = [a["fqn"] for a in resp.json()["results"]["assets"]]
        assert "db.nofilter.tagged" in asset_fqns
        assert "db.nofilter.untagged" in asset_fqns


@pytest.mark.asyncio
class TestDbtSyncMetadata:
    """Test dbt sync extraction of field descriptions, tags, and asset tags."""

    async def test_dbt_sync_extracts_column_descriptions_and_tags(
        self, client: AsyncClient
    ) -> None:
        """dbt sync should extract column descriptions into field_descriptions."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-meta-team"})
        team_id = team_resp.json()["id"]

        manifest = {
            "nodes": {
                "model.test_project.customers": {
                    "resource_type": "model",
                    "name": "customers",
                    "schema": "analytics",
                    "database": "warehouse",
                    "description": "Customer dimension table",
                    "tags": ["tier1", "financial"],
                    "columns": {
                        "customer_id": {
                            "name": "customer_id",
                            "description": "Unique identifier for the customer",
                            "data_type": "integer",
                            "meta": {"tags": ["join-key", "pii"]},
                        },
                        "email": {
                            "name": "email",
                            "description": "Customer email address",
                            "data_type": "varchar",
                            "meta": {"tessera": {"tags": ["pii", "gdpr-deletable"]}},
                        },
                        "status": {
                            "name": "status",
                            "description": "",
                            "data_type": "varchar",
                        },
                    },
                },
            },
            "sources": {},
        }

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] >= 1

        # Verify asset tags were extracted
        search_resp = await client.get("/api/v1/search", params={"q": "customers"})
        assets = search_resp.json()["results"]["assets"]
        assert len(assets) >= 1
        asset_id = assets[0]["id"]

        asset_resp = await client.get(f"/api/v1/assets/{asset_id}")
        assert asset_resp.status_code == 200
        assert "tier1" in asset_resp.json()["tags"]
        assert "financial" in asset_resp.json()["tags"]

        # Verify field descriptions were extracted into contract
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        contracts = contracts_resp.json()["results"]
        assert len(contracts) >= 1
        contract = contracts[0]
        assert (
            contract["field_descriptions"]["$.properties.customer_id"]
            == "Unique identifier for the customer"
        )
        assert contract["field_descriptions"]["$.properties.email"] == "Customer email address"
        # Empty description should not be included
        assert "$.properties.status" not in contract["field_descriptions"]

        # Verify field tags were extracted
        assert contract["field_tags"]["$.properties.customer_id"] == ["join-key", "pii"]
        assert contract["field_tags"]["$.properties.email"] == ["pii", "gdpr-deletable"]


@pytest.mark.asyncio
class TestOpenAPISyncMetadata:
    """Test OpenAPI sync extraction of property descriptions and tags."""

    async def test_openapi_sync_extracts_property_descriptions(self, client: AsyncClient) -> None:
        """OpenAPI sync extracts property descriptions into field_descriptions."""
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-meta-team"})
        team_id = team_resp.json()["id"]

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Meta Test API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List all users",
                        "tags": ["users", "admin"],
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "user_id": {
                                                    "type": "integer",
                                                    "description": "Unique user identifier",
                                                },
                                                "name": {
                                                    "type": "string",
                                                    "description": "Full name",
                                                },
                                            },
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets_created"] >= 1

        # Find the created asset
        endpoint = data["endpoints"][0]
        asset_id = endpoint["asset_id"]

        # Verify asset tags from operation tags
        asset_resp = await client.get(f"/api/v1/assets/{asset_id}")
        assert asset_resp.status_code == 200
        assert "users" in asset_resp.json()["tags"]
        assert "admin" in asset_resp.json()["tags"]

        # Verify field descriptions were extracted
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        contracts = contracts_resp.json()["results"]
        assert len(contracts) >= 1
        contract = contracts[0]
        # The response is nested: $.properties.response.properties.user_id
        assert "$.properties.response.properties.user_id" in contract["field_descriptions"]
        assert (
            contract["field_descriptions"]["$.properties.response.properties.user_id"]
            == "Unique user identifier"
        )


@pytest.mark.asyncio
class TestGraphQLSyncMetadata:
    """Test GraphQL sync extraction of field descriptions."""

    async def test_graphql_sync_extracts_arg_descriptions(self, client: AsyncClient) -> None:
        """GraphQL sync extracts argument descriptions into field_descriptions."""
        team_resp = await client.post("/api/v1/teams", json={"name": "graphql-meta-team"})
        team_id = team_resp.json()["id"]

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
                                "name": "user",
                                "description": "Fetch a single user",
                                "args": [
                                    {
                                        "name": "id",
                                        "description": "The user's unique identifier",
                                        "type": {
                                            "kind": "NON_NULL",
                                            "name": None,
                                            "ofType": {
                                                "kind": "SCALAR",
                                                "name": "ID",
                                                "ofType": None,
                                            },
                                        },
                                    }
                                ],
                                "type": {
                                    "kind": "OBJECT",
                                    "name": "User",
                                    "ofType": None,
                                },
                            }
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "fields": [
                            {
                                "name": "id",
                                "description": None,
                                "type": {
                                    "kind": "NON_NULL",
                                    "name": None,
                                    "ofType": {
                                        "kind": "SCALAR",
                                        "name": "ID",
                                        "ofType": None,
                                    },
                                },
                                "args": [],
                            },
                            {
                                "name": "name",
                                "description": None,
                                "type": {
                                    "kind": "SCALAR",
                                    "name": "String",
                                    "ofType": None,
                                },
                                "args": [],
                            },
                        ],
                    },
                    {"kind": "SCALAR", "name": "ID"},
                    {"kind": "SCALAR", "name": "String"},
                ],
            }
        }

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "schema_name": "MetaTestAPI",
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets_created"] >= 1

        # Find the created asset
        operation = data["operations"][0]
        asset_id = operation["asset_id"]

        # Verify field descriptions extracted from args
        contracts_resp = await client.get(f"/api/v1/assets/{asset_id}/contracts")
        assert contracts_resp.status_code == 200
        contracts = contracts_resp.json()["results"]
        assert len(contracts) >= 1
        contract = contracts[0]
        assert (
            contract["field_descriptions"]["$.properties.arguments.properties.id"]
            == "The user's unique identifier"
        )
