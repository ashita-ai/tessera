"""Tests for dbt type mapper: format keywords and required field inference."""

import pytest

from tessera.api.sync.dbt.mapper import (
    dbt_columns_to_json_schema,
    not_null_columns_from_guarantees,
)


class TestDateTimeFormats:
    """Date/time types must include the JSON Schema ``format`` keyword."""

    @pytest.mark.parametrize(
        ("dbt_type", "expected_format"),
        [
            ("date", "date"),
            ("DATE", "date"),
            ("datetime", "date-time"),
            ("timestamp", "date-time"),
            ("TIMESTAMP", "date-time"),
            ("timestamp_ntz", "date-time"),
            ("timestamp_tz", "date-time"),
            ("time", "time"),
            ("TIME", "time"),
        ],
    )
    def test_format_keyword_present(self, dbt_type: str, expected_format: str) -> None:
        columns = {"col": {"data_type": dbt_type}}
        schema = dbt_columns_to_json_schema(columns)
        prop = schema["properties"]["col"]
        assert prop["type"] == "string"
        assert prop["format"] == expected_format

    def test_non_temporal_types_have_no_format(self) -> None:
        columns = {
            "name": {"data_type": "varchar"},
            "age": {"data_type": "integer"},
            "score": {"data_type": "float"},
            "active": {"data_type": "boolean"},
        }
        schema = dbt_columns_to_json_schema(columns)
        for col_name in columns:
            assert "format" not in schema["properties"][col_name]

    def test_timestamp_with_precision_suffix(self) -> None:
        """``timestamp(6)`` should strip the parenthetical and still get a format."""
        columns = {"created_at": {"data_type": "timestamp(6)"}}
        schema = dbt_columns_to_json_schema(columns)
        prop = schema["properties"]["created_at"]
        assert prop == {"type": "string", "format": "date-time"}


class TestRequiredFromNotNull:
    """Columns with not_null guarantees should appear in the schema's ``required`` array."""

    def test_not_null_columns_populate_required(self) -> None:
        columns = {
            "id": {"data_type": "integer"},
            "email": {"data_type": "varchar"},
            "nickname": {"data_type": "varchar"},
        }
        schema = dbt_columns_to_json_schema(columns, not_null_columns={"id", "email"})
        assert sorted(schema["required"]) == ["email", "id"]

    def test_no_not_null_columns_means_empty_required(self) -> None:
        columns = {"id": {"data_type": "integer"}}
        schema = dbt_columns_to_json_schema(columns)
        assert schema["required"] == []

    def test_not_null_columns_none_means_empty_required(self) -> None:
        columns = {"id": {"data_type": "integer"}}
        schema = dbt_columns_to_json_schema(columns, not_null_columns=None)
        assert schema["required"] == []

    def test_not_null_column_not_in_columns_is_ignored(self) -> None:
        """A not_null column that doesn't exist in the columns dict is silently skipped."""
        columns = {"id": {"data_type": "integer"}}
        schema = dbt_columns_to_json_schema(columns, not_null_columns={"id", "ghost_column"})
        assert schema["required"] == ["id"]


class TestNotNullColumnsFromGuarantees:
    """Extraction of not_null column names from the guarantees dict."""

    def test_extracts_never_nullability(self) -> None:
        guarantees = {"nullability": {"id": "never", "email": "never"}}
        assert not_null_columns_from_guarantees(guarantees) == {"id", "email"}

    def test_ignores_non_never_values(self) -> None:
        guarantees = {"nullability": {"id": "never", "notes": "sometimes"}}
        result = not_null_columns_from_guarantees(guarantees)
        assert result == {"id"}
        assert "notes" not in result

    def test_none_guarantees(self) -> None:
        assert not_null_columns_from_guarantees(None) == set()

    def test_empty_guarantees(self) -> None:
        assert not_null_columns_from_guarantees({}) == set()

    def test_guarantees_without_nullability(self) -> None:
        guarantees = {"custom": [{"type": "unique", "column": "id"}]}
        assert not_null_columns_from_guarantees(guarantees) == set()


class TestSchemaStructure:
    """General schema structure tests."""

    def test_empty_columns(self) -> None:
        schema = dbt_columns_to_json_schema({})
        assert schema == {"type": "object", "properties": {}, "required": []}

    def test_description_preserved(self) -> None:
        columns = {"id": {"data_type": "integer", "description": "Primary key"}}
        schema = dbt_columns_to_json_schema(columns)
        assert schema["properties"]["id"]["description"] == "Primary key"

    def test_missing_data_type_defaults_to_string(self) -> None:
        columns = {"mystery": {}}
        schema = dbt_columns_to_json_schema(columns)
        assert schema["properties"]["mystery"]["type"] == "string"

    def test_unknown_type_defaults_to_string(self) -> None:
        columns = {"geo": {"data_type": "geography"}}
        schema = dbt_columns_to_json_schema(columns)
        assert schema["properties"]["geo"]["type"] == "string"

    def test_combined_format_and_required(self) -> None:
        """A timestamp column with not_null should have both format and required."""
        columns = {
            "created_at": {"data_type": "timestamp"},
            "updated_at": {"data_type": "timestamp"},
            "deleted_at": {"data_type": "timestamp"},
        }
        schema = dbt_columns_to_json_schema(columns, not_null_columns={"created_at", "updated_at"})
        assert schema["properties"]["created_at"] == {
            "type": "string",
            "format": "date-time",
        }
        assert sorted(schema["required"]) == ["created_at", "updated_at"]
        assert "deleted_at" not in schema["required"]
