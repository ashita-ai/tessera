"""Tests for Avro schema support."""

import pytest

from tessera.services.avro import (
    AvroConversionError,
    avro_to_json_schema,
    is_avro_schema,
    validate_avro_schema,
)


class TestAvroDetection:
    """Tests for is_avro_schema detection."""

    def test_detects_avro_record(self) -> None:
        """Avro record schema is detected."""
        schema = {
            "type": "record",
            "name": "User",
            "fields": [{"name": "id", "type": "long"}],
        }
        assert is_avro_schema(schema) is True

    def test_detects_avro_primitive(self) -> None:
        """Avro primitive types are detected."""
        assert is_avro_schema({"type": "string"}) is True
        assert is_avro_schema({"type": "long"}) is True
        assert is_avro_schema({"type": "boolean"}) is True

    def test_rejects_json_schema(self) -> None:
        """JSON Schema is not detected as Avro."""
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
        }
        assert is_avro_schema(schema) is False

    def test_rejects_non_dict(self) -> None:
        """Non-dict input returns False."""
        assert is_avro_schema("string") is False  # type: ignore[arg-type]
        assert is_avro_schema(None) is False  # type: ignore[arg-type]


class TestAvroValidation:
    """Tests for validate_avro_schema."""

    def test_valid_record(self) -> None:
        """Valid record schema passes validation."""
        schema = {
            "type": "record",
            "name": "User",
            "fields": [
                {"name": "id", "type": "long"},
                {"name": "email", "type": "string"},
            ],
        }
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is True
        assert errors == []

    def test_missing_type(self) -> None:
        """Schema without type field fails."""
        schema = {"name": "User", "fields": []}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False
        assert len(errors) > 0

    def test_record_missing_name(self) -> None:
        """Record without name fails."""
        schema = {"type": "record", "fields": []}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_record_missing_fields(self) -> None:
        """Record without fields fails."""
        schema = {"type": "record", "name": "User"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_enum_valid(self) -> None:
        """Valid enum passes validation."""
        schema = {
            "type": "enum",
            "name": "Status",
            "symbols": ["ACTIVE", "INACTIVE"],
        }
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is True

    def test_enum_missing_symbols(self) -> None:
        """Enum without symbols fails."""
        schema = {"type": "enum", "name": "Status"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_array_valid(self) -> None:
        """Valid array passes validation."""
        schema = {"type": "array", "items": "string"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is True

    def test_array_missing_items(self) -> None:
        """Array without items fails."""
        schema = {"type": "array"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_map_valid(self) -> None:
        """Valid map passes validation."""
        schema = {"type": "map", "values": "long"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is True

    def test_map_missing_values(self) -> None:
        """Map without values fails."""
        schema = {"type": "map"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_fixed_valid(self) -> None:
        """Valid fixed passes validation."""
        schema = {"type": "fixed", "name": "Hash", "size": 16}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is True

    def test_fixed_missing_size(self) -> None:
        """Fixed without size fails."""
        schema = {"type": "fixed", "name": "Hash"}
        is_valid, errors = validate_avro_schema(schema)
        assert is_valid is False

    def test_non_dict_fails(self) -> None:
        """Non-dict input fails validation."""
        is_valid, errors = validate_avro_schema("not a dict")  # type: ignore[arg-type]
        assert is_valid is False


class TestAvroToJsonSchemaConversion:
    """Tests for avro_to_json_schema conversion."""

    def test_simple_record(self) -> None:
        """Convert simple record to JSON Schema object."""
        avro = {
            "type": "record",
            "name": "User",
            "fields": [
                {"name": "id", "type": "long"},
                {"name": "email", "type": "string"},
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["type"] == "object"
        assert "properties" in result
        assert result["properties"]["id"]["type"] == "integer"
        assert result["properties"]["email"]["type"] == "string"
        assert "id" in result["required"]
        assert "email" in result["required"]

    def test_nullable_field(self) -> None:
        """Nullable fields are converted to anyOf with null."""
        avro = {
            "type": "record",
            "name": "User",
            "fields": [
                {"name": "id", "type": "long"},
                {"name": "nickname", "type": ["null", "string"]},
            ],
        }
        result = avro_to_json_schema(avro)

        # Nullable field should not be required
        assert "nickname" not in result.get("required", [])
        # Should have anyOf with null
        assert "anyOf" in result["properties"]["nickname"]
        any_of_types = [t.get("type") for t in result["properties"]["nickname"]["anyOf"]]
        assert "null" in any_of_types
        assert "string" in any_of_types

    def test_field_with_default(self) -> None:
        """Fields with defaults are not required."""
        avro = {
            "type": "record",
            "name": "Config",
            "fields": [
                {"name": "timeout", "type": "int", "default": 30},
            ],
        }
        result = avro_to_json_schema(avro)

        # Field with default should not be required
        assert "timeout" not in result.get("required", [])
        # Should have default value
        assert result["properties"]["timeout"]["default"] == 30

    def test_nested_record(self) -> None:
        """Nested records are converted properly."""
        avro = {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "long"},
                {
                    "name": "customer",
                    "type": {
                        "type": "record",
                        "name": "Customer",
                        "fields": [
                            {"name": "name", "type": "string"},
                        ],
                    },
                },
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["properties"]["customer"]["type"] == "object"
        assert "name" in result["properties"]["customer"]["properties"]

    def test_enum_conversion(self) -> None:
        """Enum is converted to string with enum constraint."""
        avro = {
            "type": "record",
            "name": "User",
            "fields": [
                {
                    "name": "status",
                    "type": {
                        "type": "enum",
                        "name": "Status",
                        "symbols": ["ACTIVE", "INACTIVE", "PENDING"],
                    },
                },
            ],
        }
        result = avro_to_json_schema(avro)

        status = result["properties"]["status"]
        assert status["type"] == "string"
        assert status["enum"] == ["ACTIVE", "INACTIVE", "PENDING"]

    def test_array_conversion(self) -> None:
        """Array is converted to JSON Schema array."""
        avro = {
            "type": "record",
            "name": "User",
            "fields": [
                {"name": "tags", "type": {"type": "array", "items": "string"}},
            ],
        }
        result = avro_to_json_schema(avro)

        tags = result["properties"]["tags"]
        assert tags["type"] == "array"
        assert tags["items"]["type"] == "string"

    def test_map_conversion(self) -> None:
        """Map is converted to object with additionalProperties."""
        avro = {
            "type": "record",
            "name": "Config",
            "fields": [
                {"name": "settings", "type": {"type": "map", "values": "string"}},
            ],
        }
        result = avro_to_json_schema(avro)

        settings = result["properties"]["settings"]
        assert settings["type"] == "object"
        assert settings["additionalProperties"]["type"] == "string"

    def test_fixed_conversion(self) -> None:
        """Fixed is converted to base64-encoded string."""
        avro = {
            "type": "record",
            "name": "Record",
            "fields": [
                {"name": "hash", "type": {"type": "fixed", "name": "MD5", "size": 16}},
            ],
        }
        result = avro_to_json_schema(avro)

        hash_field = result["properties"]["hash"]
        assert hash_field["type"] == "string"
        assert hash_field["contentEncoding"] == "base64"
        assert hash_field["minLength"] == 16
        assert hash_field["maxLength"] == 16

    def test_primitive_types(self) -> None:
        """All Avro primitive types are converted correctly."""
        avro = {
            "type": "record",
            "name": "Primitives",
            "fields": [
                {"name": "null_field", "type": "null"},
                {"name": "bool_field", "type": "boolean"},
                {"name": "int_field", "type": "int"},
                {"name": "long_field", "type": "long"},
                {"name": "float_field", "type": "float"},
                {"name": "double_field", "type": "double"},
                {"name": "bytes_field", "type": "bytes"},
                {"name": "string_field", "type": "string"},
            ],
        }
        result = avro_to_json_schema(avro)
        props = result["properties"]

        assert props["null_field"]["type"] == "null"
        assert props["bool_field"]["type"] == "boolean"
        assert props["int_field"]["type"] == "integer"
        assert props["long_field"]["type"] == "integer"
        assert props["float_field"]["type"] == "number"
        assert props["double_field"]["type"] == "number"
        assert props["bytes_field"]["type"] == "string"
        assert props["bytes_field"]["contentEncoding"] == "base64"
        assert props["string_field"]["type"] == "string"

    def test_logical_type_date(self) -> None:
        """Date logical type gets format annotation."""
        avro = {
            "type": "record",
            "name": "Event",
            "fields": [
                {"name": "date", "type": {"type": "int", "logicalType": "date"}},
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["properties"]["date"]["format"] == "date"

    def test_logical_type_timestamp(self) -> None:
        """Timestamp logical type gets date-time format."""
        avro = {
            "type": "record",
            "name": "Event",
            "fields": [
                {
                    "name": "created_at",
                    "type": {"type": "long", "logicalType": "timestamp-millis"},
                },
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["properties"]["created_at"]["format"] == "date-time"

    def test_logical_type_uuid(self) -> None:
        """UUID logical type gets uuid format."""
        avro = {
            "type": "record",
            "name": "Entity",
            "fields": [
                {"name": "id", "type": {"type": "string", "logicalType": "uuid"}},
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["properties"]["id"]["format"] == "uuid"

    def test_doc_becomes_description(self) -> None:
        """Avro doc fields become JSON Schema descriptions."""
        avro = {
            "type": "record",
            "name": "User",
            "doc": "Represents a user in the system",
            "fields": [
                {"name": "id", "type": "long", "doc": "Unique identifier"},
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["description"] == "Represents a user in the system"
        assert result["properties"]["id"]["description"] == "Unique identifier"

    def test_non_dict_raises(self) -> None:
        """Non-dict input raises AvroConversionError."""
        with pytest.raises(AvroConversionError):
            avro_to_json_schema("not a dict")  # type: ignore[arg-type]

    def test_empty_union_raises(self) -> None:
        """Empty union type raises error."""
        avro = {
            "type": "record",
            "name": "Test",
            "fields": [{"name": "field", "type": []}],
        }
        with pytest.raises(AvroConversionError, match="Empty union"):
            avro_to_json_schema(avro)


class TestKafkaRealisticSchemas:
    """Test with realistic Kafka-style Avro schemas."""

    def test_kafka_user_event(self) -> None:
        """Convert a typical Kafka user event schema."""
        avro = {
            "type": "record",
            "name": "UserEvent",
            "namespace": "com.example.events",
            "doc": "User activity event",
            "fields": [
                {"name": "event_id", "type": {"type": "string", "logicalType": "uuid"}},
                {"name": "user_id", "type": "long"},
                {
                    "name": "event_type",
                    "type": {
                        "type": "enum",
                        "name": "EventType",
                        "symbols": ["LOGIN", "LOGOUT", "PURCHASE"],
                    },
                },
                {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
                {
                    "name": "metadata",
                    "type": ["null", {"type": "map", "values": "string"}],
                    "default": None,
                },
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["type"] == "object"
        assert result["properties"]["event_id"]["format"] == "uuid"
        assert result["properties"]["user_id"]["type"] == "integer"
        assert result["properties"]["event_type"]["enum"] == ["LOGIN", "LOGOUT", "PURCHASE"]
        assert result["properties"]["timestamp"]["format"] == "date-time"
        # metadata is nullable with default None, so not required
        assert "metadata" not in result.get("required", [])

    def test_kafka_order_schema(self) -> None:
        """Convert a typical Kafka order schema with nested types."""
        avro = {
            "type": "record",
            "name": "Order",
            "namespace": "com.example.orders",
            "fields": [
                {"name": "order_id", "type": "string"},
                {"name": "customer_id", "type": "long"},
                {
                    "name": "items",
                    "type": {
                        "type": "array",
                        "items": {
                            "type": "record",
                            "name": "OrderItem",
                            "fields": [
                                {"name": "product_id", "type": "string"},
                                {"name": "quantity", "type": "int"},
                                {
                                    "name": "unit_price",
                                    "type": {
                                        "type": "bytes",
                                        "logicalType": "decimal",
                                        "precision": 10,
                                        "scale": 2,
                                    },
                                },
                            ],
                        },
                    },
                },
                {
                    "name": "total",
                    "type": {
                        "type": "bytes",
                        "logicalType": "decimal",
                        "precision": 12,
                        "scale": 2,
                    },
                },
                {
                    "name": "status",
                    "type": {
                        "type": "enum",
                        "name": "OrderStatus",
                        "symbols": ["PENDING", "CONFIRMED", "SHIPPED", "DELIVERED"],
                    },
                },
            ],
        }
        result = avro_to_json_schema(avro)

        assert result["type"] == "object"
        assert result["properties"]["items"]["type"] == "array"
        items_schema = result["properties"]["items"]["items"]
        assert items_schema["type"] == "object"
        assert "product_id" in items_schema["properties"]
        assert result["properties"]["status"]["enum"] == [
            "PENDING",
            "CONFIRMED",
            "SHIPPED",
            "DELIVERED",
        ]
