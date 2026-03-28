"""Tests for input validation."""

from typing import Any

import pytest
from pydantic import ValidationError

from tessera.config import settings
from tessera.models.asset import AssetCreate
from tessera.models.contract import ContractCreate
from tessera.models.team import TeamCreate

OWNER_TEAM_ID = "00000000-0000-0000-0000-000000000001"


class TestFQNValidation:
    """Tests for FQN format validation."""

    @pytest.mark.parametrize(
        "fqn",
        [
            "schema.table",
            "database.schema.table",
            "my_database.my_schema.my_table_name",
            "db1.schema2.table3",
            "_private.schema._hidden_table",
        ],
        ids=["two_segments", "three_segments", "underscores", "numbers", "leading_underscore"],
    )
    def test_valid_fqn(self, fqn: str) -> None:
        """Valid FQN formats are accepted."""
        asset = AssetCreate(fqn=fqn, owner_team_id=OWNER_TEAM_ID)
        assert asset.fqn == fqn

    @pytest.mark.parametrize(
        "fqn",
        [
            "just_a_table",
            "database.my schema.table",
            "database.schema.table-name",
            "database.123schema.table",
            "database..table",
            "database.schema.table.",
            ".database.schema.table",
        ],
        ids=[
            "single_segment",
            "spaces",
            "special_chars",
            "starts_with_number",
            "empty_segment",
            "trailing_dot",
            "leading_dot",
        ],
    )
    def test_invalid_fqn(self, fqn: str) -> None:
        """Invalid FQN formats are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(fqn=fqn, owner_team_id=OWNER_TEAM_ID)
        assert "dot-separated" in str(exc_info.value).lower()

    def test_fqn_too_long(self) -> None:
        """FQN exceeding maximum length is rejected."""
        long_fqn = "a" * 500 + "." + "b" * 500 + "." + "c"
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(fqn=long_fqn, owner_team_id=OWNER_TEAM_ID)
        assert "1000" in str(exc_info.value) or "max_length" in str(exc_info.value)


class TestVersionValidation:
    """Tests for semantic version validation."""

    @pytest.mark.parametrize(
        "version",
        [
            "1.0.0",
            "2.1.0-beta.1",
            "1.0.0+build.123",
            "1.0.0-alpha.1+build.456",
            "100.200.300",
        ],
        ids=["basic", "prerelease", "build_metadata", "prerelease_and_build", "large_numbers"],
    )
    def test_valid_version(self, version: str) -> None:
        """Valid semver strings are accepted."""
        contract = ContractCreate(version=version, schema={"type": "object"})
        assert contract.version == version

    @pytest.mark.parametrize(
        "version",
        ["1.0", "1", "v1.0.0", "1.0.0 beta", ""],
        ids=["missing_patch", "missing_minor", "v_prefix", "spaces", "empty"],
    )
    def test_invalid_version(self, version: str) -> None:
        """Invalid semver strings are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(version=version, schema={"type": "object"})
        error_text = str(exc_info.value).lower()
        assert any(frag in error_text for frag in ("pattern", "string", "short", "length"))


class TestSchemaSizeValidation:
    """Tests for schema size limits."""

    def test_valid_small_schema(self) -> None:
        """Valid small schema."""
        contract = ContractCreate(
            version="1.0.0",
            schema={"type": "object", "properties": {"id": {"type": "integer"}}},
        )
        assert contract.schema_def["type"] == "object"

    def test_valid_medium_schema(self) -> None:
        """Valid medium-sized schema with many properties."""
        properties = {f"field_{i}": {"type": "string"} for i in range(100)}
        contract = ContractCreate(
            version="1.0.0",
            schema={"type": "object", "properties": properties},
        )
        assert len(contract.schema_def["properties"]) == 100

    def test_invalid_oversized_schema(self) -> None:
        """Invalid schema exceeding size limit."""
        large_value = "x" * 100_000
        large_schema = {
            f"field_{i}": {"type": "string", "description": large_value} for i in range(15)
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(version="1.0.0", schema=large_schema)
        assert "too large" in str(exc_info.value).lower()

    def test_invalid_schema_too_many_properties(self) -> None:
        """Invalid schema with too many properties at top level."""
        too_many_props = {
            f"field_{i}": {"type": "string"} for i in range(settings.max_schema_properties + 1)
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1.0.0",
                schema={"type": "object", "properties": too_many_props},
            )
        assert "too many properties" in str(exc_info.value).lower()

    def test_invalid_schema_too_many_nested_properties(self) -> None:
        """Deeply nested schema that exceeds total property limit must be rejected."""
        nested_props = {
            f"nested_{i}": {"type": "string"} for i in range(settings.max_schema_properties + 1)
        }
        schema = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": nested_props,
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(version="1.0.0", schema=schema)
        assert "too many properties" in str(exc_info.value).lower()

    def test_valid_schema_nested_within_limit(self) -> None:
        """Nested schema within both property and depth limits is accepted."""
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        }
                    },
                }
            },
        }
        contract = ContractCreate(version="1.0.0", schema=schema)
        assert contract.schema_def == schema

    def test_invalid_schema_nesting_too_deep(self) -> None:
        """Schema nested beyond max depth must be rejected."""
        schema: dict[str, Any] = {"type": "string"}
        for _ in range(settings.max_schema_nesting_depth + 1):
            schema = {"type": "object", "properties": {"child": schema}}

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(version="1.0.0", schema=schema)
        assert "nesting too deep" in str(exc_info.value).lower()

    def test_valid_schema_array_items_counted(self) -> None:
        """Properties inside array items are counted toward the total."""
        item_props = {
            f"col_{i}": {"type": "string"} for i in range(settings.max_schema_properties + 1)
        }
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": item_props},
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(version="1.0.0", schema=schema)
        assert "too many properties" in str(exc_info.value).lower()


class TestTeamNameValidation:
    """Tests for team name validation."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("analytics", "analytics"),
            ("Data Engineering", "Data Engineering"),
            ("data-platform", "data-platform"),
            ("data_platform", "data_platform"),
            ("team123", "team123"),
            ("A", "A"),
        ],
        ids=["simple", "spaces", "hyphens", "underscores", "numbers", "single_char"],
    )
    def test_valid_name(self, name: str, expected: str) -> None:
        """Valid team names are accepted."""
        team = TeamCreate(name=name)
        assert team.name == expected

    def test_name_strips_whitespace(self) -> None:
        """Name is stripped of leading/trailing whitespace."""
        team = TeamCreate(name="  analytics  ")
        assert team.name == "analytics"

    @pytest.mark.parametrize(
        ("name", "error_fragment"),
        [
            ("", "character"),
            ("   ", "empty"),
            ("-analytics", "start"),
            ("analytics-", "end"),
            ("analytics@team", "alphanumeric"),
        ],
        ids=["empty", "whitespace_only", "starts_with_special", "ends_with_special", "at_sign"],
    )
    def test_invalid_name(self, name: str, error_fragment: str) -> None:
        """Invalid team names are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name=name)
        error_text = str(exc_info.value).lower()
        assert error_fragment in error_text or "short" in error_text or "whitespace" in error_text

    def test_name_too_long(self) -> None:
        """Name exceeds maximum length."""
        long_name = "a" * 256
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name=long_name)
        assert "255" in str(exc_info.value) or "max_length" in str(exc_info.value)
