"""Avro schema support for Tessera.

This module provides conversion between Avro schemas and JSON Schema,
enabling Tessera to accept Avro schemas for contract publishing while
internally using JSON Schema for storage and compatibility checking.
"""

from tessera.services.avro.converter import (
    AvroConversionError,
    avro_to_json_schema,
    is_avro_schema,
)
from tessera.services.avro.validator import (
    AvroValidationError,
    validate_avro_schema,
)

__all__ = [
    "AvroConversionError",
    "AvroValidationError",
    "avro_to_json_schema",
    "is_avro_schema",
    "validate_avro_schema",
]
