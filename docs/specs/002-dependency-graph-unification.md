# Spec 002: Dependency Graph Unification

**Strategy doc**: [Passive Discovery](../strategy/passive-discovery.md), Phase 3
**Priority**: 2 (prerequisite for warehouse connectors and column-level tracking)
**Status**: Draft
**Estimated effort**: 2-3 weeks

## Problem

Tessera stores dependency information in two disconnected systems:

1. **`AssetDependencyDB` table** — explicit asset-to-asset edges with typed relationships (CONSUMES, REFERENCES, TRANSFORMS). Created manually via `POST /dependencies`. Used by impact analysis graph traversal.

2. **`metadata_.depends_on` JSON array** — list of upstream FQNs stored on each asset's metadata blob. Populated by dbt sync. Used as a fallback by the `affected_parties` service via LIKE query on JSON.

This split causes three problems:

**Impact analysis is incomplete.** The `POST /assets/{id}/impact` endpoint traverses `AssetDependencyDB` only. dbt-sourced dependencies that live in `metadata_.depends_on` are invisible to impact analysis unless they also exist in the table.

**affected_parties uses both but inconsistently.** It checks the table first, then falls back to a LIKE query on `metadata_`. The LIKE query is imprecise (substring matching on JSON) and can produce false positives for FQNs that are substrings of other FQNs.

**Adding a third source (inferred dependencies) makes fragmentation worse.** Passive discovery (Spec 001) adds confirmed inferences that promote to registrations. But registrations track team-to-contract relationships, while dependencies track asset-to-asset relationships. These are related but not the same. Without unification, we'll have three places to look and no single source of truth.

## Decision

**`AssetDependencyDB` becomes the single authoritative source for asset-to-asset edges.** All dependency sources write to this table. All consumers read from this table.

## Changes

### 1. dbt Sync Writes to AssetDependencyDB

**Current behavior** (`upload.py`, lines 134-150): dbt sync stores `depends_on` FQNs in `metadata_["depends_on"]` but does not create `AssetDependencyDB` rows.

**New behavior**: After processing each node's `depends_on`, create or update `AssetDependencyDB` rows:

```python
async def _sync_dependencies(
    session: AsyncSession,
    asset: AssetDB,
    depends_on_fqns: list[str],
    all_assets_by_fqn: dict[str, AssetDB],
) -> None:
    """Sync asset dependencies from dbt depends_on to AssetDependencyDB.

    For each FQN in depends_on:
    1. Resolve to an asset (skip if asset not managed by Tessera)
    2. Upsert AssetDependencyDB row with type=TRANSFORMS
    3. Soft-delete any existing dependencies not in the current depends_on
       (the model removed an upstream reference)
    """
```

**Dependency type mapping:**

| dbt relationship | DependencyType |
|-----------------|----------------|
| Model depends on model | `TRANSFORMS` |
| Model depends on source | `CONSUMES` |
| Model depends on seed | `CONSUMES` |
| Model depends on snapshot | `CONSUMES` |

**Retain `metadata_.depends_on`**: Continue writing to metadata for backward compatibility and for display purposes. But impact analysis and affected_parties no longer read from it.

### 2. affected_parties Reads from AssetDependencyDB Only

**Current behavior** (`affected_parties.py`): Two-phase query — table first, then `metadata_` LIKE fallback.

**New behavior**: Single query against `AssetDependencyDB`.

```python
async def get_affected_parties(
    session: AsyncSession,
    asset_id: UUID,
    exclude_team_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get teams and assets affected by changes to this asset.

    Queries AssetDependencyDB for all downstream edges where
    dependency_asset_id = asset_id. No metadata fallback.
    """
    query = (
        select(AssetDB, TeamDB)
        .join(AssetDependencyDB, AssetDependencyDB.dependent_asset_id == AssetDB.id)
        .join(TeamDB, AssetDB.owner_team_id == TeamDB.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(AssetDB.deleted_at.is_(None))
    )
    if exclude_team_id:
        query = query.where(AssetDB.owner_team_id != exclude_team_id)

    # ... rest of aggregation logic unchanged
```

This eliminates the LIKE query, the imprecise substring matching, and the two-phase complexity.

### 3. Impact Analysis Uses Unified Graph

**Current behavior** (`impact.py`): BFS traversal of `AssetDependencyDB` only.

**No change needed.** Impact analysis already reads from the table. Once dbt sync writes to the table (change #1), dbt-sourced dependencies automatically appear in impact analysis without any change to the traversal code.

### 4. Migration: Backfill Existing metadata_.depends_on

A one-time migration script (not an Alembic migration — this is a data backfill, not a schema change) that:

1. Iterates all assets where `metadata_["depends_on"]` is non-empty.
2. For each FQN in `depends_on`, resolves to an asset ID.
3. Creates `AssetDependencyDB` rows with `dependency_type=TRANSFORMS` (or `CONSUMES` for sources/seeds).
4. Logs the backfill results.

```python
async def backfill_dependencies_from_metadata(
    session: AsyncSession,
) -> dict[str, int]:
    """One-time backfill: create AssetDependencyDB rows from metadata.depends_on.

    Returns:
        {"created": N, "skipped_already_exists": M, "skipped_unresolved": P}
    """
```

This runs as a CLI command: `tessera admin backfill-dependencies`.

### 5. Lineage Endpoint Update

The `GET /assets/{id}/lineage` endpoint currently merges results from both sources. After unification, it reads from `AssetDependencyDB` only and returns a cleaner, more reliable result.

**Upstream**: `WHERE dependent_asset_id = asset_id` (this asset depends on...)
**Downstream**: `WHERE dependency_asset_id = asset_id` (...depends on this asset)

## Schema Changes

No new tables. No new columns. The `AssetDependencyDB` table already has everything needed. The only schema change is potentially adding an index:

```python
# Migration 017 (or combined with Spec 001's migration)
# Index for efficient downstream lookup during dbt sync
Index("ix_asset_dependencies_dependency_asset", "dependency_asset_id", "deleted_at")
```

This index may already exist — verify before adding.

## Edge Cases

### FQN Resolution Failures

During dbt sync, `depends_on` may reference FQNs that Tessera doesn't manage (e.g., external packages, ephemeral models). These are skipped silently — no `AssetDependencyDB` row created. The `metadata_.depends_on` continues to store the full list including unresolved FQNs, preserving the original dbt metadata.

### Duplicate Dependencies

dbt sync runs repeatedly. Each run must be idempotent:
- If an `AssetDependencyDB` row already exists for (dependent, dependency, type), skip.
- If a dependency was removed in the manifest (FQN no longer in `depends_on`), soft-delete the row.
- Use the unique constraint `(dependent_asset_id, dependency_asset_id, dependency_type)` for upsert logic.

### Cross-Sync Deletion

If Model A depends on Source B in one dbt sync, and the next sync removes that dependency, the `AssetDependencyDB` row should be soft-deleted. This requires comparing the current `depends_on` list to the existing rows and deleting the diff.

```python
# After syncing all dependencies for an asset:
existing_deps = await get_existing_dependencies(session, asset_id)
current_fqns = set(depends_on_fqns)
for dep in existing_deps:
    if dep.dependency_fqn not in current_fqns:
        dep.deleted_at = func.now()
```

### Circular Dependencies

dbt prevents circular dependencies at the model level, but post-sync manual dependency creation could create cycles. The existing graph traversal already has a `max_depth` limit (default 10) and visited-node tracking to handle this. No additional protection needed.

## Testing

| Test case | Assertion |
|-----------|-----------|
| dbt sync creates dependencies | `AssetDependencyDB` rows created for each `depends_on` FQN |
| dbt sync is idempotent | Re-running sync doesn't create duplicate rows |
| dbt sync removes stale deps | Dependency soft-deleted when removed from manifest |
| Unresolved FQNs skipped | No row created for FQNs not in Tessera |
| affected_parties uses table only | LIKE query on metadata_ no longer executed |
| Impact analysis includes dbt deps | Downstream dbt models appear in impact traversal |
| Backfill script | Creates rows from existing metadata_.depends_on |
| Backfill is idempotent | Re-running backfill doesn't create duplicates |
| Lineage endpoint unified | Returns consistent results from single source |
| Source vs model dependency type | CONSUMES for sources/seeds, TRANSFORMS for models |

## Migration Strategy

1. **Write**: Ship dbt sync changes that write to both `metadata_.depends_on` AND `AssetDependencyDB`. This is additive — nothing breaks.
2. **Backfill**: Run backfill script on deployed instances to create rows from existing metadata.
3. **Read**: Switch `affected_parties` to read from table only. Deploy and monitor — verify impact analysis results don't change.
4. **Deprecate**: Mark `metadata_.depends_on` as deprecated in code comments. Continue writing for backward compatibility. Stop reading for impact/affected_parties.

Steps 1-2 are safe to deploy independently. Step 3 is the behavioral change. Step 4 is cleanup.
