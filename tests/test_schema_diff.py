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
    resolve_refs,
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
        """Changing volume guarantee should be detected with per-field kinds."""
        old = {"volume": {"min_rows": 100, "max_rows": 10000}}
        new = {"volume": {"min_rows": 50, "max_rows": 5000}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        kinds = {c.kind for c in result.changes}
        # min_rows decreased = RELAXED, max_rows decreased = TIGHTENED
        assert GuaranteeChangeKind.VOLUME_RELAXED in kinds
        assert GuaranteeChangeKind.VOLUME_TIGHTENED in kinds

    # --- Bug 1: Freshness direction tests ---

    def test_freshness_tightened(self):
        """Tightening freshness (48h -> 12h) should emit TIGHTENED (INFO)."""
        old = {"freshness": {"warn_after": {"hours": 48}}}
        new = {"freshness": {"warn_after": {"hours": 12}}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        tightened = [c for c in result.changes if c.kind == GuaranteeChangeKind.FRESHNESS_TIGHTENED]
        assert len(tightened) == 1
        assert tightened[0].severity == GuaranteeChangeSeverity.INFO

    def test_freshness_relaxed_correctly(self):
        """Relaxing freshness (12h -> 48h) should emit RELAXED (WARNING)."""
        old = {"freshness": {"warn_after": {"hours": 12}}}
        new = {"freshness": {"warn_after": {"hours": 48}}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        relaxed = [c for c in result.changes if c.kind == GuaranteeChangeKind.FRESHNESS_RELAXED]
        assert len(relaxed) == 1
        assert relaxed[0].severity == GuaranteeChangeSeverity.WARNING

    def test_freshness_max_staleness_tightened(self):
        """Tightening max_staleness_minutes (120 -> 30) should emit TIGHTENED."""
        old = {"freshness": {"max_staleness_minutes": 120}}
        new = {"freshness": {"max_staleness_minutes": 30}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        tightened = [c for c in result.changes if c.kind == GuaranteeChangeKind.FRESHNESS_TIGHTENED]
        assert len(tightened) == 1

    def test_freshness_max_staleness_relaxed(self):
        """Relaxing max_staleness_minutes (30 -> 120) should emit RELAXED."""
        old = {"freshness": {"max_staleness_minutes": 30}}
        new = {"freshness": {"max_staleness_minutes": 120}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        relaxed = [c for c in result.changes if c.kind == GuaranteeChangeKind.FRESHNESS_RELAXED]
        assert len(relaxed) == 1

    def test_freshness_unrecognizable_defaults_to_relaxed(self):
        """Unrecognisable freshness format should default to RELAXED (WARNING)."""
        old = {"freshness": {"custom_field": "fast"}}
        new = {"freshness": {"custom_field": "slow"}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        relaxed = [c for c in result.changes if c.kind == GuaranteeChangeKind.FRESHNESS_RELAXED]
        assert len(relaxed) == 1
        assert relaxed[0].severity == GuaranteeChangeSeverity.WARNING

    # --- Bug 2: Volume direction tests ---

    def test_volume_min_rows_tightened(self):
        """Increasing min_rows (50 -> 100) = TIGHTENED (INFO)."""
        old = {"volume": {"min_rows": 50}}
        new = {"volume": {"min_rows": 100}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        tightened = [c for c in result.changes if c.kind == GuaranteeChangeKind.VOLUME_TIGHTENED]
        assert len(tightened) == 1
        assert tightened[0].severity == GuaranteeChangeSeverity.INFO

    def test_volume_min_rows_relaxed(self):
        """Decreasing min_rows (100 -> 50) = RELAXED (WARNING)."""
        old = {"volume": {"min_rows": 100}}
        new = {"volume": {"min_rows": 50}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        relaxed = [c for c in result.changes if c.kind == GuaranteeChangeKind.VOLUME_RELAXED]
        assert len(relaxed) == 1
        assert relaxed[0].severity == GuaranteeChangeSeverity.WARNING

    def test_volume_max_rows_tightened(self):
        """Decreasing max_rows (10000 -> 5000) = TIGHTENED (INFO)."""
        old = {"volume": {"max_rows": 10000}}
        new = {"volume": {"max_rows": 5000}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        tightened = [c for c in result.changes if c.kind == GuaranteeChangeKind.VOLUME_TIGHTENED]
        assert len(tightened) == 1
        assert tightened[0].severity == GuaranteeChangeSeverity.INFO

    def test_volume_max_rows_relaxed(self):
        """Increasing max_rows (5000 -> 10000) = RELAXED (WARNING)."""
        old = {"volume": {"max_rows": 5000}}
        new = {"volume": {"max_rows": 10000}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        relaxed = [c for c in result.changes if c.kind == GuaranteeChangeKind.VOLUME_RELAXED]
        assert len(relaxed) == 1
        assert relaxed[0].severity == GuaranteeChangeSeverity.WARNING

    def test_volume_mixed_signals(self):
        """Mixed volume changes should emit separate changes per field."""
        old = {"volume": {"min_rows": 100, "max_rows": 10000}}
        new = {"volume": {"min_rows": 50, "max_rows": 5000}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        # min_rows decreased = RELAXED, max_rows decreased = TIGHTENED
        volume_changes = [c for c in result.changes if c.path.startswith("volume.")]
        assert len(volume_changes) == 2
        kinds = {c.kind for c in volume_changes}
        assert GuaranteeChangeKind.VOLUME_RELAXED in kinds
        assert GuaranteeChangeKind.VOLUME_TIGHTENED in kinds

    # --- Bug 3: Accepted values mixed change tests ---

    def test_accepted_values_mixed_emits_both(self):
        """Mixed adds + removes should emit both CONTRACTED and EXPANDED."""
        old = {"accepted_values": {"status": ["active", "pending"]}}
        new = {"accepted_values": {"status": ["active", "archived"]}}
        result = diff_guarantees(old, new)
        assert result.has_changes
        kinds = [c.kind for c in result.changes]
        assert GuaranteeChangeKind.ACCEPTED_VALUES_CONTRACTED in kinds
        assert GuaranteeChangeKind.ACCEPTED_VALUES_EXPANDED in kinds
        assert len(result.changes) == 2

    def test_accepted_values_mixed_is_breaking_strict(self):
        """Mixed accepted_values changes should be breaking in STRICT mode.

        EXPANDED carries WARNING severity, which triggers is_breaking(STRICT).
        """
        old = {"accepted_values": {"status": ["active", "pending"]}}
        new = {"accepted_values": {"status": ["active", "archived"]}}
        result = diff_guarantees(old, new)
        assert result.is_breaking(GuaranteeMode.STRICT)


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


class TestRefResolution:
    """Test $ref resolution before schema diffing."""

    def test_resolve_simple_def(self):
        """Resolve a simple $ref to $defs."""
        schema = {
            "type": "object",
            "properties": {"user": {"$ref": "#/$defs/User"}},
            "$defs": {"User": {"type": "object", "properties": {"name": {"type": "string"}}}},
        }
        resolved = resolve_refs(schema)
        # The $ref should be replaced with the actual definition
        assert resolved["properties"]["user"]["type"] == "object"
        assert "name" in resolved["properties"]["user"]["properties"]

    def test_resolve_definitions_key(self):
        """Resolve $ref using 'definitions' instead of '$defs'."""
        schema = {
            "type": "object",
            "properties": {"user": {"$ref": "#/definitions/User"}},
            "definitions": {"User": {"type": "object", "properties": {"name": {"type": "string"}}}},
        }
        resolved = resolve_refs(schema)
        assert resolved["properties"]["user"]["type"] == "object"

    def test_resolve_nested_refs(self):
        """Resolve nested $ref pointers."""
        schema = {
            "type": "object",
            "properties": {"user": {"$ref": "#/$defs/User"}},
            "$defs": {
                "User": {
                    "type": "object",
                    "properties": {"address": {"$ref": "#/$defs/Address"}},
                },
                "Address": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
        resolved = resolve_refs(schema)
        # Both $refs should be resolved
        user = resolved["properties"]["user"]
        assert user["type"] == "object"
        assert user["properties"]["address"]["properties"]["city"]["type"] == "string"

    def test_circular_refs_handled(self):
        """Circular $refs should be handled without infinite recursion."""
        schema = {
            "type": "object",
            "properties": {"node": {"$ref": "#/$defs/Node"}},
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "next": {"$ref": "#/$defs/Node"},  # Circular!
                    },
                }
            },
        }
        # Should not raise RecursionError
        resolved = resolve_refs(schema)
        assert resolved is not None

    def test_external_refs_preserved(self):
        """External $ref (not starting with #) should be preserved."""
        schema = {
            "type": "object",
            "properties": {"external": {"$ref": "https://example.com/schema.json"}},
        }
        resolved = resolve_refs(schema)
        # External refs should remain as-is
        assert resolved["properties"]["external"]["$ref"] == "https://example.com/schema.json"

    def test_diff_with_refs_resolved(self):
        """Two semantically identical schemas with different ref usage should be equal."""
        # Schema using $ref
        schema_with_ref = {
            "type": "object",
            "properties": {"email": {"$ref": "#/$defs/Email"}},
            "$defs": {"Email": {"type": "string", "format": "email"}},
        }
        # Schema with inline definition (semantically identical)
        schema_inline = {
            "type": "object",
            "properties": {"email": {"type": "string", "format": "email"}},
        }

        # With ref resolution (default), these should be identical
        result = diff_schemas(schema_with_ref, schema_inline)
        # The only difference should be the $defs being present in one schema
        # but not used in the resolved comparison, so no property changes
        property_changes = [c for c in result.changes if "properties" in c.path]
        assert len(property_changes) == 0

    def test_diff_detects_changes_after_ref_resolution(self):
        """Changes should be detected after $ref resolution."""
        old = {
            "type": "object",
            "properties": {"data": {"$ref": "#/$defs/Data"}},
            "$defs": {"Data": {"type": "string"}},
        }
        new = {
            "type": "object",
            "properties": {"data": {"$ref": "#/$defs/Data"}},
            "$defs": {"Data": {"type": "integer"}},  # Type changed!
        }

        result = diff_schemas(old, new)
        assert result.has_changes
        assert any(c.kind == ChangeKind.TYPE_CHANGED for c in result.changes)

    def test_resolve_with_additional_properties(self):
        """$ref with additional sibling properties should merge them."""
        schema = {
            "type": "object",
            "properties": {
                "name": {
                    "$ref": "#/$defs/String",
                    "description": "User's name",  # Additional property
                }
            },
            "$defs": {"String": {"type": "string", "maxLength": 100}},
        }
        resolved = resolve_refs(schema)
        # Should have both the ref content and the additional property
        name_prop = resolved["properties"]["name"]
        assert name_prop["type"] == "string"
        assert name_prop["maxLength"] == 100
        assert name_prop["description"] == "User's name"


class TestDepthProtection:
    """Test protection against circular/deeply nested schemas."""

    def test_deeply_nested_schema_does_not_overflow(self):
        """Schemas nested deeper than MAX_DEPTH should not cause stack overflow."""

        # Create a schema nested deeper than MAX_DEPTH (50)
        def create_nested_schema(depth: int) -> dict:
            if depth == 0:
                return {"type": "string"}
            return {
                "type": "object",
                "properties": {"nested": create_nested_schema(depth - 1)},
            }

        old = create_nested_schema(60)  # 60 levels deep
        new = create_nested_schema(60)

        # This should not raise RecursionError
        result = diff_schemas(old, new)
        assert not result.has_changes

    def test_array_nesting_does_not_overflow(self):
        """Deeply nested arrays should not cause stack overflow."""

        # Create a schema with deeply nested arrays
        def create_nested_array(depth: int) -> dict:
            if depth == 0:
                return {"type": "string"}
            return {"type": "array", "items": create_nested_array(depth - 1)}

        old = create_nested_array(60)  # 60 levels of nested arrays
        new = create_nested_array(60)

        # Should complete without overflow
        result = diff_schemas(old, new)
        assert not result.has_changes

    def test_changes_detected_within_max_depth(self):
        """Changes within MAX_DEPTH should still be detected."""
        # Create a schema with a change at a moderate depth
        old = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
        new = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {"type": "integer"},  # Changed from string
                            },
                        },
                    },
                },
            },
        }

        result = diff_schemas(old, new)
        assert result.has_changes
        # Should detect the type change
        assert any(c.kind == ChangeKind.TYPE_CHANGED for c in result.changes)


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
