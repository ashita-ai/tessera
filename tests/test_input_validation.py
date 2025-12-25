"""Tests for input validation."""

import pytest
from pydantic import ValidationError

from tessera.config import settings
from tessera.models.asset import AssetCreate
from tessera.models.contract import ContractCreate
from tessera.models.team import TeamCreate


class TestFQNValidation:
    """Tests for FQN format validation."""

    def test_valid_fqn_two_segments(self) -> None:
        """Valid FQN with two segments."""
        asset = AssetCreate(
            fqn="schema.table",
            owner_team_id="00000000-0000-0000-0000-000000000001",
        )
        assert asset.fqn == "schema.table"

    def test_valid_fqn_three_segments(self) -> None:
        """Valid FQN with three segments."""
        asset = AssetCreate(
            fqn="database.schema.table",
            owner_team_id="00000000-0000-0000-0000-000000000001",
        )
        assert asset.fqn == "database.schema.table"

    def test_valid_fqn_with_underscores(self) -> None:
        """Valid FQN with underscores."""
        asset = AssetCreate(
            fqn="my_database.my_schema.my_table_name",
            owner_team_id="00000000-0000-0000-0000-000000000001",
        )
        assert asset.fqn == "my_database.my_schema.my_table_name"

    def test_valid_fqn_with_numbers(self) -> None:
        """Valid FQN with numbers."""
        asset = AssetCreate(
            fqn="db1.schema2.table3",
            owner_team_id="00000000-0000-0000-0000-000000000001",
        )
        assert asset.fqn == "db1.schema2.table3"

    def test_valid_fqn_starts_with_underscore(self) -> None:
        """Valid FQN segment starting with underscore."""
        asset = AssetCreate(
            fqn="_private.schema._hidden_table",
            owner_team_id="00000000-0000-0000-0000-000000000001",
        )
        assert asset.fqn == "_private.schema._hidden_table"

    def test_invalid_fqn_single_segment(self) -> None:
        """Invalid FQN with only one segment."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="just_a_table",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_with_spaces(self) -> None:
        """Invalid FQN with spaces."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="database.my schema.table",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_with_special_chars(self) -> None:
        """Invalid FQN with special characters."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="database.schema.table-name",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_starts_with_number(self) -> None:
        """Invalid FQN segment starting with number."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="database.123schema.table",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_empty_segment(self) -> None:
        """Invalid FQN with empty segment."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="database..table",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_trailing_dot(self) -> None:
        """Invalid FQN with trailing dot."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn="database.schema.table.",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_invalid_fqn_leading_dot(self) -> None:
        """Invalid FQN with leading dot."""
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn=".database.schema.table",
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "dot-separated" in str(exc_info.value).lower()

    def test_fqn_too_long(self) -> None:
        """FQN exceeds maximum length."""
        long_fqn = "a" * 500 + "." + "b" * 500 + "." + "c"
        with pytest.raises(ValidationError) as exc_info:
            AssetCreate(
                fqn=long_fqn,
                owner_team_id="00000000-0000-0000-0000-000000000001",
            )
        assert "1000" in str(exc_info.value) or "max_length" in str(exc_info.value)


class TestVersionValidation:
    """Tests for semantic version validation."""

    def test_valid_version_basic(self) -> None:
        """Valid basic semver."""
        contract = ContractCreate(
            version="1.0.0",
            schema={"type": "object"},
        )
        assert contract.version == "1.0.0"

    def test_valid_version_with_prerelease(self) -> None:
        """Valid semver with prerelease tag."""
        contract = ContractCreate(
            version="2.1.0-beta.1",
            schema={"type": "object"},
        )
        assert contract.version == "2.1.0-beta.1"

    def test_valid_version_with_build_metadata(self) -> None:
        """Valid semver with build metadata."""
        contract = ContractCreate(
            version="1.0.0+build.123",
            schema={"type": "object"},
        )
        assert contract.version == "1.0.0+build.123"

    def test_valid_version_with_prerelease_and_build(self) -> None:
        """Valid semver with both prerelease and build metadata."""
        contract = ContractCreate(
            version="1.0.0-alpha.1+build.456",
            schema={"type": "object"},
        )
        assert contract.version == "1.0.0-alpha.1+build.456"

    def test_valid_version_large_numbers(self) -> None:
        """Valid semver with large version numbers."""
        contract = ContractCreate(
            version="100.200.300",
            schema={"type": "object"},
        )
        assert contract.version == "100.200.300"

    def test_invalid_version_missing_patch(self) -> None:
        """Invalid version missing patch number."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1.0",
                schema={"type": "object"},
            )
        assert "pattern" in str(exc_info.value).lower() or "string" in str(exc_info.value).lower()

    def test_invalid_version_missing_minor(self) -> None:
        """Invalid version missing minor and patch."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1",
                schema={"type": "object"},
            )
        assert "pattern" in str(exc_info.value).lower() or "string" in str(exc_info.value).lower()

    def test_invalid_version_with_v_prefix(self) -> None:
        """Invalid version with 'v' prefix."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="v1.0.0",
                schema={"type": "object"},
            )
        assert "pattern" in str(exc_info.value).lower()

    def test_invalid_version_with_spaces(self) -> None:
        """Invalid version with spaces."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1.0.0 beta",
                schema={"type": "object"},
            )
        assert "pattern" in str(exc_info.value).lower()

    def test_invalid_version_empty(self) -> None:
        """Invalid empty version."""
        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="",
                schema={"type": "object"},
            )
        # Will fail min_length check
        assert "string" in str(exc_info.value).lower() or "length" in str(exc_info.value).lower()


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
        # Create a schema larger than 1MB
        large_value = "x" * 100_000
        large_schema = {
            f"field_{i}": {"type": "string", "description": large_value} for i in range(15)
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1.0.0",
                schema=large_schema,
            )
        assert "too large" in str(exc_info.value).lower()

    def test_invalid_schema_too_many_properties(self) -> None:
        """Invalid schema with too many properties."""
        # Create a schema with more than settings.max_schema_properties
        too_many_props = {
            f"field_{i}": {"type": "string"} for i in range(settings.max_schema_properties + 1)
        }

        with pytest.raises(ValidationError) as exc_info:
            ContractCreate(
                version="1.0.0",
                schema={"type": "object", "properties": too_many_props},
            )
        assert "too many properties" in str(exc_info.value).lower()


class TestTeamNameValidation:
    """Tests for team name validation."""

    def test_valid_simple_name(self) -> None:
        """Valid simple team name."""
        team = TeamCreate(name="analytics")
        assert team.name == "analytics"

    def test_valid_name_with_spaces(self) -> None:
        """Valid team name with spaces."""
        team = TeamCreate(name="Data Engineering")
        assert team.name == "Data Engineering"

    def test_valid_name_with_hyphens(self) -> None:
        """Valid team name with hyphens."""
        team = TeamCreate(name="data-platform")
        assert team.name == "data-platform"

    def test_valid_name_with_underscores(self) -> None:
        """Valid team name with underscores."""
        team = TeamCreate(name="data_platform")
        assert team.name == "data_platform"

    def test_valid_name_with_numbers(self) -> None:
        """Valid team name with numbers."""
        team = TeamCreate(name="team123")
        assert team.name == "team123"

    def test_valid_single_char_name(self) -> None:
        """Valid single character name."""
        team = TeamCreate(name="A")
        assert team.name == "A"

    def test_name_strips_whitespace(self) -> None:
        """Name is stripped of leading/trailing whitespace."""
        team = TeamCreate(name="  analytics  ")
        assert team.name == "analytics"

    def test_invalid_name_empty(self) -> None:
        """Invalid empty team name."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name="")
        # Pydantic min_length validation triggers before our custom validator
        assert "character" in str(exc_info.value).lower() or "short" in str(exc_info.value).lower()

    def test_invalid_name_whitespace_only(self) -> None:
        """Invalid whitespace-only team name."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name="   ")
        assert "empty" in str(exc_info.value).lower() or "whitespace" in str(exc_info.value).lower()

    def test_invalid_name_starts_with_special_char(self) -> None:
        """Invalid name starting with special character."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name="-analytics")
        assert (
            "start" in str(exc_info.value).lower() or "alphanumeric" in str(exc_info.value).lower()
        )

    def test_invalid_name_ends_with_special_char(self) -> None:
        """Invalid name ending with special character."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name="analytics-")
        assert "end" in str(exc_info.value).lower() or "alphanumeric" in str(exc_info.value).lower()

    def test_invalid_name_with_special_chars(self) -> None:
        """Invalid name with disallowed special characters."""
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name="analytics@team")
        assert "alphanumeric" in str(exc_info.value).lower()

    def test_name_too_long(self) -> None:
        """Name exceeds maximum length."""
        long_name = "a" * 256
        with pytest.raises(ValidationError) as exc_info:
            TeamCreate(name=long_name)
        assert "255" in str(exc_info.value) or "max_length" in str(exc_info.value)
