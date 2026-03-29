# ADR-011: Guarantee Diffing with Severity-Based Classification

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Data quality guarantees (not-null, unique, accepted_values, freshness, volume) are part of a contract's promise to consumers. When guarantees change between contract versions, consumers need to know — but not all guarantee changes carry the same risk.

Tightening a guarantee (fewer accepted values, stricter freshness SLA) is a safety improvement. Relaxing a guarantee (more accepted values, looser freshness) is a risk expansion. The system should distinguish between these.

## Decision

### Severity Classification

Guarantee changes are classified into two severity levels:

| Change Direction | Severity | Rationale |
|-----------------|----------|-----------|
| **Contracted** (stricter) | `INFO` | Producer is raising the bar. Consumers see better data. Safe. |
| **Expanded** (relaxed) | `WARNING` | Producer is lowering the bar. Consumers may see data they don't expect. Risky. |
| **Added** | `INFO` | New guarantee where none existed. Improvement. |
| **Removed** | `WARNING` | Guarantee withdrawn. Consumers lose a promise. |

### Guarantee Modes

Three modes control how guarantee changes interact with the publishing workflow:

| Mode | Behavior |
|------|----------|
| `NOTIFY` (default) | Guarantee changes are reported but don't block publishing. |
| `STRICT` | WARNING-level guarantee changes are treated as breaking. They trigger proposals and require acknowledgment. |
| `IGNORE` | Guarantee changes are not diffed at all. |

### Integration with Impact Preview

The `/assets/{id}/impact-preview` endpoint includes guarantee diffs alongside schema diffs, giving producers a complete picture of what their change affects before publishing.

## Consequences

**Benefits:**
- Consumers are informed about guarantee changes without being blocked by improvements.
- Teams that depend on specific guarantees can opt into `STRICT` mode for protection.
- The INFO/WARNING distinction maps to intuition: stricter is good, laxer is concerning.

**Costs:**
- `NOTIFY` is the default, meaning guarantee relaxation doesn't block by default. A consumer relying on a not-null guarantee won't be protected unless they've opted into `STRICT` mode.
- No per-guarantee mode control. A team can't say "strict on freshness, notify on accepted_values." It's all or nothing per asset.
- Guarantee history isn't versioned alongside contracts. Old contracts don't retroactively record what guarantees they had.

## Alternatives Considered

**All guarantee changes are breaking:** Simpler but too conservative. Adding a new not-null guarantee would require proposals from all consumers, discouraging quality improvements.

**Per-guarantee severity overrides:** Let teams configure which guarantee types are breaking. Deferred as premature — the current two-level system covers the common cases.
