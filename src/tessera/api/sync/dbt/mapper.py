"""Type mapping utilities for dbt-to-Tessera schema conversion."""

from typing import Any

from tessera.models.enums import ResourceType

# dbt data types → JSON Schema types
_TYPE_MAPPING: dict[str, str] = {
    # String types
    "string": "string",
    "text": "string",
    "varchar": "string",
    "char": "string",
    "character varying": "string",
    # Numeric types
    "integer": "integer",
    "int": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "int64": "integer",
    "int32": "integer",
    "number": "number",
    "numeric": "number",
    "decimal": "number",
    "float": "number",
    "double": "number",
    "real": "number",
    "float64": "number",
    # Boolean
    "boolean": "boolean",
    "bool": "boolean",
    # Date/time (represented as strings in JSON)
    "date": "string",
    "datetime": "string",
    "timestamp": "string",
    "timestamp_ntz": "string",
    "timestamp_tz": "string",
    "time": "string",
    # Other
    "json": "object",
    "jsonb": "object",
    "array": "array",
    "variant": "object",
    "object": "object",
}

_RESOURCE_TYPE_MAPPING: dict[str, ResourceType] = {
    "model": ResourceType.MODEL,
    "source": ResourceType.SOURCE,
    "seed": ResourceType.SEED,
    "snapshot": ResourceType.SNAPSHOT,
}


def map_dbt_resource_type(dbt_type: str) -> ResourceType:
    """Map dbt resource type string to ResourceType enum."""
    return _RESOURCE_TYPE_MAPPING.get(dbt_type, ResourceType.OTHER)


def dbt_columns_to_json_schema(columns: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt column definitions to JSON Schema.

    Maps dbt data types to JSON Schema types for compatibility checking.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for col_name, col_info in columns.items():
        data_type = (col_info.get("data_type") or "string").lower()
        # Extract base type (e.g., "varchar(255)" -> "varchar")
        base_type = data_type.split("(")[0].strip()

        json_type = _TYPE_MAPPING.get(base_type, "string")
        prop: dict[str, Any] = {"type": json_type}

        # Add description if present
        if col_info.get("description"):
            prop["description"] = col_info["description"]

        properties[col_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
