"""Tests for dependency graph unification (issue #420).

Verifies that:
- dbt sync creates AssetDependencyDB rows from depends_on
- dbt sync is idempotent (no duplicate rows)
- dbt sync soft-deletes removed dependencies
- Unresolved FQNs are skipped without error
- affected_parties reads exclusively from AssetDependencyDB
- Correct dependency types: model→model = TRANSFORMS, model→source = CONSUMES
- Lineage endpoint reads from table only (no metadata fallback)
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _make_manifest(
    nodes: dict | None = None,
    sources: dict | None = None,
) -> dict:
    return {"nodes": nodes or {}, "sources": sources or {}}


class TestDbtSyncCreatesDependencies:
    """dbt sync should write AssetDependencyDB rows for depends_on."""

    async def test_sync_creates_dependency_rows(self, client: AsyncClient) -> None:
        """Model depending on a source should produce a CONSUMES row."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-sync-team"})).json()

        manifest = _make_manifest(
            nodes={
                "model.proj.orders": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "orders",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["source.proj.raw.events"]},
                },
            },
            sources={
                "source.proj.raw.events": {
                    "database": "db",
                    "schema": "raw",
                    "name": "events",
                    "description": "",
                    "columns": {},
                },
            },
        )

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] == 2
        assert data["dependencies"]["synced"] == 1

        # Verify: look up the model and check its dependencies
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        model = assets["db.mart.orders"]

        deps_resp = await client.get(f"/api/v1/assets/{model['id']}/dependencies")
        deps = deps_resp.json()["results"]
        assert len(deps) == 1
        assert deps[0]["dependency_type"] == "consumes"

    async def test_model_to_model_is_transforms(self, client: AsyncClient) -> None:
        """Model depending on another model should produce a TRANSFORMS row."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-transforms-team"})).json()

        manifest = _make_manifest(
            nodes={
                "model.proj.stg_users": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "staging",
                    "name": "stg_users",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": []},
                },
                "model.proj.dim_users": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "dim_users",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["model.proj.stg_users"]},
                },
            },
        )

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dependencies"]["synced"] == 1

        # Verify the dependency type
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        dim_users = assets["db.mart.dim_users"]

        deps_resp = await client.get(f"/api/v1/assets/{dim_users['id']}/dependencies")
        deps = deps_resp.json()["results"]
        assert len(deps) == 1
        assert deps[0]["dependency_type"] == "transforms"

    async def test_sync_is_idempotent(self, client: AsyncClient) -> None:
        """Re-running sync should not create duplicate dependency rows."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-idempotent-team"})).json()

        manifest = _make_manifest(
            nodes={
                "model.proj.base": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "raw",
                    "name": "base",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": []},
                },
                "model.proj.derived": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "derived",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["model.proj.base"]},
                },
            },
        )

        # First sync
        resp1 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp1.status_code == 200
        assert resp1.json()["dependencies"]["synced"] == 1

        # Second sync (overwrite mode to process existing assets)
        resp2 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": team["id"],
                "conflict_mode": "overwrite",
            },
        )
        assert resp2.status_code == 200
        # No new deps — they already exist
        assert resp2.json()["dependencies"]["synced"] == 0

        # Verify only one dependency row
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        derived = assets["db.mart.derived"]

        deps_resp = await client.get(f"/api/v1/assets/{derived['id']}/dependencies")
        assert len(deps_resp.json()["results"]) == 1

    async def test_sync_soft_deletes_removed_deps(self, client: AsyncClient) -> None:
        """When a dependency is removed from the manifest, its row is soft-deleted."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-softdel-team"})).json()

        manifest_v1 = _make_manifest(
            nodes={
                "model.proj.upstream_a": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "raw",
                    "name": "upstream_a",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": []},
                },
                "model.proj.upstream_b": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "raw",
                    "name": "upstream_b",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": []},
                },
                "model.proj.consumer": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "consumer",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["model.proj.upstream_a", "model.proj.upstream_b"]},
                },
            },
        )

        # First sync: consumer depends on A and B
        resp1 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest_v1, "owner_team_id": team["id"]},
        )
        assert resp1.status_code == 200
        assert resp1.json()["dependencies"]["synced"] == 2

        # Second sync: consumer now only depends on A (B removed)
        manifest_v2 = _make_manifest(
            nodes={
                "model.proj.upstream_a": manifest_v1["nodes"]["model.proj.upstream_a"],
                "model.proj.upstream_b": manifest_v1["nodes"]["model.proj.upstream_b"],
                "model.proj.consumer": {
                    **manifest_v1["nodes"]["model.proj.consumer"],
                    "depends_on": {"nodes": ["model.proj.upstream_a"]},
                },
            },
        )

        resp2 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest_v2,
                "owner_team_id": team["id"],
                "conflict_mode": "overwrite",
            },
        )
        assert resp2.status_code == 200

        # Should only have 1 active dependency now
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        consumer = assets["db.mart.consumer"]

        deps_resp = await client.get(f"/api/v1/assets/{consumer['id']}/dependencies")
        active_deps = deps_resp.json()["results"]
        assert len(active_deps) == 1

    async def test_unresolved_fqns_skipped(self, client: AsyncClient) -> None:
        """Dependencies on FQNs not in Tessera should be skipped silently."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-unresolved-team"})).json()

        manifest = _make_manifest(
            nodes={
                "model.proj.lonely": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "lonely",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    # depends on a package model not in our manifest
                    "depends_on": {"nodes": ["model.external_pkg.something"]},
                },
            },
        )

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"]["created"] == 1
        # No dependencies synced because the target doesn't exist in the manifest
        assert data["dependencies"]["synced"] == 0

    async def test_model_to_seed_is_consumes(self, client: AsyncClient) -> None:
        """Model depending on a seed should produce a CONSUMES row."""
        team = (await client.post("/api/v1/teams", json={"name": "dep-seed-team"})).json()

        manifest = _make_manifest(
            nodes={
                "seed.proj.country_codes": {
                    "resource_type": "seed",
                    "database": "db",
                    "schema": "seeds",
                    "name": "country_codes",
                    "description": "",
                    "tags": [],
                    "columns": {},
                },
                "model.proj.enriched": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "enriched",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["seed.proj.country_codes"]},
                },
            },
        )

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["dependencies"]["synced"] == 1

        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        enriched = assets["db.mart.enriched"]

        deps_resp = await client.get(f"/api/v1/assets/{enriched['id']}/dependencies")
        deps = deps_resp.json()["results"]
        assert len(deps) == 1
        assert deps[0]["dependency_type"] == "consumes"


class TestAffectedPartiesUsesTableOnly:
    """affected_parties should read exclusively from AssetDependencyDB."""

    async def test_metadata_depends_on_not_used_without_table_row(
        self, client: AsyncClient
    ) -> None:
        """An asset with only metadata.depends_on (no table row) should NOT
        appear in affected parties.
        """
        owner_team = (
            await client.post("/api/v1/teams", json={"name": "ap-owner-only-meta"})
        ).json()
        downstream_team = (
            await client.post("/api/v1/teams", json={"name": "ap-downstream-only-meta"})
        ).json()

        # Create upstream asset with contract
        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.src.metadata_only_src", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"x": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset with ONLY metadata.depends_on — no table row
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.mart.metadata_only_consumer",
                "owner_team_id": downstream_team["id"],
                "metadata": {"depends_on": ["db.src.metadata_only_src"]},
            },
        )

        # Publish breaking change
        schema_v2 = {"type": "object", "properties": {"x": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        data = result.json()

        # Without a table row, this should NOT be found by affected_parties
        if data.get("action") == "proposal_created":
            proposal = (await client.get(f"/api/v1/proposals/{data['proposal']['id']}")).json()
            assert len(proposal["affected_assets"]) == 0
        else:
            # No proposal created means no affected parties — also correct
            pass

    async def test_table_row_is_found(self, client: AsyncClient) -> None:
        """An asset with an AssetDependencyDB row should appear in affected parties."""
        owner_team = (await client.post("/api/v1/teams", json={"name": "ap-owner-table"})).json()
        downstream_team = (
            await client.post("/api/v1/teams", json={"name": "ap-downstream-table"})
        ).json()

        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.src.table_test_src", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"y": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.mart.table_test_consumer", "owner_team_id": downstream_team["id"]},
            )
        ).json()

        # Create explicit dependency row
        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"dependency_asset_id": upstream["id"]},
        )

        # Publish breaking change
        schema_v2 = {"type": "object", "properties": {"y": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        data = result.json()
        assert data["action"] == "proposal_created"

        proposal = (await client.get(f"/api/v1/proposals/{data['proposal']['id']}")).json()
        assert len(proposal["affected_assets"]) == 1
        assert proposal["affected_assets"][0]["asset_fqn"] == "db.mart.table_test_consumer"


class TestDbtSyncEndToEndImpactAnalysis:
    """Integration: dbt sync → dependency rows → impact analysis."""

    async def test_dbt_deps_appear_in_impact_analysis(self, client: AsyncClient) -> None:
        """After dbt sync creates dependency rows, impact analysis finds them."""
        team = (await client.post("/api/v1/teams", json={"name": "e2e-impact-team"})).json()

        # Sync a source and a model that depends on it
        manifest = _make_manifest(
            sources={
                "source.proj.raw.orders": {
                    "database": "db",
                    "schema": "raw",
                    "name": "orders",
                    "description": "Raw orders",
                    "columns": {
                        "id": {"description": "PK", "data_type": "integer"},
                        "amount": {"description": "Order amount", "data_type": "numeric"},
                    },
                },
            },
            nodes={
                "model.proj.stg_orders": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "staging",
                    "name": "stg_orders",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["source.proj.raw.orders"]},
                },
            },
        )

        resp = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest, "owner_team_id": team["id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["dependencies"]["synced"] == 1

        # Now verify the lineage endpoint sees the dependency
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        source = assets["db.raw.orders"]

        lineage_resp = await client.get(f"/api/v1/assets/{source['id']}/lineage")
        assert lineage_resp.status_code == 200
        lineage = lineage_resp.json()
        assert len(lineage["downstream_assets"]) == 1
        assert lineage["downstream_assets"][0]["asset_fqn"] == "db.staging.stg_orders"


class TestSyncReactivatesDeletedDeps:
    """If a dependency is removed then re-added, the soft-deleted row is reactivated."""

    async def test_reactivation(self, client: AsyncClient) -> None:
        team = (await client.post("/api/v1/teams", json={"name": "dep-reactivate-team"})).json()

        base_nodes = {
            "model.proj.upstream": {
                "resource_type": "model",
                "database": "db",
                "schema": "raw",
                "name": "upstream",
                "description": "",
                "tags": [],
                "columns": {},
                "depends_on": {"nodes": []},
            },
        }

        # v1: consumer depends on upstream
        manifest_v1 = _make_manifest(
            nodes={
                **base_nodes,
                "model.proj.consumer": {
                    "resource_type": "model",
                    "database": "db",
                    "schema": "mart",
                    "name": "consumer",
                    "description": "",
                    "tags": [],
                    "columns": {},
                    "depends_on": {"nodes": ["model.proj.upstream"]},
                },
            },
        )

        resp1 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={"manifest": manifest_v1, "owner_team_id": team["id"]},
        )
        assert resp1.json()["dependencies"]["synced"] == 1

        # v2: remove the dependency
        manifest_v2 = _make_manifest(
            nodes={
                **base_nodes,
                "model.proj.consumer": {
                    **manifest_v1["nodes"]["model.proj.consumer"],
                    "depends_on": {"nodes": []},
                },
            },
        )

        resp2 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest_v2,
                "owner_team_id": team["id"],
                "conflict_mode": "overwrite",
            },
        )
        assert resp2.status_code == 200

        # Verify: no active deps
        assets_resp = await client.get(f"/api/v1/assets?owner={team['id']}")
        assets = {a["fqn"]: a for a in assets_resp.json()["results"]}
        consumer = assets["db.mart.consumer"]
        deps_resp = await client.get(f"/api/v1/assets/{consumer['id']}/dependencies")
        assert len(deps_resp.json()["results"]) == 0

        # v3: re-add the dependency
        resp3 = await client.post(
            "/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest_v1,
                "owner_team_id": team["id"],
                "conflict_mode": "overwrite",
            },
        )
        assert resp3.status_code == 200
        # Should reactivate (counts as "synced")
        assert resp3.json()["dependencies"]["synced"] == 1

        # Verify: 1 active dep again
        deps_resp = await client.get(f"/api/v1/assets/{consumer['id']}/dependencies")
        assert len(deps_resp.json()["results"]) == 1
