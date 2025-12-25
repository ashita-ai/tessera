"""Tests for schema diffing service."""

from tessera.models.enums import ChangeType, CompatibilityMode
from tessera.services.schema_diff import (
    ChangeKind,
    GuaranteeChangeKind,
    GuaranteeChangeSeverity,
    GuaranteeMode,
    check_compatibility,
    check_guarantee_compatibility,
    diff_contracts,
    diff_guarantees,
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
        assert any(c.kind == ChangeKind.PROPERTY_ADDED and "city" in c.path for c in result.changes)


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


class TestArrayConstraintChanges:
    """Test array constraint changes like minItems, maxItems, etc."""

    def test_constraint_relaxed_min_items(self):
        """Relaxing minItems constraint should be detected."""
        old = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}, "minItems": 3}},
        }
        new = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_RELAXED for c in result.changes)

    def test_constraint_tightened_min_items(self):
        """Tightening minItems constraint should be detected."""
        old = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        }
        new = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}, "minItems": 5}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_TIGHTENED for c in result.changes)

    def test_pattern_changed(self):
        """Changing pattern constraint should be detected as tightening."""
        old = {
            "type": "object",
            "properties": {"email": {"type": "string", "pattern": "^.*$"}},
        }
        new = {
            "type": "object",
            "properties": {"email": {"type": "string", "pattern": "^[a-z]+@[a-z]+\\.[a-z]+$"}},
        }
        result = diff_schemas(old, new)
        assert any(c.kind == ChangeKind.CONSTRAINT_TIGHTENED for c in result.changes)


class TestGuaranteeDiff:
    """Test guarantee diffing functionality."""

    def test_no_changes(self):
        """Identical guarantees should produce no changes."""
        guarantees = {
            "nullability": {"id": True, "name": True},
            "uniqueness": {"id": True},
        }
        result = diff_guarantees(guarantees, guarantees)
        assert not result.has_changes

    def test_nullability_added(self):
        """Adding not_null constraint should be detected."""
        old = {"nullability": {"id": True}}
        new = {"nullability": {"id": True, "email": True}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        assert any(c.kind == GuaranteeChangeKind.NOT_NULL_ADDED for c in result.changes)

    def test_nullability_removed(self):
        """Removing not_null constraint should be detected as warning."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        assert any(c.kind == GuaranteeChangeKind.NOT_NULL_REMOVED for c in result.changes)
        assert any(c.severity == GuaranteeChangeSeverity.WARNING for c in result.changes)

    def test_uniqueness_added(self):
        """Adding unique constraint should be detected."""
        old = {"uniqueness": {"id": True}}
        new = {"uniqueness": {"id": True, "email": True}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        assert any(c.kind == GuaranteeChangeKind.UNIQUE_ADDED for c in result.changes)

    def test_uniqueness_removed(self):
        """Removing unique constraint should be detected as warning."""
        old = {"uniqueness": {"id": True, "email": True}}
        new = {"uniqueness": {"id": True}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        assert any(c.kind == GuaranteeChangeKind.UNIQUE_REMOVED for c in result.changes)

    def test_accepted_values_expanded(self):
        """Expanding accepted values should be detected."""
        old = {"accepted_values": {"status": ["active"]}}
        new = {"accepted_values": {"status": ["active", "pending"]}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        # Adding a new accepted value = expanded constraint
        assert any(c.kind == GuaranteeChangeKind.ACCEPTED_VALUES_EXPANDED for c in result.changes)

    def test_accepted_values_contracted(self):
        """Contracting accepted values should be detected as warning."""
        old = {"accepted_values": {"status": ["active", "pending"]}}
        new = {"accepted_values": {"status": ["active"]}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        # Removing an accepted value = contracted constraint
        assert any(c.kind == GuaranteeChangeKind.ACCEPTED_VALUES_CONTRACTED for c in result.changes)

    def test_freshness_added(self):
        """Adding freshness guarantee should be detected."""
        old = {}
        new = {"freshness": {"warn_after": {"hours": 24}}}
        result = diff_guarantees(old, new)
        assert result.has_changes

    def test_freshness_relaxed(self):
        """Relaxing freshness guarantee should be warning."""
        old = {"freshness": {"warn_after": {"hours": 12}}}
        new = {"freshness": {"warn_after": {"hours": 48}}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        assert any(c.severity == GuaranteeChangeSeverity.WARNING for c in result.changes)

    def test_relationship_added(self):
        """Adding relationship guarantee should be detected."""
        old = {"relationships": {}}
        new = {"relationships": {"user_id": {"to": "users.id"}}}
        result = diff_guarantees(old, new)
        assert result.has_changes

    def test_volume_changed(self):
        """Changing volume guarantee should be detected."""
        old = {"volume": {"min_rows": 100, "max_rows": 10000}}
        new = {"volume": {"min_rows": 50, "max_rows": 5000}}
        result = diff_guarantees(old, new)
        assert result.has_changes


class TestGuaranteeDiffResult:
    """Test GuaranteeDiffResult methods."""

    def test_by_severity(self):
        """Test filtering changes by severity."""
        old = {"nullability": {"id": True, "email": True}, "uniqueness": {"id": True}}
        new = {"nullability": {"id": True}, "uniqueness": {"id": True, "email": True}}
        result = diff_guarantees(old, new)
        # Should have both INFO (uniqueness added) and WARNING (nullability removed)
        assert len(result.info_changes) > 0 or len(result.warning_changes) > 0

    def test_is_breaking_ignore_mode(self):
        """Ignore mode should never be breaking."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        result = diff_guarantees(old, new)
        assert not result.is_breaking(GuaranteeMode.IGNORE)

    def test_is_breaking_notify_mode(self):
        """Notify mode should never block."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        result = diff_guarantees(old, new)
        assert not result.is_breaking(GuaranteeMode.NOTIFY)

    def test_is_breaking_strict_mode(self):
        """Strict mode should block on warning changes."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        result = diff_guarantees(old, new)
        assert result.is_breaking(GuaranteeMode.STRICT)

    def test_breaking_changes_returns_warnings(self):
        """breaking_changes should return warnings in strict mode."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        result = diff_guarantees(old, new)
        breaking = result.breaking_changes(GuaranteeMode.STRICT)
        assert len(breaking) > 0


class TestGuaranteeChange:
    """Test GuaranteeChange serialization."""

    def test_to_dict(self):
        """Test GuaranteeChange.to_dict serialization."""
        old = {"nullability": {"id": True}}
        new = {"nullability": {"id": True, "email": True}}
        result = diff_guarantees(old, new)
        for change in result.changes:
            d = change.to_dict()
            assert "type" in d
            assert "path" in d
            assert "message" in d
            assert "severity" in d


class TestCheckGuaranteeCompatibility:
    """Test check_guarantee_compatibility function."""

    def test_compatible_ignore_mode(self):
        """Any change is compatible in ignore mode."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        is_compatible, breaking = check_guarantee_compatibility(old, new, GuaranteeMode.IGNORE)
        assert is_compatible
        assert len(breaking) == 0

    def test_compatible_notify_mode(self):
        """Any change is compatible in notify mode."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        is_compatible, breaking = check_guarantee_compatibility(old, new, GuaranteeMode.NOTIFY)
        assert is_compatible

    def test_incompatible_strict_mode(self):
        """Removing guarantees breaks strict mode."""
        old = {"nullability": {"id": True, "email": True}}
        new = {"nullability": {"id": True}}
        is_compatible, breaking = check_guarantee_compatibility(old, new, GuaranteeMode.STRICT)
        assert not is_compatible
        assert len(breaking) > 0


class TestDiffContracts:
    """Test diff_contracts function for full contract comparison."""

    def test_diff_contracts_schema_only(self):
        """Test diffing contracts with only schema changes."""
        old_schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new_schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        result = diff_contracts(old_schema, new_schema)
        assert result.schema_diff.has_changes
        assert not result.guarantee_diff.has_changes

    def test_diff_contracts_guarantees_only(self):
        """Test diffing contracts with only guarantee changes."""
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        old_guarantees = {"nullability": {"id": True}}
        new_guarantees = {"nullability": {"id": True, "name": True}}
        result = diff_contracts(schema, schema, old_guarantees, new_guarantees)
        assert not result.schema_diff.has_changes
        assert result.guarantee_diff.has_changes

    def test_diff_contracts_both(self):
        """Test diffing contracts with both schema and guarantee changes."""
        old_schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        new_schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        }
        old_guarantees = {"nullability": {"id": True}}
        new_guarantees = {"nullability": {"id": True, "name": True}}
        result = diff_contracts(old_schema, new_schema, old_guarantees, new_guarantees)
        assert result.schema_diff.has_changes
        assert result.guarantee_diff.has_changes
        assert result.has_changes
