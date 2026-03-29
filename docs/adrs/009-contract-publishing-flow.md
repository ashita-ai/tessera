# ADR-009: Three-Path Contract Publishing Flow

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Publishing a contract is the core action in Tessera. The system must handle three fundamentally different scenarios:

1. **First contract for an asset.** No consumers exist. No compatibility to check.
2. **Compatible change.** Schema evolves within the asset's compatibility mode. Consumers are unaffected.
3. **Breaking change.** Schema evolves in a way that violates the compatibility mode. Consumers must coordinate.

Each scenario has different implications for versioning, notification, and workflow.

## Decision

### Path 1: First Contract → Auto-Publish

When no active contract exists for an asset, the new contract is published immediately with version `1.0.0`. No diff is performed. No proposal is created.

**Rationale:** There are zero consumers to protect. Any gate would be friction without value.

### Path 2: Compatible Change → Auto-Publish + Deprecate

When the schema diff detects no breaking changes under the asset's compatibility mode:
- The new contract is published with an auto-incremented version (minor or patch, depending on change type).
- The previous active contract is marked `DEPRECATED`.
- Field-level metadata (descriptions, tags) from the old contract is merged into the new one, preserving human-authored annotations.

**Rationale:** Compatible changes are safe by definition. Blocking them would discourage schema evolution.

### Path 3: Breaking Change → Proposal or Reject

When the schema diff detects breaking changes:
- If `create_proposals_for_breaking=True` (default for sync endpoints): a Proposal is created with affected parties, entering the acknowledgment workflow (ADR-004).
- If `create_proposals_for_breaking=False`: the publish is rejected with a 409 Conflict listing the breaking changes.
- If `force=True`: the contract is published immediately, bypassing all checks. This is audit-logged with `action=FORCE_PUBLISH`.

### Write-Audit-Publish (WAP) Gate

Optionally, contracts can require a passing audit run (data quality checks) before publishing. If the most recent `AuditRun` for the asset has `status=FAILED`, the publish is rejected unless forced. This is opt-in per asset via `require_audit_pass`.

### Version Suggestion

The system detects the appropriate semver bump:
- **Major:** Breaking changes detected.
- **Minor:** Non-breaking additions (new columns, new enum values).
- **Patch:** No schema changes (metadata-only updates).

Three versioning modes control how suggestions are used:
- `AUTO`: System determines the version. Producer has no choice.
- `SUGGEST`: System suggests; producer can accept or override.
- `ENFORCE`: Producer provides a version; system validates it matches the detected change level.

## Consequences

**Benefits:**
- Zero-friction path for compatible changes encourages frequent, small schema evolution.
- Breaking changes are explicitly coordinated, preventing silent downstream failures.
- Force publish exists as an escape hatch for emergencies, with full audit trail.
- WAP integration connects data quality to the publishing pipeline.

**Costs:**
- Three code paths create maintenance burden. Each path has distinct logic for versioning, notification, and state transitions.
- Metadata merge (field descriptions carried forward) can silently propagate stale annotations if the old descriptions no longer apply to the new schema.
- Force publish undermines the coordination model. It's necessary (emergencies happen) but its existence means the guarantee is "coordination unless overridden," not "coordination always."
