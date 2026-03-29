"""Tests for deep merge metadata across all sync endpoints.

Validates that re-syncing with partial metadata preserves previously-set
nested keys rather than silently destroying them via shallow dict merge.
See: https://github.com/ashita-ai/tessera/issues/381
"""

import pytest

from tessera.api.sync.helpers import deep_merge_metadata

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for deep_merge_metadata
# ---------------------------------------------------------------------------


class TestDeepMergeMetadata:
    """Pure unit tests for the recursive merge function."""

    def test_disjoint_keys_are_combined(self) -> None:
        base = {"a": 1}
        updates = {"b": 2}
        assert deep_merge_metadata(base, updates) == {"a": 1, "b": 2}

    def test_scalar_overwrite(self) -> None:
        base = {"a": 1}
        updates = {"a": 2}
        assert deep_merge_metadata(base, updates) == {"a": 2}

    def test_nested_dicts_merge_recursively(self) -> None:
        base = {"guarantees": {"freshness": "1h", "format": "parquet"}}
        updates = {"guarantees": {"freshness": "2h"}}
        result = deep_merge_metadata(base, updates)
        assert result == {"guarantees": {"freshness": "2h", "format": "parquet"}}

    def test_deeply_nested_merge(self) -> None:
        base = {"a": {"b": {"c": 1, "d": 2}, "e": 3}}
        updates = {"a": {"b": {"c": 99}}}
        result = deep_merge_metadata(base, updates)
        assert result == {"a": {"b": {"c": 99, "d": 2}, "e": 3}}

    def test_top_level_key_preserved_when_absent_in_update(self) -> None:
        base = {"owner_contact": "alice@co", "guarantees": {"freshness": "1h"}}
        updates = {"guarantees": {"freshness": "2h"}}
        result = deep_merge_metadata(base, updates)
        assert result["owner_contact"] == "alice@co"
        assert result["guarantees"] == {"freshness": "2h"}

    def test_list_values_are_replaced_not_appended(self) -> None:
        """Lists are atomic values — the update wins entirely."""
        base = {"tags": ["old"]}
        updates = {"tags": ["new"]}
        assert deep_merge_metadata(base, updates) == {"tags": ["new"]}

    def test_type_change_dict_to_scalar(self) -> None:
        """If a value changes from dict to scalar, the update wins."""
        base = {"x": {"nested": True}}
        updates = {"x": "replaced"}
        assert deep_merge_metadata(base, updates) == {"x": "replaced"}

    def test_type_change_scalar_to_dict(self) -> None:
        """If a value changes from scalar to dict, the update wins."""
        base = {"x": "old"}
        updates = {"x": {"nested": True}}
        assert deep_merge_metadata(base, updates) == {"x": {"nested": True}}

    def test_empty_base(self) -> None:
        assert deep_merge_metadata({}, {"a": 1}) == {"a": 1}

    def test_empty_updates(self) -> None:
        assert deep_merge_metadata({"a": 1}, {}) == {"a": 1}

    def test_both_empty(self) -> None:
        assert deep_merge_metadata({}, {}) == {}

    def test_original_dicts_are_not_mutated(self) -> None:
        base = {"a": {"b": 1}}
        updates = {"a": {"c": 2}}
        _ = deep_merge_metadata(base, updates)
        assert base == {"a": {"b": 1}}
        assert updates == {"a": {"c": 2}}

    def test_issue_381_exact_scenario(self) -> None:
        """Reproduce the exact scenario described in issue #381."""
        existing = {
            "guarantees": {"freshness": "1h", "format": "parquet"},
            "owner_contact": "alice@co",
        }
        incoming = {"guarantees": {"freshness": "2h"}}
        result = deep_merge_metadata(existing, incoming)
        assert result == {
            "guarantees": {"freshness": "2h", "format": "parquet"},
            "owner_contact": "alice@co",
        }


# ---------------------------------------------------------------------------
# Integration tests: OpenAPI sync preserves nested metadata
# ---------------------------------------------------------------------------


class TestOpenAPISyncDeepMerge:
    """Re-importing an OpenAPI spec should deep-merge metadata on existing assets."""

    async def _make_openapi_spec(self, title: str = "Pet Store") -> dict:
        return {
            "openapi": "3.0.0",
            "info": {"title": title, "version": "1.0.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "summary": "List all pets",
                        "responses": {
                            "200": {
                                "description": "A list of pets",
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
                                },
                            }
                        },
                    }
                }
            },
        }

    async def test_resync_preserves_nested_metadata(self, client) -> None:
        # Create team
        team_resp = await client.post("/api/v1/teams", json={"name": "openapi-team"})
        team_id = team_resp.json()["id"]

        spec = await self._make_openapi_spec()

        # First import — creates assets
        resp1 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": spec, "owner_team_id": team_id},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["assets_created"] == 1
        asset_id = data1["endpoints"][0]["asset_id"]

        # Manually inject nested metadata to simulate accumulated state
        asset_resp = await client.get(f"/api/v1/assets/{asset_id}")
        original_metadata = asset_resp.json()["metadata"]

        await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={
                "metadata": {
                    **original_metadata,
                    "custom_field": "should_survive",
                    "guarantees": {"freshness": "1h", "format": "parquet"},
                }
            },
        )

        # Re-import same spec — should deep-merge, not replace
        resp2 = await client.post(
            "/api/v1/sync/openapi",
            json={"spec": spec, "owner_team_id": team_id},
        )
        assert resp2.status_code == 200
        assert resp2.json()["assets_updated"] == 1

        # Verify nested metadata survived
        final_resp = await client.get(f"/api/v1/assets/{asset_id}")
        final_metadata = final_resp.json()["metadata"]
        assert final_metadata.get("custom_field") == "should_survive"
        # guarantees is a dict — the openapi sync may set its own keys,
        # but "format" should survive if the sync doesn't touch it
        if "guarantees" in final_metadata:
            assert final_metadata["guarantees"].get("format") == "parquet"


# ---------------------------------------------------------------------------
# Integration tests: dbt sync preserves nested metadata
# ---------------------------------------------------------------------------


class TestDbtSyncDeepMerge:
    """Re-uploading a dbt manifest should deep-merge metadata on existing assets."""

    def _make_manifest(self) -> dict:
        return {
            "metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"},
            "nodes": {
                "model.my_project.orders": {
                    "resource_type": "model",
                    "database": "analytics",
                    "schema": "public",
                    "name": "orders",
                    "description": "Customer orders",
                    "columns": {
                        "id": {"name": "id", "description": "Primary key", "data_type": "integer"},
                        "amount": {
                            "name": "amount",
                            "description": "Order amount",
                            "data_type": "numeric",
                        },
                    },
                    "tags": ["finance"],
                    "fqn": ["my_project", "orders"],
                    "path": "models/orders.sql",
                    "depends_on": {"nodes": []},
                    "meta": {},
                    "config": {},
                }
            },
            "sources": {},
        }

    async def test_resync_preserves_nested_metadata(self, client) -> None:
        team_resp = await client.post("/api/v1/teams", json={"name": "dbt-team"})
        team_id = team_resp.json()["id"]

        manifest = self._make_manifest()

        # First upload
        resp1 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
            },
        )
        assert resp1.status_code == 200
        assert resp1.json()["assets"]["created"] == 1

        # Find asset and inject nested metadata
        assets_resp = await client.get(f"/api/v1/assets?owner={team_id}")
        asset = assets_resp.json()["results"][0]
        asset_id = asset["id"]

        asset_detail = await client.get(f"/api/v1/assets/{asset_id}")
        original_metadata = asset_detail.json()["metadata"]

        await client.patch(
            f"/api/v1/assets/{asset_id}",
            json={
                "metadata": {
                    **original_metadata,
                    "sla_contact": "ops@co",
                    "guarantees": {"freshness": "1h", "volume": "10k"},
                }
            },
        )

        # Re-upload same manifest with overwrite
        resp2 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team_id,
                "conflict_mode": "overwrite",
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["assets"]["updated"] == 1

        # Verify deep-merged metadata
        final_resp = await client.get(f"/api/v1/assets/{asset_id}")
        final_metadata = final_resp.json()["metadata"]
        assert final_metadata.get("sla_contact") == "ops@co"
        # The dbt manifest doesn't set guarantees (no tests), so the
        # manually-set guarantees should survive entirely
        if "guarantees" not in manifest["nodes"]["model.my_project.orders"].get("meta", {}):
            assert final_metadata.get("guarantees", {}).get("freshness") == "1h"
            assert final_metadata.get("guarantees", {}).get("volume") == "10k"
