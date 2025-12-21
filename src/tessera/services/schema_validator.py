"""JSON Schema validation service."""

from typing import Any

from jsonschema import Draft7Validator


class SchemaValidationError(Exception):
    """Raised when a schema is invalid."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.message = message
        self.path = path
        super().__init__(message)


def validate_json_schema(schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate that a dict is a valid JSON Schema (Draft 7).

    Args:
        schema: The schema dict to validate

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors: list[str] = []

    # Check that schema is a dict
    if not isinstance(schema, dict):
        return False, ["Schema must be an object"]

    # Validate against JSON Schema Draft 7 meta-schema
    validator = Draft7Validator(Draft7Validator.META_SCHEMA)

    for error in validator.iter_errors(schema):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")

    return len(errors) == 0, errors


def validate_schema_or_raise(schema: dict[str, Any]) -> None:
    """Validate a schema and raise SchemaValidationError if invalid.

    Args:
        schema: The schema dict to validate

    Raises:
        SchemaValidationError: If the schema is invalid
    """
    is_valid, errors = validate_json_schema(schema)
    if not is_valid:
        raise SchemaValidationError(
            message=f"Invalid JSON Schema: {'; '.join(errors)}",
            path=errors[0].split(":")[0] if errors else None,
        )


def check_schema_validity(schema: dict[str, Any]) -> dict[str, Any]:
    """Check schema validity and return structured result.

    Args:
        schema: The schema dict to validate

    Returns:
        Dict with 'valid' boolean and 'errors' list
    """
    is_valid, errors = validate_json_schema(schema)
    return {
        "valid": is_valid,
        "errors": errors,
    }
