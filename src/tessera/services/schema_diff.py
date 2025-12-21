"""Schema diffing and compatibility checking.

Implements JSON Schema diffing with compatibility modes borrowed from
Kafka Schema Registry (backward, forward, full, none).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tessera.models.enums import ChangeType, CompatibilityMode


class ChangeKind(StrEnum):
    """Types of schema changes."""

    PROPERTY_ADDED = "property_added"
    PROPERTY_REMOVED = "property_removed"
    PROPERTY_RENAMED = "property_renamed"  # Detected heuristically
    TYPE_CHANGED = "type_changed"
    TYPE_WIDENED = "type_widened"  # e.g., int -> number
    TYPE_NARROWED = "type_narrowed"  # e.g., number -> int
    REQUIRED_ADDED = "required_added"
    REQUIRED_REMOVED = "required_removed"
    ENUM_VALUES_ADDED = "enum_values_added"
    ENUM_VALUES_REMOVED = "enum_values_removed"
    CONSTRAINT_TIGHTENED = "constraint_tightened"  # e.g., maxLength decreased
    CONSTRAINT_RELAXED = "constraint_relaxed"  # e.g., maxLength increased
    DEFAULT_ADDED = "default_added"
    DEFAULT_REMOVED = "default_removed"
    DEFAULT_CHANGED = "default_changed"
    NULLABLE_ADDED = "nullable_added"
    NULLABLE_REMOVED = "nullable_removed"


# Which changes are breaking under each compatibility mode
BACKWARD_BREAKING = {
    ChangeKind.PROPERTY_REMOVED,
    ChangeKind.PROPERTY_RENAMED,
    ChangeKind.TYPE_CHANGED,
    ChangeKind.TYPE_NARROWED,
    ChangeKind.REQUIRED_ADDED,
    ChangeKind.ENUM_VALUES_REMOVED,
    ChangeKind.CONSTRAINT_TIGHTENED,
    ChangeKind.DEFAULT_REMOVED,
    ChangeKind.NULLABLE_REMOVED,
}

FORWARD_BREAKING = {
    ChangeKind.PROPERTY_ADDED,
    ChangeKind.PROPERTY_RENAMED,
    ChangeKind.TYPE_CHANGED,
    ChangeKind.TYPE_WIDENED,
    ChangeKind.REQUIRED_REMOVED,
    ChangeKind.ENUM_VALUES_ADDED,
    ChangeKind.CONSTRAINT_RELAXED,
    ChangeKind.DEFAULT_ADDED,
    ChangeKind.NULLABLE_ADDED,
}

# Full compatibility = intersection of backward and forward breaking
FULL_BREAKING = BACKWARD_BREAKING | FORWARD_BREAKING


@dataclass
class BreakingChange:
    """A single breaking change detected in a schema diff."""

    kind: ChangeKind
    path: str  # JSON path to the affected element (e.g., "properties.email")
    message: str
    old_value: Any = None
    new_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": str(self.kind),
            "path": self.path,
            "message": self.message,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


@dataclass
class SchemaDiffResult:
    """Result of comparing two schemas."""

    changes: list[BreakingChange] = field(default_factory=list)
    change_type: ChangeType = ChangeType.PATCH

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    def breaking_for_mode(self, mode: CompatibilityMode) -> list[BreakingChange]:
        """Return only changes that are breaking under the given mode."""
        if mode == CompatibilityMode.NONE:
            return []

        breaking_kinds = {
            CompatibilityMode.BACKWARD: BACKWARD_BREAKING,
            CompatibilityMode.FORWARD: FORWARD_BREAKING,
            CompatibilityMode.FULL: FULL_BREAKING,
        }[mode]

        return [c for c in self.changes if c.kind in breaking_kinds]

    def is_compatible(self, mode: CompatibilityMode) -> bool:
        """Check if the schema change is compatible under the given mode."""
        return len(self.breaking_for_mode(mode)) == 0


class SchemaDiff:
    """Compares two JSON schemas and identifies changes."""

    # Type hierarchy for widening/narrowing detection
    TYPE_HIERARCHY = {
        "null": 0,
        "boolean": 1,
        "integer": 2,
        "number": 3,  # number includes integer
        "string": 4,
        "array": 5,
        "object": 6,
    }

    # Types that can be widened to other types
    TYPE_WIDENING = {
        ("integer", "number"),  # int -> number is widening
    }

    def __init__(self, old_schema: dict[str, Any], new_schema: dict[str, Any]):
        self.old = old_schema
        self.new = new_schema
        self.changes: list[BreakingChange] = []

    def diff(self) -> SchemaDiffResult:
        """Perform the diff and return results."""
        self.changes = []
        self._diff_object(self.old, self.new, "")
        return SchemaDiffResult(
            changes=self.changes,
            change_type=self._classify_changes(),
        )

    def _classify_changes(self) -> ChangeType:
        """Classify the overall change type based on detected changes."""
        if not self.changes:
            return ChangeType.PATCH

        # Any breaking change under backward compatibility = MAJOR
        backward_breaking = any(c.kind in BACKWARD_BREAKING for c in self.changes)
        if backward_breaking:
            return ChangeType.MAJOR

        # Additions that don't break backward compatibility = MINOR
        additions = any(
            c.kind
            in {
                ChangeKind.PROPERTY_ADDED,
                ChangeKind.ENUM_VALUES_ADDED,
                ChangeKind.NULLABLE_ADDED,
                ChangeKind.DEFAULT_ADDED,
            }
            for c in self.changes
        )
        if additions:
            return ChangeType.MINOR

        return ChangeType.PATCH

    def _diff_object(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Diff two schema objects recursively."""
        # Compare properties
        old_props = old.get("properties", {})
        new_props = new.get("properties", {})
        self._diff_properties(old_props, new_props, f"{path}.properties" if path else "properties")

        # Compare required fields
        old_required = set(old.get("required", []))
        new_required = set(new.get("required", []))
        self._diff_required(old_required, new_required, path)

        # Compare type
        self._diff_type(old, new, path)

        # Compare constraints
        self._diff_constraints(old, new, path)

        # Compare enum values
        self._diff_enum(old, new, path)

        # Compare default
        self._diff_default(old, new, path)

        # Compare nullable (for schemas that use nullable keyword)
        self._diff_nullable(old, new, path)

        # Recurse into items for arrays
        if old.get("type") == "array" and new.get("type") == "array":
            old_items = old.get("items", {})
            new_items = new.get("items", {})
            if old_items or new_items:
                self._diff_object(old_items, new_items, f"{path}.items" if path else "items")

    def _diff_properties(
        self, old_props: dict[str, Any], new_props: dict[str, Any], path: str
    ) -> None:
        """Compare properties between schemas."""
        old_keys = set(old_props.keys())
        new_keys = set(new_props.keys())

        # Removed properties
        for key in old_keys - new_keys:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.PROPERTY_REMOVED,
                    path=f"{path}.{key}",
                    message=f"Property '{key}' was removed",
                    old_value=old_props[key],
                    new_value=None,
                )
            )

        # Added properties
        for key in new_keys - old_keys:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.PROPERTY_ADDED,
                    path=f"{path}.{key}",
                    message=f"Property '{key}' was added",
                    old_value=None,
                    new_value=new_props[key],
                )
            )

        # Modified properties (recurse)
        for key in old_keys & new_keys:
            self._diff_object(old_props[key], new_props[key], f"{path}.{key}")

    def _diff_required(self, old_req: set[str], new_req: set[str], path: str) -> None:
        """Compare required fields."""
        req_path = f"{path}.required" if path else "required"

        for field_name in new_req - old_req:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.REQUIRED_ADDED,
                    path=req_path,
                    message=f"Field '{field_name}' is now required",
                    old_value=list(old_req),
                    new_value=list(new_req),
                )
            )

        for field_name in old_req - new_req:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.REQUIRED_REMOVED,
                    path=req_path,
                    message=f"Field '{field_name}' is no longer required",
                    old_value=list(old_req),
                    new_value=list(new_req),
                )
            )

    def _diff_type(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Compare type definitions."""
        old_type = old.get("type")
        new_type = new.get("type")

        if old_type is None or new_type is None:
            return
        if old_type == new_type:
            return

        type_path = f"{path}.type" if path else "type"

        # Check for widening/narrowing
        if (old_type, new_type) in self.TYPE_WIDENING:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.TYPE_WIDENED,
                    path=type_path,
                    message=f"Type widened from '{old_type}' to '{new_type}'",
                    old_value=old_type,
                    new_value=new_type,
                )
            )
        elif (new_type, old_type) in self.TYPE_WIDENING:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.TYPE_NARROWED,
                    path=type_path,
                    message=f"Type narrowed from '{old_type}' to '{new_type}'",
                    old_value=old_type,
                    new_value=new_type,
                )
            )
        else:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.TYPE_CHANGED,
                    path=type_path,
                    message=f"Type changed from '{old_type}' to '{new_type}'",
                    old_value=old_type,
                    new_value=new_type,
                )
            )

    def _diff_constraints(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Compare constraints like minLength, maxLength, minimum, maximum, pattern."""
        # Constraints that when increased are "relaxed" (less restrictive)
        relaxing_increase = {"maxLength", "maxItems", "maximum", "exclusiveMaximum"}
        # Constraints that when decreased are "relaxed"
        relaxing_decrease = {"minLength", "minItems", "minimum", "exclusiveMinimum"}

        all_constraints = relaxing_increase | relaxing_decrease | {"pattern"}

        for constraint in all_constraints:
            old_val = old.get(constraint)
            new_val = new.get(constraint)

            if old_val == new_val:
                continue

            constraint_path = f"{path}.{constraint}" if path else constraint

            # Constraint removed = relaxed
            if old_val is not None and new_val is None:
                self.changes.append(
                    BreakingChange(
                        kind=ChangeKind.CONSTRAINT_RELAXED,
                        path=constraint_path,
                        message=f"Constraint '{constraint}' was removed",
                        old_value=old_val,
                        new_value=None,
                    )
                )
            # Constraint added = tightened
            elif old_val is None and new_val is not None:
                self.changes.append(
                    BreakingChange(
                        kind=ChangeKind.CONSTRAINT_TIGHTENED,
                        path=constraint_path,
                        message=f"Constraint '{constraint}' was added with value {new_val}",
                        old_value=None,
                        new_value=new_val,
                    )
                )
            # Constraint changed (both old_val and new_val are not None at this point)
            elif constraint in relaxing_increase and old_val is not None and new_val is not None:
                if new_val > old_val:
                    kind = ChangeKind.CONSTRAINT_RELAXED
                    msg = f"Constraint '{constraint}' relaxed from {old_val} to {new_val}"
                else:
                    kind = ChangeKind.CONSTRAINT_TIGHTENED
                    msg = f"Constraint '{constraint}' tightened from {old_val} to {new_val}"
                self.changes.append(
                    BreakingChange(
                        kind=kind,
                        path=constraint_path,
                        message=msg,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )
            elif constraint in relaxing_decrease and old_val is not None and new_val is not None:
                if new_val < old_val:
                    kind = ChangeKind.CONSTRAINT_RELAXED
                    msg = f"Constraint '{constraint}' relaxed from {old_val} to {new_val}"
                else:
                    kind = ChangeKind.CONSTRAINT_TIGHTENED
                    msg = f"Constraint '{constraint}' tightened from {old_val} to {new_val}"
                self.changes.append(
                    BreakingChange(
                        kind=kind,
                        path=constraint_path,
                        message=msg,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )
            elif constraint == "pattern":
                # Pattern changes are always considered tightening (conservative)
                self.changes.append(
                    BreakingChange(
                        kind=ChangeKind.CONSTRAINT_TIGHTENED,
                        path=constraint_path,
                        message=f"Pattern changed from '{old_val}' to '{new_val}'",
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

    def _diff_enum(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Compare enum values."""
        old_enum = set(old.get("enum", []))
        new_enum = set(new.get("enum", []))

        if not old_enum and not new_enum:
            return

        enum_path = f"{path}.enum" if path else "enum"

        added = new_enum - old_enum
        removed = old_enum - new_enum

        if added:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.ENUM_VALUES_ADDED,
                    path=enum_path,
                    message=f"Enum values added: {added}",
                    old_value=list(old_enum),
                    new_value=list(new_enum),
                )
            )

        if removed:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.ENUM_VALUES_REMOVED,
                    path=enum_path,
                    message=f"Enum values removed: {removed}",
                    old_value=list(old_enum),
                    new_value=list(new_enum),
                )
            )

    def _diff_default(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Compare default values."""
        old_default = old.get("default")
        new_default = new.get("default")
        has_old = "default" in old
        has_new = "default" in new

        if not has_old and not has_new:
            return

        default_path = f"{path}.default" if path else "default"

        if has_old and not has_new:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.DEFAULT_REMOVED,
                    path=default_path,
                    message=f"Default value removed (was {old_default})",
                    old_value=old_default,
                    new_value=None,
                )
            )
        elif not has_old and has_new:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.DEFAULT_ADDED,
                    path=default_path,
                    message=f"Default value added: {new_default}",
                    old_value=None,
                    new_value=new_default,
                )
            )
        elif old_default != new_default:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.DEFAULT_CHANGED,
                    path=default_path,
                    message=f"Default value changed from {old_default} to {new_default}",
                    old_value=old_default,
                    new_value=new_default,
                )
            )

    def _diff_nullable(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        """Compare nullable flag (common in OpenAPI/JSON Schema extensions)."""
        old_nullable = old.get("nullable", False)
        new_nullable = new.get("nullable", False)

        if old_nullable == new_nullable:
            return

        nullable_path = f"{path}.nullable" if path else "nullable"

        if new_nullable and not old_nullable:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.NULLABLE_ADDED,
                    path=nullable_path,
                    message="Field is now nullable",
                    old_value=False,
                    new_value=True,
                )
            )
        else:
            self.changes.append(
                BreakingChange(
                    kind=ChangeKind.NULLABLE_REMOVED,
                    path=nullable_path,
                    message="Field is no longer nullable",
                    old_value=True,
                    new_value=False,
                )
            )


def diff_schemas(old_schema: dict[str, Any], new_schema: dict[str, Any]) -> SchemaDiffResult:
    """Convenience function to diff two schemas."""
    differ = SchemaDiff(old_schema, new_schema)
    return differ.diff()


def check_compatibility(
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    mode: CompatibilityMode,
) -> tuple[bool, list[BreakingChange]]:
    """Check if a schema change is compatible under the given mode.

    Returns:
        Tuple of (is_compatible, list of breaking changes)
    """
    result = diff_schemas(old_schema, new_schema)
    breaking = result.breaking_for_mode(mode)
    return len(breaking) == 0, breaking
