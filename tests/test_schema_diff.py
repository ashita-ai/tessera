"""Tests for schema diffing service."""

import pytest

from tessera.models.enums import ChangeType, CompatibilityMode
from tessera.services.schema_diff import (
    ChangeKind,
    SchemaDiff,
    check_compatibility,
    diff_schemas,
)


class TestPropertyChanges:
    """Test property additions and removals."""

    def test_no_changes(self):
        """Identical schemas should produce no changes."""
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        result = diff_schemas(schema, schema)
        assert not result.has_changes
        assert result.change_type == ChangeType.PATCH

    def test_property_added(self):
        """Adding a property should be detected."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
        }
        result = diff_schemas(old, new)
        assert result.has_changes
        assert any(c.kind == ChangeKind.PROPERTY_ADDED for c in result.changes)
        assert result.change_type == ChangeType.MINOR

    def test_property_removed(self):
        """Removing a property should be detected."""
        old = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
        }
        new = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = diff_schemas(old, new)
        assert result.has_changes
        assert any(c.kind == ChangeKind.PROPERTY_REMOVED for c in result.changes)
        assert result.change_type == ChangeType.MAJOR

    def test_nested_property_added(self):
        """Adding a nested property should be detected."""
        old = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {"street": {"type": "string"}},
                }
            },
        }
        new = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"},
                    },
                }
            },
        }
        result = diff_schemas(old, new)
        assert any(
            c.kind == ChangeKind.PROPERTY_ADDED and "city" in c.path
            for c in result.changes
        )


class TestRequiredChanges:
    """Test required field changes."""

    def test_required_added(self):
        """Making a field required should be detected."""
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id"],
        }
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id", "name"],
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.REQUIRED_ADDED for c in result.changes)
        assert result.change_type == ChangeType.MAJOR

    def test_required_removed(self):
        """Making a field optional should be detected."""
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id", "name"],
        }
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id"],
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.REQUIRED_REMOVED for c in result.changes)


class TestTypeChanges:
    """Test type changes."""

    def test_type_changed(self):
        """Changing a type should be detected."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.TYPE_CHANGED for c in result.changes)
        assert result.change_type == ChangeType.MAJOR

    def test_type_widened(self):
        """Widening a type (int -> number) should be detected."""
        old = {"type": "object", "properties": {"value": {"type": "integer"}}}
        new = {"type": "object", "properties": {"value": {"type": "number"}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.TYPE_WIDENED for c in result.changes)

    def test_type_narrowed(self):
        """Narrowing a type (number -> int) should be detected."""
        old = {"type": "object", "properties": {"value": {"type": "number"}}}
        new = {"type": "object", "properties": {"value": {"type": "integer"}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.TYPE_NARROWED for c in result.changes)
        assert result.change_type == ChangeType.MAJOR


class TestEnumChanges:
    """Test enum value changes."""

    def test_enum_values_added(self):
        """Adding enum values should be detected."""
        old = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["active", "inactive"]}},
        }
        new = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["active", "inactive", "pending"]}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.ENUM_VALUES_ADDED for c in result.changes)
        assert result.change_type == ChangeType.MINOR

    def test_enum_values_removed(self):
        """Removing enum values should be detected."""
        old = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["active", "inactive", "pending"]}},
        }
        new = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["active", "inactive"]}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.ENUM_VALUES_REMOVED for c in result.changes)
        assert result.change_type == ChangeType.MAJOR


class TestConstraintChanges:
    """Test constraint changes."""

    def test_max_length_decreased(self):
        """Decreasing maxLength should be a tightening."""
        old = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 100}}}
        new = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 50}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_TIGHTENED for c in result.changes)

    def test_max_length_increased(self):
        """Increasing maxLength should be a relaxation."""
        old = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 50}}}
        new = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 100}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_RELAXED for c in result.changes)

    def test_min_length_added(self):
        """Adding minLength constraint should be tightening."""
        old = {"type": "object", "properties": {"name": {"type": "string"}}}
        new = {"type": "object", "properties": {"name": {"type": "string", "minLength": 1}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_TIGHTENED for c in result.changes)

    def test_constraint_removed(self):
        """Removing a constraint should be relaxation."""
        old = {"type": "object", "properties": {"name": {"type": "string", "maxLength": 100}}}
        new = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_RELAXED for c in result.changes)


class TestDefaultChanges:
    """Test default value changes."""

    def test_default_added(self):
        """Adding a default should be detected."""
        old = {"type": "object", "properties": {"active": {"type": "boolean"}}}
        new = {"type": "object", "properties": {"active": {"type": "boolean", "default": True}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.DEFAULT_ADDED for c in result.changes)

    def test_default_removed(self):
        """Removing a default should be detected."""
        old = {"type": "object", "properties": {"active": {"type": "boolean", "default": True}}}
        new = {"type": "object", "properties": {"active": {"type": "boolean"}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.DEFAULT_REMOVED for c in result.changes)

    def test_default_changed(self):
        """Changing a default should be detected."""
        old = {"type": "object", "properties": {"active": {"type": "boolean", "default": True}}}
        new = {"type": "object", "properties": {"active": {"type": "boolean", "default": False}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.DEFAULT_CHANGED for c in result.changes)


class TestNullableChanges:
    """Test nullable changes."""

    def test_nullable_added(self):
        """Making a field nullable should be detected."""
        old = {"type": "object", "properties": {"name": {"type": "string"}}}
        new = {"type": "object", "properties": {"name": {"type": "string", "nullable": True}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.NULLABLE_ADDED for c in result.changes)

    def test_nullable_removed(self):
        """Removing nullable should be detected."""
        old = {"type": "object", "properties": {"name": {"type": "string", "nullable": True}}}
        new = {"type": "object", "properties": {"name": {"type": "string", "nullable": False}}}
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.NULLABLE_REMOVED for c in result.changes)


class TestCompatibilityModes:
    """Test compatibility checking under different modes."""

    def test_backward_compatible_addition(self):
        """Adding optional field should be backward compatible."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id"],
        }
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.BACKWARD)
        assert is_compatible
        assert len(breaking) == 0

    def test_backward_incompatible_removal(self):
        """Removing a field should break backward compatibility."""
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        new = {"type": "object", "properties": {"id": {"type": "integer"}}}
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.BACKWARD)
        assert not is_compatible
        assert any(c.kind == ChangeKind.PROPERTY_REMOVED for c in breaking)

    def test_backward_incompatible_required(self):
        """Adding required field should break backward compatibility."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id", "name"],
        }
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.BACKWARD)
        assert not is_compatible

    def test_forward_compatible_removal(self):
        """Removing optional field should be forward compatible."""
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id"],
        }
        new = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.FORWARD)
        assert is_compatible

    def test_forward_incompatible_addition(self):
        """Adding a field should break forward compatibility."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.FORWARD)
        assert not is_compatible

    def test_full_compatibility_strict(self):
        """Full compatibility should reject both additions and removals."""
        base = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
        added = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id"],
        }

        # Addition breaks full
        is_compatible, _ = check_compatibility(base, added, CompatibilityMode.FULL)
        assert not is_compatible

        # Removal also breaks full
        is_compatible, _ = check_compatibility(added, base, CompatibilityMode.FULL)
        assert not is_compatible

    def test_none_mode_allows_anything(self):
        """None mode should allow any change."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new = {"type": "object", "properties": {"name": {"type": "string"}}}
        is_compatible, breaking = check_compatibility(old, new, CompatibilityMode.NONE)
        assert is_compatible
        assert len(breaking) == 0


class TestArraySchemas:
    """Test array schema handling."""

    def test_array_items_type_changed(self):
        """Changing array item type should be detected."""
        old = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        new = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "integer"}}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.TYPE_CHANGED for c in result.changes)

    def test_array_items_property_added(self):
        """Adding property to array items should be detected."""
        old = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
                }
            },
        }
        new = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                    },
                }
            },
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.PROPERTY_ADDED for c in result.changes)


class TestChangeTypeClassification:
    """Test that change types are classified correctly."""

    def test_patch_for_no_changes(self):
        """No changes should be classified as PATCH."""
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = diff_schemas(schema, schema)
        assert result.change_type == ChangeType.PATCH

    def test_minor_for_additions(self):
        """Backward-compatible additions should be MINOR."""
        old = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        result = diff_schemas(old, new)
        assert result.change_type == ChangeType.MINOR

    def test_major_for_breaking(self):
        """Breaking changes should be MAJOR."""
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        new = {"type": "object", "properties": {"id": {"type": "integer"}}}
        result = diff_schemas(old, new)
        assert result.change_type == ChangeType.MAJOR
