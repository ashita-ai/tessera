# ADR-005: Kafka-Inspired Compatibility Modes

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Not all schema changes are equal, and not all teams have the same tolerance for change. A team that owns a critical financial report needs strict compatibility checking. A team running experimental dashboards might not care. The system needs a way to express this.

Kafka's Schema Registry solved this problem for event streams with four compatibility modes. The semantics are well-understood by data engineers and map cleanly to the producer-consumer relationship.

## Decision

Four compatibility modes, set per-asset:

| Mode | Breaking if... | Use case |
|------|----------------|----------|
| `BACKWARD` | Consumers of old data can't read new schema. Remove field, add required, narrow type, remove enum value. | Default. Producers evolve; consumers stay stable. |
| `FORWARD` | Producers of old schema can't produce data matching new schema. Add field, remove required, widen type, add enum value. | Consumers evolve first; producers catch up. |
| `FULL` | Either direction breaks. Union of backward and forward breaking changes. | Maximum safety. Both sides must be stable. |
| `NONE` | Nothing is breaking. All changes auto-publish. Consumers are still notified. | Experimental assets, internal-only data. |

The schema diff engine classifies each change into one of 18 `ChangeKind` values, then checks whether that kind is breaking under the asset's compatibility mode. If any breaking change is detected, a proposal is created.

## Consequences

**Benefits:**
- Proven semantics. Engineers who've used Kafka Schema Registry already understand the model.
- Per-asset flexibility. Critical tables use `FULL`; experimental ones use `NONE`.
- The diff engine is mode-agnostic — it detects all changes, then the mode determines which are breaking.

**Costs:**
- `FORWARD` compatibility is rarely used in practice for warehouse data (it's more relevant for streaming). Including it adds cognitive load without proportional value.
- No custom compatibility rules. A team can't say "removing a column is fine if it hasn't been queried in 90 days." The modes are fixed categories.
- Mode changes on an existing asset can be confusing. Switching from `NONE` to `FULL` doesn't retroactively flag past changes.

## Alternatives Considered

**Binary compatible/incompatible:** Simpler but too blunt. Doesn't capture the directionality of compatibility (who can evolve independently).

**Custom rule engine:** Let teams define arbitrary compatibility rules. Rejected as premature complexity — the four modes cover 95% of real-world needs.

**Per-field compatibility:** Different compatibility modes for different columns. Rejected as too granular — it would make the proposal workflow incomprehensible.
