"""Avro to JSON Schema converter.

Converts Avro schemas to JSON Schema format for storage and compatibility checking.
This is a one-way conversion used at contract publish time.
"""

from typing import Any


class AvroConversionError(Exception):
    """Raised when Avro schema conversion fails."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.message = message
        self.path = path
        super().__init__(message)


# Avro primitive type to JSON Schema mapping
AVRO_PRIMITIVE_TO_JSON_SCHEMA: dict[str, dict[str, Any]] = {
    "null": {"type": "null"},
    "boolean": {"type": "boolean"},
    "int": {"type": "integer"},
    "long": {"type": "integer"},
    "float": {"type": "number"},
    "double": {"type": "number"},
    "bytes": {"type": "string", "contentEncoding": "base64"},
    "string": {"type": "string"},
}


def is_avro_schema(schema: dict[str, Any]) -> bool:
    """Detect if a schema is an Avro schema.

    Avro schemas have distinctive markers:
    - type: "record" with name and fields
    - Avro primitive types as strings
    """
    if not isinstance(schema, dict):
        return False

    # Record type is the most common Avro schema
    if schema.get("type") == "record" and "fields" in schema:
        return True

    # Check for Avro-specific field structure
    schema_type = schema.get("type")
    if schema_type in AVRO_PRIMITIVE_TO_JSON_SCHEMA:
        return True

    return False


def _convert_type(
    avro_type: str | list[Any] | dict[str, Any],
    path: str = "",
    named_types: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert an Avro type to JSON Schema.

    Args:
        avro_type: The Avro type (primitive string, union list, or complex dict)
        path: Current path for error messages
        named_types: Registry of named types (records, enums, fixed) for references

    Returns:
        JSON Schema dict
    """
    if named_types is None:
        named_types = {}

    # Primitive type as string
    if isinstance(avro_type, str):
        if avro_type in AVRO_PRIMITIVE_TO_JSON_SCHEMA:
            return AVRO_PRIMITIVE_TO_JSON_SCHEMA[avro_type].copy()
        # Named type reference
        if avro_type in named_types:
            return named_types[avro_type].copy()
        # Qualified name reference (namespace.name)
        for name, schema in named_types.items():
            if name.endswith(f".{avro_type}") or avro_type.endswith(f".{name}"):
                return schema.copy()
        raise AvroConversionError(f"Unknown Avro type: {avro_type}", path)

    # Union type (array of types)
    if isinstance(avro_type, list):
        return _convert_union(avro_type, path, named_types)

    # Complex type (dict)
    if isinstance(avro_type, dict):
        return _convert_complex_type(avro_type, path, named_types)

    raise AvroConversionError(f"Invalid Avro type: {avro_type}", path)


def _convert_union(
    union_types: list[Any],
    path: str,
    named_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert an Avro union type to JSON Schema.

    Avro unions are arrays like ["null", "string"] for nullable string.
    """
    if not union_types:
        raise AvroConversionError("Empty union type", path)

    # Check if it's a nullable type (["null", T] or [T, "null"])
    null_count = sum(1 for t in union_types if t == "null")
    non_null_types = [t for t in union_types if t != "null"]

    if null_count == 1 and len(non_null_types) == 1:
        # Simple nullable type - convert the non-null type
        converted = _convert_type(non_null_types[0], path, named_types)
        # Mark as nullable by allowing null in anyOf
        return {"anyOf": [{"type": "null"}, converted]}

    # Multi-type union - convert all to anyOf
    converted_types = [
        _convert_type(t, f"{path}[{i}]", named_types) for i, t in enumerate(union_types)
    ]
    return {"anyOf": converted_types}


def _convert_complex_type(
    avro_type: dict[str, Any],
    path: str,
    named_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert an Avro complex type to JSON Schema."""
    type_name = avro_type.get("type")

    if type_name == "record":
        return _convert_record(avro_type, path, named_types)
    elif type_name == "enum":
        return _convert_enum(avro_type, path)
    elif type_name == "array":
        return _convert_array(avro_type, path, named_types)
    elif type_name == "map":
        return _convert_map(avro_type, path, named_types)
    elif type_name == "fixed":
        return _convert_fixed(avro_type, path)
    elif type_name in AVRO_PRIMITIVE_TO_JSON_SCHEMA:
        # Primitive type with logical type annotation
        result = AVRO_PRIMITIVE_TO_JSON_SCHEMA[type_name].copy()
        # Handle logical types
        logical_type = avro_type.get("logicalType")
        if logical_type:
            result = _apply_logical_type(result, logical_type, avro_type)
        return result
    else:
        raise AvroConversionError(f"Unknown Avro complex type: {type_name}", path)


def _convert_record(
    avro_type: dict[str, Any],
    path: str,
    named_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert an Avro record to JSON Schema object."""
    name = avro_type.get("name", "")
    namespace = avro_type.get("namespace", "")
    full_name = f"{namespace}.{name}" if namespace else name

    # Register this record type for forward references
    # Use a placeholder first to handle recursive types
    named_types[full_name] = {"$ref": f"#/$defs/{full_name}"}
    if name and name != full_name:
        named_types[name] = {"$ref": f"#/$defs/{full_name}"}

    fields = avro_type.get("fields", [])
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type")
        field_path = f"{path}.{field_name}" if path else field_name

        if field_type is None:
            raise AvroConversionError(f"Field '{field_name}' has no type", field_path)

        # Check if field is nullable (union with null)
        is_nullable = False
        if isinstance(field_type, list):
            is_nullable = "null" in field_type

        # Convert the field type
        converted = _convert_type(field_type, field_path, named_types)
        properties[field_name] = converted

        # Handle default values
        if "default" in field:
            properties[field_name]["default"] = field["default"]

        # Field is required unless it's nullable or has a default
        if not is_nullable and "default" not in field:
            required.append(field_name)

        # Add description from doc
        if "doc" in field:
            properties[field_name]["description"] = field["doc"]

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }

    if required:
        result["required"] = required

    # Add description from record doc
    if "doc" in avro_type:
        result["description"] = avro_type["doc"]

    return result


def _convert_enum(avro_type: dict[str, Any], path: str) -> dict[str, Any]:
    """Convert an Avro enum to JSON Schema."""
    symbols = avro_type.get("symbols", [])
    if not symbols:
        raise AvroConversionError("Enum has no symbols", path)

    result: dict[str, Any] = {
        "type": "string",
        "enum": symbols,
    }

    if "doc" in avro_type:
        result["description"] = avro_type["doc"]

    if "default" in avro_type:
        result["default"] = avro_type["default"]

    return result


def _convert_array(
    avro_type: dict[str, Any],
    path: str,
    named_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert an Avro array to JSON Schema."""
    items = avro_type.get("items")
    if items is None:
        raise AvroConversionError("Array has no items type", path)

    return {
        "type": "array",
        "items": _convert_type(items, f"{path}.items", named_types),
    }


def _convert_map(
    avro_type: dict[str, Any],
    path: str,
    named_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert an Avro map to JSON Schema."""
    values = avro_type.get("values")
    if values is None:
        raise AvroConversionError("Map has no values type", path)

    return {
        "type": "object",
        "additionalProperties": _convert_type(values, f"{path}.values", named_types),
    }


def _convert_fixed(avro_type: dict[str, Any], path: str) -> dict[str, Any]:
    """Convert an Avro fixed to JSON Schema."""
    size = avro_type.get("size")
    if size is None:
        raise AvroConversionError("Fixed has no size", path)

    # Fixed is binary data of exact size, represent as base64 string
    return {
        "type": "string",
        "contentEncoding": "base64",
        "minLength": size,
        "maxLength": size,
    }


def _apply_logical_type(
    base_schema: dict[str, Any],
    logical_type: str,
    avro_type: dict[str, Any],
) -> dict[str, Any]:
    """Apply Avro logical type to JSON Schema."""
    result = base_schema.copy()

    # Date/time logical types
    if logical_type == "date":
        result["format"] = "date"
    elif logical_type == "time-millis" or logical_type == "time-micros":
        result["format"] = "time"
    elif logical_type == "timestamp-millis" or logical_type == "timestamp-micros":
        result["format"] = "date-time"
    elif logical_type == "local-timestamp-millis" or logical_type == "local-timestamp-micros":
        result["format"] = "date-time"
    elif logical_type == "uuid":
        result["format"] = "uuid"
    elif logical_type == "decimal":
        # Decimal with precision and scale
        result["type"] = "string"
        result["pattern"] = r"^-?\d+(\.\d+)?$"
        if "precision" in avro_type:
            result["x-avro-precision"] = avro_type["precision"]
        if "scale" in avro_type:
            result["x-avro-scale"] = avro_type["scale"]
    elif logical_type == "duration":
        result["format"] = "duration"

    return result


def avro_to_json_schema(avro_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert an Avro schema to JSON Schema.

    Args:
        avro_schema: Valid Avro schema dict

    Returns:
        Equivalent JSON Schema dict

    Raises:
        AvroConversionError: If conversion fails

    Example:
        >>> avro = {
        ...     "type": "record",
        ...     "name": "User",
        ...     "fields": [
        ...         {"name": "id", "type": "long"},
        ...         {"name": "email", "type": "string"},
        ...         {"name": "name", "type": ["null", "string"], "default": None}
        ...     ]
        ... }
        >>> json_schema = avro_to_json_schema(avro)
        >>> json_schema["type"]
        'object'
        >>> "id" in json_schema["properties"]
        True
    """
    if not isinstance(avro_schema, dict):
        raise AvroConversionError("Avro schema must be a dict")

    named_types: dict[str, dict[str, Any]] = {}

    schema_type = avro_schema.get("type")

    # Handle record (most common case)
    if schema_type == "record":
        return _convert_record(avro_schema, "", named_types)

    # Handle other types
    return _convert_type(avro_schema, "", named_types)
