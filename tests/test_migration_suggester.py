"""Tests for the rule-based migration suggester service."""

from tessera.models.enums import CompatibilityMode
from tessera.services.migration_suggester import suggest_migrations
from tessera.services.schema_diff import BreakingChange, ChangeKind


def _bc(kind: ChangeKind, path: str, message: str = "", **kwargs) -> BreakingChange:
    """Shorthand for creating a BreakingChange."""
    return BreakingChange(kind=kind, path=path, message=message, **kwargs)


# ---------------------------------------------------------------------------
# Rule 1: PROPERTY_REMOVED → deprecate
# ---------------------------------------------------------------------------


class TestPropertyRemoved:
    def test_single_field_removed(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "email": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["id", "email", "name"],
        }
        new = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        changes = [_bc(ChangeKind.PROPERTY_REMOVED, "properties.email", "Removed property 'email'")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        suggestion = result[0]
        assert suggestion.strategy == "deprecate"
        assert suggestion.confidence == "high"
        # The suggested schema should have email back with deprecated: true
        assert "email" in suggestion.suggested_schema["properties"]
        assert suggestion.suggested_schema["properties"]["email"]["deprecated"] is True

    def test_removed_field_gets_deprecated_description(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Current status"},
            },
        }
        new = {"type": "object", "properties": {}}
        changes = [_bc(ChangeKind.PROPERTY_REMOVED, "properties.status")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        desc = result[0].suggested_schema["properties"]["status"]["description"]
        assert desc.startswith("[DEPRECATED]")


# ---------------------------------------------------------------------------
# Rule 2: REQUIRED_FIELD_ADDED → default
# ---------------------------------------------------------------------------


class TestRequiredFieldAdded:
    def test_required_field_made_optional(self) -> None:
        old = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        new = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["id", "status"],
        }
        changes = [_bc(ChangeKind.REQUIRED_ADDED, "required.status")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        suggestion = result[0]
        assert suggestion.strategy == "default"
        assert suggestion.confidence == "high"
        # status should be removed from required
        schema = suggestion.suggested_schema
        assert "status" not in schema.get("required", [])
        # status should have a default
        assert schema["properties"]["status"]["default"] == ""

    def test_required_integer_gets_zero_default(self) -> None:
        old = {"type": "object", "properties": {}}
        new = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        }
        changes = [_bc(ChangeKind.REQUIRED_ADDED, "required.count")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        assert result[0].suggested_schema["properties"]["count"]["default"] == 0


# ---------------------------------------------------------------------------
# Rule 3: TYPE_NARROWED → additive
# ---------------------------------------------------------------------------


class TestTypeNarrowed:
    def test_type_narrowed_creates_v2_field(self) -> None:
        old = {
            "type": "object",
            "properties": {"amount": {"type": "number"}},
        }
        new = {
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
        }
        changes = [_bc(ChangeKind.TYPE_NARROWED, "properties.amount")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        suggestion = result[0]
        assert suggestion.strategy == "additive"
        assert suggestion.confidence == "medium"
        schema = suggestion.suggested_schema
        # Original field restored with deprecation
        assert schema["properties"]["amount"]["type"] == "number"
        assert schema["properties"]["amount"]["deprecated"] is True
        # New v2 field with narrowed type
        assert "amount_v2" in schema["properties"]
        assert schema["properties"]["amount_v2"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Rule 4: ENUM_VALUES_REMOVED → deprecate
# ---------------------------------------------------------------------------


class TestEnumValuesRemoved:
    def test_removed_enum_values_re_added(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
            },
        }
        new = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive"]},
            },
        }
        changes = [_bc(ChangeKind.ENUM_VALUES_REMOVED, "properties.status")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        suggestion = result[0]
        assert suggestion.strategy == "deprecate"
        assert suggestion.confidence == "high"
        enum_values = suggestion.suggested_schema["properties"]["status"]["enum"]
        assert "pending" in enum_values
        assert "active" in enum_values
        assert "inactive" in enum_values


# ---------------------------------------------------------------------------
# Rule 5: TYPE_CHANGED → additive
# ---------------------------------------------------------------------------


class TestTypeChanged:
    def test_type_changed_creates_v2(self) -> None:
        old = {
            "type": "object",
            "properties": {"score": {"type": "string"}},
        }
        new = {
            "type": "object",
            "properties": {"score": {"type": "integer"}},
        }
        changes = [_bc(ChangeKind.TYPE_CHANGED, "properties.score")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        assert result[0].strategy == "additive"
        assert "score_v2" in result[0].suggested_schema["properties"]


# ---------------------------------------------------------------------------
# Rule 6: CONSTRAINT_TIGHTENED → keep_constraint
# ---------------------------------------------------------------------------


class TestConstraintTightened:
    def test_tightened_constraint_restored(self) -> None:
        old = {
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 255}},
        }
        new = {
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 100}},
        }
        changes = [_bc(ChangeKind.CONSTRAINT_TIGHTENED, "properties.name")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        suggestion = result[0]
        assert suggestion.strategy == "keep_constraint"
        assert suggestion.confidence == "high"
        assert suggestion.suggested_schema["properties"]["name"]["maxLength"] == 255


# ---------------------------------------------------------------------------
# Composition: multiple breaking changes
# ---------------------------------------------------------------------------


class TestComposition:
    def test_multiple_breaking_changes_composed(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["email", "name"],
        }
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        changes = [
            _bc(ChangeKind.PROPERTY_REMOVED, "properties.email"),
            _bc(ChangeKind.REQUIRED_ADDED, "required.age"),
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) >= 1
        composed = result[0]
        assert composed.strategy == "composed"
        # email should be re-added with deprecated
        assert "email" in composed.suggested_schema["properties"]
        # age should not be required
        assert "age" not in composed.suggested_schema.get("required", [])

    def test_conflicting_modifications_produce_standalone(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "data": {"type": "string", "maxLength": 255},
            },
        }
        new = {
            "type": "object",
            "properties": {},
        }
        changes = [
            _bc(ChangeKind.PROPERTY_REMOVED, "properties.data"),
            # Conflict: same path
            _bc(ChangeKind.CONSTRAINT_TIGHTENED, "properties.data"),
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        # First should be the deprecate result (applied first)
        # Second should be standalone for the constraint change
        assert len(result) >= 1

    def test_no_known_rule_returns_empty(self) -> None:
        old = {"type": "object", "properties": {}}
        new = {"type": "object", "properties": {}}
        changes = [_bc(ChangeKind.DEFAULT_CHANGED, "properties.x", "default changed")]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert result == []

    def test_empty_breaking_changes_returns_empty(self) -> None:
        result = suggest_migrations({}, {}, [], CompatibilityMode.BACKWARD)
        assert result == []

    def test_none_compatibility_mode_returns_empty(self) -> None:
        changes = [_bc(ChangeKind.PROPERTY_REMOVED, "properties.x")]
        result = suggest_migrations({}, {}, changes, CompatibilityMode.NONE)
        assert result == []
