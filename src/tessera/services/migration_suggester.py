"""Rule-based migration suggester for breaking schema changes.

When a schema change is breaking, this service generates non-breaking
alternatives using deterministic rules. Each rule targets a specific
breaking change pattern and produces a modified schema that avoids the break.

Rules:
    1. PROPERTY_REMOVED → deprecate (re-add with deprecated: true)
    2. REQUIRED_FIELD_ADDED → default (make optional, add type-appropriate default)
    3. TYPE_CHANGED (narrowed) → additive (add {field}_v2, deprecate old)
    4. ENUM_VALUES_REMOVED → deprecate (re-add removed values, note deprecated)
    5. TYPE_CHANGED (other) → additive (keep old, add {field}_v2)
    6. CONSTRAINT_TIGHTENED → keep_constraint (keep the old looser constraint)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from tessera.models.enums import CompatibilityMode
from tessera.services.schema_diff import BreakingChange, ChangeKind


@dataclass(frozen=True)
class MigrationSuggestion:
    """A single migration suggestion for avoiding a breaking change."""

    strategy: str
    description: str
    confidence: str
    suggested_schema: dict[str, Any]
    changes_made: list[str]


# Default values by JSON Schema type
_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "number": 0.0,
    "boolean": False,
    "array": [],
    "object": {},
    "null": None,
}


def _get_property_at_path(schema: dict[str, Any], path: str) -> tuple[dict[str, Any] | None, str]:
    """Navigate to the parent container and return (parent_props, field_name).

    Handles paths like 'properties.email' or 'properties.address.properties.city'.
    Returns (None, '') if the path is not navigable.
    """
    parts = path.split(".")
    current = schema

    # Walk to the parent 'properties' dict
    for i, part in enumerate(parts[:-1]):
        if part == "properties" and "properties" in current:
            current = current["properties"]
        elif part in current:
            current = current[part]
            # If this is a nested object, drill into it
            if isinstance(current, dict) and "properties" in current and i + 1 < len(parts) - 1:
                continue
        else:
            return None, ""

    field_name = parts[-1]
    # If current is a 'properties' dict (we're inside it), return it
    if isinstance(current, dict):
        return current, field_name
    return None, ""


def _get_type_for_field(schema: dict[str, Any], path: str) -> str | None:
    """Get the JSON Schema type of a field at the given path."""
    props, field_name = _get_property_at_path(schema, path)
    if props and field_name in props:
        field_def = props[field_name]
        if isinstance(field_def, dict):
            return field_def.get("type")
    return None


def _apply_property_removed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Rule 1: Re-add removed property with deprecated: true."""
    props, field_name = _get_property_at_path(old_schema, change.path)
    if not props or field_name not in props:
        return None

    result = copy.deepcopy(schema)
    target_props, _ = _get_property_at_path(result, change.path)
    if target_props is None:
        # Ensure properties dict exists
        if "properties" not in result:
            result["properties"] = {}
        target_props = result["properties"]

    # Re-add the field with deprecated flag
    old_field_def = copy.deepcopy(props[field_name])
    if isinstance(old_field_def, dict):
        old_field_def["deprecated"] = True
        desc = old_field_def.get("description", "")
        if desc:
            old_field_def["description"] = f"[DEPRECATED] {desc}"
        else:
            old_field_def["description"] = (
                "[DEPRECATED] This field will be removed in a future version."
            )
    target_props[field_name] = old_field_def

    return MigrationSuggestion(
        strategy="deprecate",
        description=f"Re-added removed property '{field_name}' with deprecated: true",
        confidence="high",
        suggested_schema=result,
        changes_made=[f"Re-added '{change.path}' with deprecated: true"],
    )


def _apply_required_field_added(
    schema: dict[str, Any],
    change: BreakingChange,
) -> MigrationSuggestion | None:
    """Rule 2: Make new required field optional with type-appropriate default."""
    result = copy.deepcopy(schema)

    # Extract field name from path (e.g., 'required.email' → 'email')
    parts = change.path.split(".")
    field_name = parts[-1] if parts else ""
    if not field_name:
        return None

    # Remove from required list
    if "required" in result and field_name in result["required"]:
        result["required"] = [r for r in result["required"] if r != field_name]
        if not result["required"]:
            del result["required"]

    # Add a default value based on the field's type
    field_type = _get_type_for_field(result, f"properties.{field_name}")
    default_value = _TYPE_DEFAULTS.get(field_type or "string", "")

    if "properties" in result and field_name in result["properties"]:
        field_def = result["properties"][field_name]
        if isinstance(field_def, dict):
            field_def["default"] = default_value

    confidence = "high" if field_type in _TYPE_DEFAULTS else "medium"

    return MigrationSuggestion(
        strategy="default",
        description=f"Made '{field_name}' optional with default value {default_value!r}",
        confidence=confidence,
        suggested_schema=result,
        changes_made=[
            f"Removed '{field_name}' from required list",
            f"Added default value {default_value!r} to '{field_name}'",
        ],
    )


def _apply_type_narrowed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Rule 3: Add {field}_v2 with new type, deprecate old field."""
    props, field_name = _get_property_at_path(schema, change.path)
    if not props or field_name not in props:
        return None

    old_props, _ = _get_property_at_path(old_schema, change.path)
    if not old_props or field_name not in old_props:
        return None

    result = copy.deepcopy(schema)
    target_props, _ = _get_property_at_path(result, change.path)
    if target_props is None:
        return None

    # Keep old field definition (restore original type)
    old_field_def = copy.deepcopy(old_props[field_name])
    if isinstance(old_field_def, dict):
        old_field_def["deprecated"] = True
        old_field_def["description"] = (
            f"[DEPRECATED] Use '{field_name}_v2' instead. {old_field_def.get('description', '')}"
        ).strip()

    # New field gets the narrowed type under _v2 name
    new_field_def = copy.deepcopy(props[field_name])
    if isinstance(new_field_def, dict):
        new_field_def["description"] = (
            f"Replacement for deprecated '{field_name}'. {new_field_def.get('description', '')}"
        ).strip()

    target_props[field_name] = old_field_def
    target_props[f"{field_name}_v2"] = new_field_def

    # Remove field_name from required and don't add _v2 to required
    if "required" in result and field_name in result["required"]:
        result["required"] = [r for r in result["required"] if r != field_name]
        if not result["required"]:
            del result["required"]

    return MigrationSuggestion(
        strategy="additive",
        description=(f"Added '{field_name}_v2' with new type, deprecated original '{field_name}'"),
        confidence="medium",
        suggested_schema=result,
        changes_made=[
            f"Restored original type for '{change.path}'",
            f"Added '{field_name}_v2' with narrowed type",
            f"Marked '{field_name}' as deprecated",
        ],
    )


def _apply_enum_values_removed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Rule 4: Re-add removed enum values, note deprecated in description."""
    props, field_name = _get_property_at_path(schema, change.path)
    if not props or field_name not in props:
        return None

    old_props, _ = _get_property_at_path(old_schema, change.path)
    if not old_props or field_name not in old_props:
        return None

    result = copy.deepcopy(schema)
    target_props, _ = _get_property_at_path(result, change.path)
    if target_props is None:
        return None

    field_def = target_props[field_name]
    old_field_def = old_props[field_name]

    if not isinstance(field_def, dict) or not isinstance(old_field_def, dict):
        return None

    old_enum = set(old_field_def.get("enum", []))
    new_enum = set(field_def.get("enum", []))
    removed_values = old_enum - new_enum

    if not removed_values:
        return None

    # Re-add removed values (preserve original types — JSON Schema enums can be any type)
    combined_enum = list(field_def.get("enum", [])) + sorted(
        removed_values, key=lambda v: (type(v).__name__, str(v))
    )
    field_def["enum"] = combined_enum

    deprecated_str = ", ".join(
        repr(v) for v in sorted(removed_values, key=lambda v: (type(v).__name__, str(v)))
    )
    existing_desc = field_def.get("description", "")
    field_def["description"] = (f"{existing_desc} [Deprecated values: {deprecated_str}]").strip()

    return MigrationSuggestion(
        strategy="deprecate",
        description=f"Re-added removed enum values ({deprecated_str}) as deprecated",
        confidence="high",
        suggested_schema=result,
        changes_made=[
            f"Re-added enum values {deprecated_str} to '{change.path}'",
            "Noted deprecated values in field description",
        ],
    )


def _apply_type_changed(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Rule 5: Keep old field, add {field}_v2 with new type."""
    # Same as type narrowed but for general type changes
    return _apply_type_narrowed(schema, change, old_schema)


def _apply_constraint_tightened(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Rule 6: Keep the old (looser) constraint."""
    props, field_name = _get_property_at_path(schema, change.path)
    old_props, old_field_name = _get_property_at_path(old_schema, change.path)

    if not props or not old_props:
        return None

    result = copy.deepcopy(schema)
    target_props, target_field = _get_property_at_path(result, change.path)
    if target_props is None:
        return None

    # For constraint changes, the path may point to the constraint itself
    # e.g., 'properties.name.maxLength'
    # We need to figure out what changed and restore the old value
    if field_name in props and old_field_name in old_props:
        # The path points to a field - look for changed constraints
        new_field = props[field_name]
        old_field = old_props[old_field_name]
        if isinstance(new_field, dict) and isinstance(old_field, dict):
            constraint_keys = [
                "maxLength",
                "minLength",
                "maximum",
                "minimum",
                "exclusiveMaximum",
                "exclusiveMinimum",
                "maxItems",
                "minItems",
                "pattern",
                "multipleOf",
                "maxProperties",
                "minProperties",
            ]
            changes_made = []
            for key in constraint_keys:
                if key in old_field and key in new_field and old_field[key] != new_field[key]:
                    target_props[target_field][key] = old_field[key]
                    changes_made.append(
                        f"Restored '{key}' from {new_field[key]} to {old_field[key]}"
                    )
                elif key not in old_field and key in new_field:
                    # New constraint added (tightening)
                    del target_props[target_field][key]
                    changes_made.append(f"Removed newly added constraint '{key}'")

            if changes_made:
                return MigrationSuggestion(
                    strategy="keep_constraint",
                    description=f"Kept original (looser) constraints for '{field_name}'",
                    confidence="high",
                    suggested_schema=result,
                    changes_made=changes_made,
                )

    # Fallback: try to use old_value/new_value from the change itself
    if change.old_value is not None:
        return MigrationSuggestion(
            strategy="keep_constraint",
            description=f"Kept original constraint value at '{change.path}'",
            confidence="high",
            suggested_schema=result,
            changes_made=[f"Restored constraint at '{change.path}' to original value"],
        )

    return None


# Maps ChangeKind to (handler_function, applies_to_narrowed_only)
_RULE_DISPATCH: dict[
    ChangeKind,
    str,
] = {
    ChangeKind.PROPERTY_REMOVED: "property_removed",
    ChangeKind.REQUIRED_ADDED: "required_added",
    ChangeKind.TYPE_NARROWED: "type_narrowed",
    ChangeKind.ENUM_VALUES_REMOVED: "enum_removed",
    ChangeKind.TYPE_CHANGED: "type_changed",
    ChangeKind.CONSTRAINT_TIGHTENED: "constraint_tightened",
}


def _apply_rule(
    schema: dict[str, Any],
    change: BreakingChange,
    old_schema: dict[str, Any],
) -> MigrationSuggestion | None:
    """Apply the appropriate migration rule for a breaking change."""
    rule = _RULE_DISPATCH.get(change.kind)
    if rule is None:
        return None

    if rule == "property_removed":
        return _apply_property_removed(schema, change, old_schema)
    elif rule == "required_added":
        return _apply_required_field_added(schema, change)
    elif rule == "type_narrowed":
        return _apply_type_narrowed(schema, change, old_schema)
    elif rule == "enum_removed":
        return _apply_enum_values_removed(schema, change, old_schema)
    elif rule == "type_changed":
        return _apply_type_changed(schema, change, old_schema)
    elif rule == "constraint_tightened":
        return _apply_constraint_tightened(schema, change, old_schema)
    return None


def _paths_conflict(path_a: str, path_b: str) -> bool:
    """Check if two change paths conflict (overlap on the same field)."""
    # Two paths conflict if one is a prefix of the other
    return path_a.startswith(path_b) or path_b.startswith(path_a)


def suggest_migrations(
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    breaking_changes: list[BreakingChange],
    compatibility_mode: CompatibilityMode,
) -> list[MigrationSuggestion]:
    """Generate migration suggestions for breaking schema changes.

    For multiple breaking changes, attempts to compose modifications into a
    single schema. If modifications conflict (overlapping paths), the
    conflicting change produces a standalone suggestion instead.

    Args:
        old_schema: The current published schema.
        new_schema: The proposed schema with breaking changes.
        breaking_changes: List of breaking changes detected by schema diff.
        compatibility_mode: The compatibility mode in effect.

    Returns:
        List of migration suggestions. The first suggestion (if any) is the
        composed result; subsequent entries are standalone fallbacks for
        changes that couldn't be composed.
    """
    if not breaking_changes:
        return []

    if compatibility_mode == CompatibilityMode.NONE:
        return []

    # Single change: straightforward
    if len(breaking_changes) == 1:
        suggestion = _apply_rule(new_schema, breaking_changes[0], old_schema)
        return [suggestion] if suggestion else []

    # Multiple changes: try to compose
    composed_schema = copy.deepcopy(new_schema)
    composed_changes_made: list[str] = []
    composed_descriptions: list[str] = []
    standalone_suggestions: list[MigrationSuggestion] = []
    applied_paths: list[str] = []
    lowest_confidence = "high"

    for change in breaking_changes:
        # Check for path conflicts with already-applied changes
        conflicts_with_applied = any(
            _paths_conflict(change.path, applied) for applied in applied_paths
        )

        if conflicts_with_applied:
            # Generate standalone suggestion for this change
            standalone = _apply_rule(new_schema, change, old_schema)
            if standalone:
                standalone_suggestions.append(standalone)
            continue

        # Try to apply this rule to the composed schema
        suggestion = _apply_rule(composed_schema, change, old_schema)
        if suggestion:
            composed_schema = suggestion.suggested_schema
            composed_changes_made.extend(suggestion.changes_made)
            composed_descriptions.append(suggestion.description)
            applied_paths.append(change.path)
            if suggestion.confidence == "low" or (
                suggestion.confidence == "medium" and lowest_confidence == "high"
            ):
                lowest_confidence = suggestion.confidence
        else:
            # No rule matched — skip (no suggestion for unknown patterns)
            pass

    results: list[MigrationSuggestion] = []

    if composed_changes_made:
        results.append(
            MigrationSuggestion(
                strategy="composed",
                description="; ".join(composed_descriptions),
                confidence=lowest_confidence,
                suggested_schema=composed_schema,
                changes_made=composed_changes_made,
            )
        )

    results.extend(standalone_suggestions)
    return results
