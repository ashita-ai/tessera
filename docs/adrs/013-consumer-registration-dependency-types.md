# ADR-013: Consumer Registration with Dependency Types and Pinned Versions

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

The proposal-acknowledgment workflow (ADR-004) depends on knowing who consumes each asset. Without a dependency graph, impact analysis is impossible and proposals can't identify affected parties.

The dependency graph must capture not just *that* a dependency exists, but *what kind* of dependency it is — a dashboard that reads a table has a different relationship than a dbt model that transforms it. And consumers need a way to pin to a specific contract version when they're not ready to upgrade.

## Decision

### Registration Model

Consumers register dependencies by creating a `Registration` linking their team to an asset. Registrations are:
- **Active by default.** Created with `status=ACTIVE`.
- **Soft-deletable.** Deregistration sets `deleted_at`, preserving the historical record.
- **Pinnable.** Optional `pinned_version` locks the consumer to a specific contract version.

### Dependency Types

Three types classify the relationship:

| Type | Meaning | Example |
|------|---------|---------|
| `CONSUMES` | Direct read dependency. Consumer queries the asset's data. | A dashboard reading from `orders`. |
| `REFERENCES` | Foreign key or lookup relationship. Consumer joins against the asset. | A model that joins `orders` with `customers` on `customer_id`. |
| `TRANSFORMS` | The consumer's output is derived from this asset. | A dbt model with `depends_on: [orders]`. |

### Dual Discovery: Explicit + Implicit

Dependencies come from two sources:
1. **Explicit registration:** A team calls `POST /registrations` to declare a dependency.
2. **Implicit from sync:** dbt manifest `depends_on` fields create dependencies automatically during `POST /sync/dbt`.

The `affected_parties` service unions both sources when computing impact.

### Status Transitions

```
ACTIVE → MIGRATING (consumer is upgrading to new contract version)
ACTIVE → INACTIVE (soft-deleted via deregistration)
MIGRATING → ACTIVE (upgrade complete)
```

`MIGRATING` status is informational — it tells the proposal workflow that this consumer is in transition but hasn't finished yet. It doesn't block proposals.

## Consequences

**Benefits:**
- Impact analysis covers both explicit and implicit dependencies, reducing blind spots.
- Dependency types enable targeted notifications. A `TRANSFORMS` dependency might need a different migration path than a `CONSUMES` dependency.
- Pinned versions let consumers opt out of automatic upgrades until they're ready.

**Costs:**
- **Cold-start problem.** Impact analysis is only as good as the dependency graph. If consumers don't register and don't use dbt sync, the graph is empty and proposals notify no one. This is the system's most critical weakness.
- `MIGRATING` status is advisory only. There's no automatic transition to `ACTIVE` after a deadline, no enforcement that the migration actually completes.
- Pinned versions require explicit management. If a consumer pins to `1.2.0` and the asset is now on `3.0.0`, there's no mechanism to detect or warn about the drift.

## Alternatives Considered

**Automatic discovery from query logs:** Analyze warehouse query history to detect dependencies without manual registration. Deferred as a separate initiative — it's the highest-leverage improvement to the dependency graph but requires warehouse-specific integrations (BigQuery audit logs, Snowflake query history, etc.).

**Fine-grained column-level dependencies:** Track which specific columns a consumer uses, not just which asset. Deferred — useful for precise impact analysis but significantly increases registration complexity and storage.
