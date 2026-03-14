"""Rule-based migration suggester for breaking schema changes.

Given a set of breaking changes detected by schema_diff, produces non-breaking
migration alternatives. Each rule handles one ChangeKind and modifies the
proposed schema to avoid the break. When multiple breaking changes exist,
the service composes them into a single suggested schema—falling back to
standalone per-change suggestions when modifications conflict.

Ref: docs/adrs/specs/003-migration-suggester.md
"""

import copy
from typing import Any

from pydantic import BaseModel, Field

from tessera.models.enums import CompatibilityMode
from tessera.services.schema_diff import BreakingChange, ChangeKind


class MigrationSuggestion(BaseModel):
    """A single migration suggestion that avoids a breaking change."""

    strategy: str = Field(
        ..., description="Migration strategy: additive, deprecate, default, keep_constraint"
    )
    description: str = Field(..., description="Human-readable explanation of the suggestion")
    confidence: str = Field(..., description="Confidence level: high, medium, low")
    suggested_schema: dict[str, Any] = Field(
        ..., description="Modified schema that avoids the breaking change"
    )
    changes_made: list[str] = Field(
        default_factory=list, description="List of modifications applied to the schema"
    )


# Type -> sensible default value mapping for Rule 2
_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _get_property_at_path(schema: dict[str, Any], path: str) -> tuple[dict[str, Any] | None, str]:
    """Navigate to the parent container and return (container, field_name).

    Paths from BreakingChange look like "properties.email" or
    "properties.address.properties.zip". We walk through the schema
    following each segment.
    """
    segments = path.split(".")
    current = schema
    for segment in segments[:-1]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None, segments[-1]
    return current, segments[-1]


def _apply_rule_property_removed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    """Rule 1: Re-add removed property with deprecated: true."""
    container, field_name = _get_property_at_path(old_schema, change.path)
    if container is None or field_name not in container:
        return None

    old_prop_def = copy.deepcopy(container[field_name])
    old_prop_def["deprecated"] = True

    existing_desc = old_prop_def.get("description", "")
    if existing_desc:
        old_prop_def["description"] = f"Deprecated: {existing_desc}"
    else:
        old_prop_def["description"] = "Deprecated: scheduled for removal in a future version"

    # Insert the property back into the new schema at the same path
    new_container, _ = _get_property_at_path(schema, change.path)
    if new_container is None:
        return None

    new_container[field_name] = old_prop_def

    # If the field was required in the old schema, keep it required
    parent_path_segments = change.path.split(".")
    # Walk up to find the object that has "required"
    obj = schema
    for seg in parent_path_segments[:-2]:  # skip "properties" and field_name
        if isinstance(obj, dict) and seg in obj:
            obj = obj[seg]

    if isinstance(obj, dict) and "required" in obj:
        old_obj = old_schema
        for seg in parent_path_segments[:-2]:
            if isinstance(old_obj, dict) and seg in old_obj:
                old_obj = old_obj[seg]
        if isinstance(old_obj, dict) and field_name in old_obj.get("required", []):
            if field_name not in obj["required"]:
                obj["required"].append(field_name)

    return schema, f"Re-added '{field_name}' with deprecated: true"


def _apply_rule_required_added(
    schema: dict[str, Any],
    change: BreakingChange,
) -> tuple[dict[str, Any], str, str] | None:
    """Rule 2: Make new required field optional, add default if possible.

    Returns (schema, change_description, confidence).
    """
    # The path for REQUIRED_ADDED is like "required.email" — the field name
    # is the last segment
    segments = change.path.split(".")
    field_name = segments[-1]

    # Find the "required" array in the schema
    # For top-level: required is at schema["required"]
    # For nested: walk to the parent object
    obj = schema
    for seg in segments[:-2]:  # everything before "required.field_name"
        if isinstance(obj, dict) and seg in obj:
            obj = obj[seg]

    if not isinstance(obj, dict) or "required" not in obj:
        return None

    required_list: list[str] = obj["required"]
    if field_name in required_list:
        required_list.remove(field_name)
        if not required_list:
            del obj["required"]

    # Try to add a default based on field type
    confidence = "medium"
    prop_def = obj.get("properties", {}).get(field_name)
    if isinstance(prop_def, dict):
        field_type = prop_def.get("type")
        if isinstance(field_type, str) and field_type in _TYPE_DEFAULTS:
            prop_def["default"] = _TYPE_DEFAULTS[field_type]
            confidence = "high"

    return schema, f"Made '{field_name}' optional with default", confidence


def _apply_rule_type_narrowed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    """Rule 3: Add {field}_v2 with new type, keep old field."""
    container, field_name = _get_property_at_path(schema, change.path)
    if container is None or field_name not in container:
        return None

    old_container, _ = _get_property_at_path(old_schema, change.path)
    if old_container is None or field_name not in old_container:
        return None

    # Restore the old property definition and mark deprecated
    new_type_def = copy.deepcopy(container[field_name])
    old_type_def = copy.deepcopy(old_container[field_name])
    old_type_def["deprecated"] = True

    container[field_name] = old_type_def
    container[f"{field_name}_v2"] = new_type_def

    return schema, f"Kept '{field_name}' with original type, added '{field_name}_v2' with new type"


def _apply_rule_enum_removed(
    schema: dict[str, Any],
    change: BreakingChange,
) -> tuple[dict[str, Any], str] | None:
    """Rule 4: Re-add removed enum values."""
    container, field_name = _get_property_at_path(schema, change.path)
    if container is None or field_name not in container:
        return None

    prop_def = container[field_name]
    if not isinstance(prop_def, dict) or "enum" not in prop_def:
        return None

    current_enum = prop_def["enum"]
    old_values = change.old_value
    if not isinstance(old_values, list):
        return None

    # Union old and new values, preserving order (new values first, then re-added)
    removed = [v for v in old_values if v not in current_enum]
    if not removed:
        return None

    prop_def["enum"] = current_enum + removed

    existing_desc = prop_def.get("description", "")
    deprecated_note = f"Deprecated values: {removed}"
    if existing_desc:
        prop_def["description"] = f"{existing_desc}. {deprecated_note}"
    else:
        prop_def["description"] = deprecated_note

    return schema, f"Re-added deprecated enum values {removed} to '{field_name}'"


def _apply_rule_type_changed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    """Rule 5: Add {field}_v2 with new type, keep old field (general type change)."""
    # Same mechanism as rule 3 — keep old, add _v2 with new
    return _apply_rule_type_narrowed(schema, change, old_schema)


def _apply_rule_constraint_tightened(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    """Rule 6: Keep the old (looser) constraint."""
    container, field_name = _get_property_at_path(schema, change.path)
    if container is None or field_name not in container:
        return None

    old_container, _ = _get_property_at_path(old_schema, change.path)
    if old_container is None or field_name not in old_container:
        return None

    new_prop = container[field_name]
    old_prop = old_container[field_name]

    # Constraint keywords in JSON Schema
    constraint_keys = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "pattern",
        "multipleOf",
    }

    changes_applied: list[str] = []
    for key in constraint_keys:
        if key in old_prop and (key not in new_prop or old_prop[key] != new_prop[key]):
            new_prop[key] = old_prop[key]
            changes_applied.append(f"restored {key}={old_prop[key]}")
        elif key in new_prop and key not in old_prop:
            # New constraint that didn't exist before — remove it
            del new_prop[key]
            changes_applied.append(f"removed new {key}")

    if not changes_applied:
        return None

    return schema, f"Kept original constraints on '{field_name}': {', '.join(changes_applied)}"


def _paths_overlap(path_a: str, path_b: str) -> bool:
    """Check if two JSON paths target the same or overlapping schema locations."""
    return path_a == path_b or path_a.startswith(path_b + ".") or path_b.startswith(path_a + ".")


def suggest_migrations(
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    breaking_changes: list[BreakingChange],
    compatibility_mode: CompatibilityMode,
) -> list[MigrationSuggestion]:
    """Generate non-breaking migration alternatives for breaking schema changes.

    Attempts to compose all rule modifications into a single suggested schema.
    When modifications conflict (overlapping paths), conflicting changes become
    standalone suggestions.

    Args:
        old_schema: The current (existing) schema.
        new_schema: The proposed schema that has breaking changes.
        breaking_changes: List of breaking changes detected by schema_diff.
        compatibility_mode: The compatibility mode in effect.

    Returns:
        List of MigrationSuggestion, possibly empty if no rules match.
        The first suggestion (if any) is the composed result; remaining
        entries are standalone fallbacks for conflicting changes.
    """
    if compatibility_mode == CompatibilityMode.NONE:
        return []

    if not breaking_changes:
        return []

    # Track which changes we can compose vs. which conflict
    composed_schema = copy.deepcopy(new_schema)
    composed_changes: list[str] = []
    composed_kinds: list[ChangeKind] = []
    composed_paths: list[str] = []
    standalone: list[MigrationSuggestion] = []
    lowest_confidence = "high"

    for change in breaking_changes:
        # Check for path conflicts with already-composed changes
        has_conflict = any(_paths_overlap(change.path, p) for p in composed_paths)

        if has_conflict:
            # Apply this rule independently as a standalone suggestion
            result = _apply_single_rule(copy.deepcopy(new_schema), change, old_schema)
            if result is not None:
                standalone.append(result)
            continue

        # Try to apply the rule to the composed schema
        result_tuple = _apply_rule(composed_schema, change, old_schema)
        if result_tuple is None:
            continue

        schema_out, desc, confidence = result_tuple
        composed_schema = schema_out
        composed_changes.append(desc)
        composed_kinds.append(change.kind)
        composed_paths.append(change.path)

        if _confidence_rank(confidence) < _confidence_rank(lowest_confidence):
            lowest_confidence = confidence

    suggestions: list[MigrationSuggestion] = []

    if composed_changes:
        suggestions.append(
            MigrationSuggestion(
                strategy=_pick_composed_strategy_from_kinds(composed_kinds),
                description="Composed migration: " + "; ".join(composed_changes),
                confidence=lowest_confidence,
                suggested_schema=composed_schema,
                changes_made=composed_changes,
            )
        )

    suggestions.extend(standalone)
    return suggestions


def _apply_rule(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> tuple[dict[str, Any], str, str] | None:
    """Apply the appropriate rule for a breaking change.

    Returns (modified_schema, description, confidence) or None.
    """
    if change.kind == ChangeKind.PROPERTY_REMOVED:
        result = _apply_rule_property_removed(schema, change, old_schema)
        if result is not None:
            return result[0], result[1], "high"

    elif change.kind == ChangeKind.REQUIRED_ADDED:
        return _apply_rule_required_added(schema, change)

    elif change.kind == ChangeKind.TYPE_NARROWED:
        result = _apply_rule_type_narrowed(schema, change, old_schema)
        if result is not None:
            return result[0], result[1], "medium"

    elif change.kind == ChangeKind.ENUM_VALUES_REMOVED:
        result = _apply_rule_enum_removed(schema, change)
        if result is not None:
            return result[0], result[1], "high"

    elif change.kind == ChangeKind.TYPE_CHANGED:
        result = _apply_rule_type_changed(schema, change, old_schema)
        if result is not None:
            return result[0], result[1], "medium"

    elif change.kind == ChangeKind.CONSTRAINT_TIGHTENED:
        result = _apply_rule_constraint_tightened(schema, change, old_schema)
        if result is not None:
            return result[0], result[1], "high"

    return None


def _apply_single_rule(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Apply a single rule and wrap the result as a standalone MigrationSuggestion."""
    result = _apply_rule(schema, change, old_schema)
    if result is None:
        return None

    schema_out, desc, confidence = result
    strategy_map = {
        ChangeKind.PROPERTY_REMOVED: "deprecate",
        ChangeKind.REQUIRED_ADDED: "default",
        ChangeKind.TYPE_NARROWED: "additive",
        ChangeKind.ENUM_VALUES_REMOVED: "deprecate",
        ChangeKind.TYPE_CHANGED: "additive",
        ChangeKind.CONSTRAINT_TIGHTENED: "keep_constraint",
    }
    return MigrationSuggestion(
        strategy=strategy_map.get(change.kind, "unknown"),
        description=desc,
        confidence=confidence,
        suggested_schema=schema_out,
        changes_made=[desc],
    )


def _confidence_rank(confidence: str) -> int:
    """Rank confidence levels for comparison (higher = more confident)."""
    return {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)


def _pick_composed_strategy_from_kinds(kinds: list[ChangeKind]) -> str:
    """Pick a strategy name for a composed suggestion based on the actually-applied rules."""
    strategy_map = {
        ChangeKind.PROPERTY_REMOVED: "deprecate",
        ChangeKind.REQUIRED_ADDED: "default",
        ChangeKind.TYPE_NARROWED: "additive",
        ChangeKind.ENUM_VALUES_REMOVED: "deprecate",
        ChangeKind.TYPE_CHANGED: "additive",
        ChangeKind.CONSTRAINT_TIGHTENED: "keep_constraint",
    }
    strategies = [strategy_map[k] for k in kinds if k in strategy_map]
    if not strategies:
        return "mixed"
    if len(set(strategies)) == 1:
        return strategies[0]
    return "mixed"
