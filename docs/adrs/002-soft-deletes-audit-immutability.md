# ADR-002: Soft Deletes and Audit Immutability

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Tessera's coordination model requires a complete historical record. When a team deletes an asset, the proposals, acknowledgments, and audit events that reference it must remain queryable. Without this, post-incident analysis becomes impossible — you can't answer "what happened" if the evidence was cascade-deleted.

## Decision

1. **All mutable entities use soft delete.** Teams, assets, registrations, and dependencies have a `deleted_at` column. Queries filter `WHERE deleted_at IS NULL` by default.

2. **No cascade deletes on any foreign key.** FK constraints exist for referential integrity but never cascade. Deleting a team does not touch its assets, contracts, or audit events.

3. **Audit events are append-only.** `AuditEventDB` has no `deleted_at` column and no update path. Once written, an audit event is permanent.

4. **Contracts and proposals are immutable once created.** Status transitions are allowed (PENDING → APPROVED), but the original data (schema, affected parties) is never modified.

## Consequences

**Benefits:**
- Full auditability: every action that ever occurred is recoverable
- Safe deletion: removing a team or asset is reversible
- FK integrity: PostgreSQL prevents orphaned references at the DB level

**Costs:**
- Every query must remember to filter soft-deleted rows. A missed filter surfaces ghost data. Mitigated by consistent query patterns and test coverage (`test_soft_delete_enforcement.py`).
- Storage grows monotonically. No automatic cleanup of old soft-deleted rows.
- Application complexity: "is this entity active?" requires checking `deleted_at`, not just existence.

## Alternatives Considered

**Hard deletes with archive tables:** Move deleted rows to shadow tables. Rejected because it doubles the schema surface and complicates queries that need to join current and historical data.

**Event sourcing:** Store all state as events and derive current state. Rejected as over-engineering for the current scale. The audit log provides event-like history without the infrastructure cost of a full event store.
