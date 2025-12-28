"""Avro schema validation.

Validates that a dict is a valid Avro schema using fastavro if available,
or basic structural validation otherwise.
"""

from typing import Any

# Try to import fastavro for full validation
try:
    from fastavro.schema import parse_schema  # type: ignore[import-not-found]

    FASTAVRO_AVAILABLE = True
except ImportError:
    FASTAVRO_AVAILABLE = False
    parse_schema = None  # type: ignore[assignment, misc]


class AvroValidationError(Exception):
    """Raised when an Avro schema is invalid."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.message = message
        self.path = path
        super().__init__(message)


# Valid Avro primitive types
AVRO_PRIMITIVE_TYPES = {"null", "boolean", "int", "long", "float", "double", "bytes", "string"}

# Valid Avro complex types
AVRO_COMPLEX_TYPES = {"record", "enum", "array", "map", "fixed"}


def _validate_basic(schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Basic structural validation of Avro schema.

    Used when fastavro is not installed.
    """
    errors: list[str] = []

    if not isinstance(schema, dict):
        return False, ["Avro schema must be an object"]

    schema_type = schema.get("type")

    if schema_type is None:
        # Could be a union (list) or named type reference (string)
        # For top-level, require type
        errors.append("Schema must have a 'type' field")
        return False, errors

    # Check type is valid
    if schema_type not in AVRO_PRIMITIVE_TYPES and schema_type not in AVRO_COMPLEX_TYPES:
        errors.append(f"Unknown Avro type: {schema_type}")

    # Record-specific validation
    if schema_type == "record":
        if "name" not in schema:
            errors.append("Record must have a 'name' field")
        if "fields" not in schema:
            errors.append("Record must have a 'fields' field")
        elif not isinstance(schema["fields"], list):
            errors.append("Record 'fields' must be an array")
        else:
            for i, field in enumerate(schema["fields"]):
                if not isinstance(field, dict):
                    errors.append(f"Field {i} must be an object")
                    continue
                if "name" not in field:
                    errors.append(f"Field {i} must have a 'name'")
                if "type" not in field:
                    errors.append(f"Field {i} must have a 'type'")

    # Enum-specific validation
    elif schema_type == "enum":
        if "name" not in schema:
            errors.append("Enum must have a 'name' field")
        if "symbols" not in schema:
            errors.append("Enum must have a 'symbols' field")
        elif not isinstance(schema["symbols"], list):
            errors.append("Enum 'symbols' must be an array")
        elif not all(isinstance(s, str) for s in schema["symbols"]):
            errors.append("Enum symbols must be strings")

    # Array-specific validation
    elif schema_type == "array":
        if "items" not in schema:
            errors.append("Array must have an 'items' field")

    # Map-specific validation
    elif schema_type == "map":
        if "values" not in schema:
            errors.append("Map must have a 'values' field")

    # Fixed-specific validation
    elif schema_type == "fixed":
        if "name" not in schema:
            errors.append("Fixed must have a 'name' field")
        if "size" not in schema:
            errors.append("Fixed must have a 'size' field")
        elif not isinstance(schema["size"], int) or schema["size"] < 0:
            errors.append("Fixed 'size' must be a non-negative integer")

    return len(errors) == 0, errors


def validate_avro_schema(schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate that a dict is a valid Avro schema.

    Uses fastavro for full validation if available, otherwise falls back
    to basic structural validation.

    Args:
        schema: The schema dict to validate

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    if not isinstance(schema, dict):
        return False, ["Avro schema must be an object"]

    # First run basic validation to catch structural issues that fastavro may be lenient about
    # (e.g., fastavro accepts record without 'fields' but Avro spec requires it)
    is_basic_valid, basic_errors = _validate_basic(schema)
    if not is_basic_valid:
        return False, basic_errors

    # Use fastavro for additional validation if available
    if FASTAVRO_AVAILABLE and parse_schema is not None:
        try:
            parse_schema(schema)
            return True, []
        except Exception as e:
            return False, [str(e)]

    return True, []


def validate_avro_schema_or_raise(schema: dict[str, Any]) -> None:
    """Validate an Avro schema and raise AvroValidationError if invalid.

    Args:
        schema: The schema dict to validate

    Raises:
        AvroValidationError: If the schema is invalid
    """
    is_valid, errors = validate_avro_schema(schema)
    if not is_valid:
        raise AvroValidationError(
            message=f"Invalid Avro schema: {'; '.join(errors)}",
            path=errors[0].split(":")[0] if errors else None,
        )
