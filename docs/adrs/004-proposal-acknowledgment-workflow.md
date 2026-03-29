# ADR-004: Proposal-Acknowledgment Coordination Workflow

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

The core problem Tessera solves: a data producer wants to make a breaking schema change, but doesn't know who depends on their data or how to coordinate the rollout. The solution must be explicit (not best-effort), auditable (not Slack threads), and non-blocking for compatible changes.

## Decision

Breaking schema changes trigger a **proposal-acknowledgment workflow**:

1. Producer publishes a new contract with a breaking change.
2. Tessera detects the break via schema diff and creates a `Proposal` with status `PENDING`.
3. The proposal snapshots affected parties (teams and assets) as JSON at creation time.
4. Each affected team must submit an `Acknowledgment` with response type: `APPROVED`, `BLOCKED`, or `MIGRATING`.
5. When all affected teams have acknowledged (none blocked), the proposal can be published.
6. Producers can `force` publish at any time, bypassing acknowledgments. This is audit-logged.
7. Producers can `withdraw` a proposal. Proposals can auto-expire after a configurable deadline.

### State Machine

```
PENDING → APPROVED (all acks received, none blocked)
PENDING → REJECTED (any ack is BLOCKED)
PENDING → WITHDRAWN (producer cancels)
PENDING → EXPIRED (deadline passes with auto_expire=true)
APPROVED → PUBLISHED (producer publishes the approved change)
```

### Affected Parties as JSON Snapshots

Affected teams and assets are stored as JSON arrays on the proposal, not as foreign keys. This captures "who was affected at the time the proposal was created" even if registrations change later.

## Consequences

**Benefits:**
- Explicit coordination: no breaking change ships without acknowledgment (or a force flag with audit trail).
- Snapshot isolation: the affected party list is immutable, preventing race conditions where a consumer registers after a proposal is created.
- Non-blocking for compatible changes: only breaking changes enter the workflow.

**Costs:**
- JSON storage for affected parties means no efficient FK-based queries like "all proposals affecting asset X." Mitigated by the `pending-proposals` endpoint which queries by team.
- Force publish is an escape hatch that bypasses the entire workflow. Mitigated by audit logging — the force is visible in the trail.
- Snapshot isolation means a newly-registered consumer is invisible to an existing proposal. Mitigated by allowing new proposals to be created.

## Alternatives Considered

**Notification-only (no blocking):** Just tell consumers about changes. Rejected because notification without a blocking mechanism doesn't actually coordinate — it's a Slack message with extra steps.

**Approval chains (sequential):** Teams approve in order. Rejected as too rigid — parallel acknowledgment is faster and real-world coordination is concurrent.

**Automatic rollback on consumer failure:** If a consumer's pipeline breaks, auto-revert the schema change. Rejected as too dangerous — automatic rollbacks can cause cascading failures.
