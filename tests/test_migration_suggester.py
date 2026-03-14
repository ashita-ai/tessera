"""Tests for the migration suggester service.

Covers all 6 rules, composition logic, conflict handling,
and edge cases per the spec (docs/adrs/specs/003-migration-suggester.md).
"""

from tessera.models.enums import CompatibilityMode
from tessera.services.migration_suggester import suggest_migrations
from tessera.services.schema_diff import BreakingChange, ChangeKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obj_schema(**properties: dict) -> dict:
    """Build a minimal object schema from property defs."""
    return {
        "type": "object",
        "properties": {name: defn for name, defn in properties.items()},
    }


# ---------------------------------------------------------------------------
# Rule 1: Property Removed -> deprecate
# ---------------------------------------------------------------------------


class TestPropertyRemoved:
    def test_single_field_removed(self) -> None:
        old = _obj_schema(
            user_id={"type": "integer"},
            name={"type": "string"},
        )
        new = _obj_schema(name={"type": "string"})
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.user_id",
                message="Property 'user_id' was removed",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)

        assert len(result) == 1
        s = result[0]
        assert s.strategy == "deprecate"
        assert s.confidence == "high"
        assert "user_id" in s.suggested_schema["properties"]
        assert s.suggested_schema["properties"]["user_id"]["deprecated"] is True

    def test_removed_field_preserves_existing_description(self) -> None:
        old = _obj_schema(
            email={"type": "string", "description": "User email address"},
        )
        new = _obj_schema()
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.email",
                message="Property 'email' was removed",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        prop = result[0].suggested_schema["properties"]["email"]
        assert prop["description"].startswith("Deprecated:")
        assert "User email address" in prop["description"]

    def test_removed_required_field_stays_required(self) -> None:
        old = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["id", "name"],
        }
        new = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.id",
                message="Property 'id' was removed",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        suggested = result[0].suggested_schema
        assert "id" in suggested["properties"]
        assert "id" in suggested.get("required", [])


# ---------------------------------------------------------------------------
# Rule 2: Required Field Added -> default
# ---------------------------------------------------------------------------


class TestRequiredFieldAdded:
    def test_string_field_gets_default(self) -> None:
        old = _obj_schema(name={"type": "string"})
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["email"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.email",
                message="Field 'email' was added to required",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.confidence == "high"
        suggested = s.suggested_schema
        assert "email" not in suggested.get("required", [])
        assert suggested["properties"]["email"].get("default") == ""

    def test_integer_field_gets_zero_default(self) -> None:
        old = _obj_schema(name={"type": "string"})
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["count"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.count",
                message="Field 'count' was added to required",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        suggested = result[0].suggested_schema
        assert suggested["properties"]["count"].get("default") == 0

    def test_unknown_type_gets_medium_confidence(self) -> None:
        old = _obj_schema(name={"type": "string"})
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "data": {"type": "null"},
            },
            "required": ["data"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.data",
                message="Field 'data' was added to required",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert result[0].confidence == "medium"

    def test_required_list_removed_when_empty(self) -> None:
        old = _obj_schema(name={"type": "string"})
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tag": {"type": "string"},
            },
            "required": ["tag"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.tag",
                message="Field 'tag' was added to required",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        suggested = result[0].suggested_schema
        assert "required" not in suggested or "tag" not in suggested.get("required", [])


# ---------------------------------------------------------------------------
# Rule 3: Type Narrowed -> additive (_v2)
# ---------------------------------------------------------------------------


class TestTypeNarrowed:
    def test_number_to_integer(self) -> None:
        old = _obj_schema(score={"type": "number"})
        new = _obj_schema(score={"type": "integer"})
        changes = [
            BreakingChange(
                kind=ChangeKind.TYPE_NARROWED,
                path="properties.score",
                message="Type narrowed from number to integer",
                old_value="number",
                new_value="integer",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.strategy == "additive"
        assert s.confidence == "medium"
        props = s.suggested_schema["properties"]
        assert props["score"]["type"] == "number"
        assert props["score"]["deprecated"] is True
        assert props["score_v2"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Rule 4: Enum Values Removed -> deprecate
# ---------------------------------------------------------------------------


class TestEnumValuesRemoved:
    def test_single_value_removed(self) -> None:
        old = _obj_schema(status={"type": "string", "enum": ["active", "pending", "archived"]})
        new = _obj_schema(status={"type": "string", "enum": ["active", "archived"]})
        changes = [
            BreakingChange(
                kind=ChangeKind.ENUM_VALUES_REMOVED,
                path="properties.status",
                message="Enum value 'pending' was removed",
                old_value=["active", "pending", "archived"],
                new_value=["active", "archived"],
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.strategy == "deprecate"
        assert s.confidence == "high"
        assert "pending" in s.suggested_schema["properties"]["status"]["enum"]
        assert "Deprecated" in s.suggested_schema["properties"]["status"].get("description", "")


# ---------------------------------------------------------------------------
# Rule 5: Type Changed (general) -> additive
# ---------------------------------------------------------------------------


class TestTypeChanged:
    def test_string_to_integer(self) -> None:
        old = _obj_schema(id={"type": "string"})
        new = _obj_schema(id={"type": "integer"})
        changes = [
            BreakingChange(
                kind=ChangeKind.TYPE_CHANGED,
                path="properties.id",
                message="Type changed from string to integer",
                old_value="string",
                new_value="integer",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.strategy == "additive"
        assert s.confidence == "medium"
        props = s.suggested_schema["properties"]
        assert props["id"]["type"] == "string"
        assert props["id"]["deprecated"] is True
        assert props["id_v2"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Rule 6: Constraint Tightened -> keep_constraint
# ---------------------------------------------------------------------------


class TestConstraintTightened:
    def test_maxlength_reduced(self) -> None:
        old = _obj_schema(name={"type": "string", "maxLength": 100})
        new = _obj_schema(name={"type": "string", "maxLength": 50})
        changes = [
            BreakingChange(
                kind=ChangeKind.CONSTRAINT_TIGHTENED,
                path="properties.name",
                message="maxLength reduced from 100 to 50",
                old_value=100,
                new_value=50,
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.strategy == "keep_constraint"
        assert s.confidence == "high"
        assert s.suggested_schema["properties"]["name"]["maxLength"] == 100

    def test_minimum_increased(self) -> None:
        old = _obj_schema(age={"type": "integer", "minimum": 0})
        new = _obj_schema(age={"type": "integer", "minimum": 18})
        changes = [
            BreakingChange(
                kind=ChangeKind.CONSTRAINT_TIGHTENED,
                path="properties.age",
                message="minimum increased from 0 to 18",
                old_value=0,
                new_value=18,
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert result[0].suggested_schema["properties"]["age"]["minimum"] == 0

    def test_new_constraint_added(self) -> None:
        """A constraint that didn't exist before counts as tightening."""
        old = _obj_schema(name={"type": "string"})
        new = _obj_schema(name={"type": "string", "maxLength": 50})
        changes = [
            BreakingChange(
                kind=ChangeKind.CONSTRAINT_TIGHTENED,
                path="properties.name",
                message="maxLength constraint added",
                old_value=None,
                new_value=50,
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert "maxLength" not in result[0].suggested_schema["properties"]["name"]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    def test_multiple_non_conflicting_changes(self) -> None:
        """Two changes on different paths compose into one suggestion."""
        old = {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        new = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["email"],
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.user_id",
                message="Property 'user_id' was removed",
            ),
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.email",
                message="Field 'email' was added to required",
            ),
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert len(result) == 1
        s = result[0]
        assert s.strategy == "mixed"
        assert len(s.changes_made) == 2
        # Both modifications applied
        assert "user_id" in s.suggested_schema["properties"]
        assert s.suggested_schema["properties"]["user_id"]["deprecated"] is True
        assert "email" not in s.suggested_schema.get("required", [])

    def test_conflicting_changes_produce_standalone(self) -> None:
        """Two changes on the same path: first composes, second is standalone."""
        old = _obj_schema(
            name={"type": "string", "maxLength": 100},
        )
        new = _obj_schema(
            name={"type": "integer", "maxLength": 50},
        )
        changes = [
            BreakingChange(
                kind=ChangeKind.TYPE_CHANGED,
                path="properties.name",
                message="Type changed from string to integer",
                old_value="string",
                new_value="integer",
            ),
            BreakingChange(
                kind=ChangeKind.CONSTRAINT_TIGHTENED,
                path="properties.name",
                message="maxLength reduced from 100 to 50",
                old_value=100,
                new_value=50,
            ),
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        # First change composes, second is standalone due to path conflict
        assert len(result) >= 2
        assert result[0].strategy == "additive"  # TYPE_CHANGED composed first
        assert result[1].strategy == "keep_constraint"  # standalone

    def test_lowest_confidence_wins(self) -> None:
        """Composed confidence should be the minimum across all rules."""
        old = {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "score": {"type": "number"},
            },
        }
        new = {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
            },
        }
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.user_id",
                message="Property removed",
            ),
            BreakingChange(
                kind=ChangeKind.TYPE_NARROWED,
                path="properties.score",
                message="Type narrowed",
                old_value="number",
                new_value="integer",
            ),
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert result[0].confidence == "medium"  # TYPE_NARROWED is medium


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_breaking_changes_returns_empty(self) -> None:
        old = _obj_schema(name={"type": "string"})
        new = _obj_schema(name={"type": "string"})

        result = suggest_migrations(old, new, [], CompatibilityMode.BACKWARD)
        assert result == []

    def test_compatibility_none_returns_empty(self) -> None:
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.x",
                message="Removed",
            )
        ]
        result = suggest_migrations({}, {}, changes, CompatibilityMode.NONE)
        assert result == []

    def test_unknown_change_kind_returns_empty(self) -> None:
        """A change kind with no matching rule produces no suggestions."""
        old = _obj_schema(name={"type": "string"})
        new = _obj_schema(name={"type": "string"})
        changes = [
            BreakingChange(
                kind=ChangeKind.NULLABLE_REMOVED,
                path="properties.name",
                message="Nullable removed",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert result == []

    def test_forward_breaking_change(self) -> None:
        """Forward compatibility mode should still generate suggestions."""
        old = _obj_schema(name={"type": "string"})
        new = _obj_schema(
            name={"type": "string"},
            email={"type": "string"},
        )
        new["required"] = ["email"]
        changes = [
            BreakingChange(
                kind=ChangeKind.REQUIRED_ADDED,
                path="required.email",
                message="Field 'email' was added to required",
            )
        ]

        result = suggest_migrations(old, new, changes, CompatibilityMode.FORWARD)
        assert len(result) == 1

    def test_suggested_schema_is_deep_copy(self) -> None:
        """Ensure the original schemas are not mutated."""
        old = _obj_schema(user_id={"type": "integer"}, name={"type": "string"})
        new = _obj_schema(name={"type": "string"})
        old_copy = {
            "type": "object",
            "properties": {"user_id": {"type": "integer"}, "name": {"type": "string"}},
        }
        new_copy = {"type": "object", "properties": {"name": {"type": "string"}}}
        changes = [
            BreakingChange(
                kind=ChangeKind.PROPERTY_REMOVED,
                path="properties.user_id",
                message="Property 'user_id' was removed",
            )
        ]

        suggest_migrations(old, new, changes, CompatibilityMode.BACKWARD)
        assert old == old_copy
        assert new == new_copy
