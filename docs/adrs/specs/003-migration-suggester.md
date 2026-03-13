# Spec 003: Migration Suggester Service

**ADR**: 001-ai-enablement
**Priority**: 3
**Status**: Draft

## Overview

A rule-based service that takes a breaking schema change and produces one or more non-breaking migration alternatives. Returns modified schemas that an agent (or human) can adopt instead of forcing a breaking change through the proposal workflow.

## Interface

```python
# services/migration_suggester.py

@dataclass
class MigrationSuggestion:
    strategy: str          # e.g., "additive", "deprecate", "widen", "default"
    description: str       # human-readable explanation
    confidence: str        # "high", "medium", "low"
    suggested_schema: dict # the modified schema that avoids the break
    changes_made: list[str] # list of modifications applied

def suggest_migrations(
    old_schema: dict,
    new_schema: dict,
    breaking_changes: list[BreakingChange],
    compatibility_mode: CompatibilityMode,
) -> list[MigrationSuggestion]:
    """
    Generate non-breaking migration alternatives for each breaking change.

    Returns an empty list if no automated suggestions are possible.
    May return multiple suggestions ranked by confidence.
    """
```

## Rules

Each rule handles one `BreakingChange.kind` and produces a modified schema. Rules are applied independently — when multiple breaking changes exist, the service attempts to compose them into a single suggested schema. If composition fails (conflicting modifications), it falls back to per-change suggestions.

### Rule 1: Property Removed (BACKWARD breaking)

**Trigger**: `BreakingChange.kind == PROPERTY_REMOVED`

**Strategy**: `"deprecate"`

**Action**: Re-add the removed property to the new schema, marked as deprecated.
- Copy the property definition from the old schema
- Add `"deprecated": true` to the property
- Add `"description": "Deprecated: scheduled for removal in a future version"` (preserving any existing description with a prefix)
- If the property was in `required`, keep it in `required`

**Confidence**: `"high"` — this is always a valid backward-compatible alternative.

**Example**:
```
Old: { "properties": { "user_id": { "type": "integer" }, "name": { "type": "string" } } }
New: { "properties": { "name": { "type": "string" } } }

Suggestion: { "properties": { "user_id": { "type": "integer", "deprecated": true }, "name": { "type": "string" } } }
```

### Rule 2: Required Field Added (BACKWARD breaking)

**Trigger**: `BreakingChange.kind == REQUIRED_FIELD_ADDED`

**Strategy**: `"default"`

**Action**: Make the new required field optional instead.
- Remove the field from the `required` array
- If the field's type allows it, add a `"default"` value:
  - `string` -> `""`
  - `integer` / `number` -> `0`
  - `boolean` -> `false`
  - `array` -> `[]`
  - `object` -> `{}`
  - `null` / unknown -> no default, just make optional

**Confidence**: `"high"` if a sensible default exists, `"medium"` if no default can be inferred.

### Rule 3: Type Narrowed (BACKWARD breaking)

**Trigger**: `BreakingChange.kind == TYPE_CHANGED` where old type is wider than new type

**Strategy**: `"additive"`

**Action**: Add a new field with the narrower type alongside the old field.
- Keep the old field unchanged
- Add `{field_name}_v2` with the new type
- Mark old field as `"deprecated": true`

**Confidence**: `"medium"` — the naming convention (`_v2`) is a heuristic; the caller may want a different name.

### Rule 4: Enum Values Removed (BACKWARD breaking)

**Trigger**: `BreakingChange.kind == ENUM_VALUE_REMOVED`

**Strategy**: `"deprecate"`

**Action**: Re-add removed enum values to the new schema.
- Union old enum values with new enum values
- Add a `"description"` noting which values are deprecated

**Confidence**: `"high"` — always valid.

### Rule 5: Type Changed (any direction)

**Trigger**: `BreakingChange.kind == TYPE_CHANGED` (not covered by Rule 3)

**Strategy**: `"additive"`

**Action**: Keep old field, add new field with `_v2` suffix.
- Old field marked `"deprecated": true`
- New field uses the desired type

**Confidence**: `"medium"`

### Rule 6: Constraint Tightened (BACKWARD breaking)

**Trigger**: `BreakingChange.kind == CONSTRAINT_CHANGED` where new constraint is stricter (e.g., lower `maxLength`, higher `minimum`)

**Strategy**: `"keep_constraint"`

**Action**: Keep the old (looser) constraint in the suggested schema.

**Confidence**: `"high"` — consumers can still send the same data.

## Composition

When a proposed change has multiple breaking changes:

1. Start with the proposed (new) schema as a base
2. Apply each rule's modification in sequence
3. After each application, verify the result is still valid JSON Schema
4. If a modification conflicts with a previous one (overlapping paths), skip it and include it as a separate standalone suggestion
5. Return the composed schema as the primary suggestion, plus any standalone suggestions

## Non-Goals

- **LLM integration**: This spec is rule-based only. LLM enhancement is a separate future spec.
- **Field rename detection**: Detecting that `user_id` -> `customer_id` is a rename (not a remove + add) requires heuristics or ML. Out of scope.
- **Cross-schema migrations**: Suggestions that span multiple assets (e.g., "update the upstream source first") are out of scope.

## Testing

| Test case | Input | Expected suggestion |
|-----------|-------|-------------------|
| Single field removed | Remove `user_id` | Deprecate: re-add with `deprecated: true` |
| Required field added | Add required `email` | Make optional, add default `""` |
| Type narrowed (string -> integer) | Change `id` from string to int | Add `id_v2` as integer, deprecate `id` |
| Enum value removed | Remove `"pending"` from status | Re-add `"pending"` to enum |
| Multiple breaking changes | Remove field + add required | Composed schema with both fixes |
| Conflicting modifications | Two changes on same path | Primary suggestion + standalone fallback |
| No known rule | Structural schema reorganization | Empty suggestions list |
| Forward-breaking only | Add new optional field (forward mode) | Appropriate suggestion for forward compat |
| Constraint tightened | `maxLength` reduced 100 -> 50 | Keep `maxLength: 100` |
