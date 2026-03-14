"""Contract models."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.config import settings
from tessera.models.enums import ChangeType, CompatibilityMode, ContractStatus, SchemaFormat


class Guarantees(BaseModel):
    """Contract guarantees beyond schema."""

    freshness: dict[str, Any] | None = Field(
        None,
        description="Freshness requirements (e.g., max_staleness_minutes, measured_by)",
    )
    volume: dict[str, Any] | None = Field(
        None,
        description="Volume requirements (e.g., min_rows, max_row_delta_pct)",
    )
    nullability: dict[str, str] | None = Field(
        None,
        description="Column nullability requirements (e.g., {'customer_id': 'never'})",
    )
    accepted_values: dict[str, list[str]] | None = Field(
        None,
        description="Accepted values per column (e.g., {'status': ['active', 'churned']})",
    )


def _count_all_properties(schema: dict[str, Any]) -> int:
    """Count total properties across all nesting levels.

    Uses an iterative (stack-based) traversal to avoid ``RecursionError``
    on deeply nested schemas.  Counts properties within objects and within
    array items so that deeply nested schemas with many leaf properties are
    correctly measured against ``settings.max_schema_properties``.
    """
    count = 0
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "object" and "properties" in node:
            props: dict[str, Any] = node["properties"]
            count += len(props)
            stack.extend(props.values())
        if "items" in node:
            stack.append(node["items"])
    return count


def _max_nesting_depth(schema: dict[str, Any]) -> int:
    """Return the maximum object-nesting depth in *schema*.

    Uses an iterative (stack-based) traversal to avoid ``RecursionError``
    on deeply nested schemas.  Only object types with ``properties`` advance
    the depth counter, so arrays and scalar sub-schemas don't inflate the
    count.
    """
    max_depth = 0
    # Stack entries: (node, current_depth)
    stack: list[tuple[Any, int]] = [(schema, 0)]
    while stack:
        node, current = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "object" and "properties" in node:
            child_depth = current + 1
            if child_depth > max_depth:
                max_depth = child_depth
            for prop_schema in node["properties"].values():
                stack.append((prop_schema, child_depth))
        if "items" in node:
            stack.append((node["items"], current))
    return max_depth


class ContractBase(BaseModel):
    """Base contract fields."""

    version: str | None = Field(
        None,
        min_length=5,  # Minimum: "0.0.0"
        max_length=50,
        pattern=r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$",
        description="Semantic version (e.g., '1.0.0'). Auto-incremented if not provided.",
    )
    schema_def: dict[str, Any] = Field(..., alias="schema", description="JSON Schema definition")
    schema_format: SchemaFormat = Field(
        SchemaFormat.JSON_SCHEMA,
        description="Schema format: 'json_schema' (default) or 'avro'. Avro schemas are "
        "validated and converted to JSON Schema for storage.",
    )
    compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD
    guarantees: Guarantees | None = None

    @field_validator("schema_def")
    @classmethod
    def validate_schema_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate schema size and property count to prevent DoS attacks."""
        # 1. Check byte size
        serialized = json.dumps(v, separators=(",", ":"))
        if len(serialized) > settings.max_schema_size_bytes:
            raise ValueError(
                f"Schema too large. Maximum size: {settings.max_schema_size_bytes:,} bytes "
                f"({settings.max_schema_size_bytes // 1024 // 1024}MB). "
                f"Current size: {len(serialized):,} bytes."
            )

        # 2. Check total property count across all nesting levels
        total_props = _count_all_properties(v)
        if total_props > settings.max_schema_properties:
            raise ValueError(
                f"Too many properties in schema (including nested). "
                f"Maximum: {settings.max_schema_properties}. Found: {total_props}."
            )

        # 3. Check nesting depth
        depth = _max_nesting_depth(v)
        if depth > settings.max_schema_nesting_depth:
            raise ValueError(
                f"Schema nesting too deep. "
                f"Maximum depth: {settings.max_schema_nesting_depth}. Found: {depth}."
            )

        return v


class ContractCreate(ContractBase):
    """Fields for creating a contract."""

    field_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Map of JSON path -> human-readable description",
    )
    field_tags: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of JSON path -> list of tags",
    )


class Contract(ContractBase):
    """Contract entity."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    asset_id: UUID
    version: str = Field(..., description="Semantic version")  # Required for stored contracts
    schema_format: SchemaFormat = Field(
        SchemaFormat.JSON_SCHEMA,
        description="Original schema format submitted (json_schema or avro).",
    )
    field_descriptions: dict[str, str] = Field(default_factory=dict)
    field_tags: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("field_descriptions", mode="before")
    @classmethod
    def coerce_field_descriptions_none(cls, v: Any) -> dict[str, str]:
        """Coerce None to empty dict."""
        if v is None:
            return {}
        return dict(v)

    @field_validator("field_tags", mode="before")
    @classmethod
    def coerce_field_tags_none(cls, v: Any) -> dict[str, list[str]]:
        """Coerce None to empty dict."""
        if v is None:
            return {}
        return dict(v)

    status: ContractStatus = ContractStatus.ACTIVE
    published_at: datetime
    published_by: UUID
    published_by_user_id: UUID | None = None
    updated_at: datetime | None = None


class VersionSuggestionRequest(BaseModel):
    """Request body for previewing version suggestion without publishing."""

    schema_def: dict[str, Any] = Field(..., alias="schema", description="JSON Schema definition")
    schema_format: SchemaFormat = Field(
        SchemaFormat.JSON_SCHEMA,
        description="Schema format: 'json_schema' (default) or 'avro'",
    )


class VersionSuggestion(BaseModel):
    """Suggested version based on schema diff analysis.

    Returned when asset.semver_mode is 'suggest' and no version is provided,
    or included in validation errors when semver_mode is 'enforce'.
    """

    suggested_version: str = Field(
        ..., description="The suggested semantic version based on schema changes"
    )
    current_version: str | None = Field(
        None, description="The current contract version (None for first contract)"
    )
    change_type: ChangeType = Field(
        ..., description="The detected change type (major, minor, patch)"
    )
    reason: str = Field(
        ..., description="Human-readable explanation of why this version was suggested"
    )
    is_first_contract: bool = Field(
        False, description="True if this is the first contract for the asset"
    )
    breaking_changes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of breaking changes detected in the schema diff",
    )
