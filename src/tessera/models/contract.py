"""Contract models."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.config import settings
from tessera.models.enums import CompatibilityMode, ContractStatus


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

        # 2. Check property count (if object)
        if v.get("type") == "object" and "properties" in v:
            props_count = len(v["properties"])
            if props_count > settings.max_schema_properties:
                raise ValueError(
                    f"Too many properties in schema. Maximum: {settings.max_schema_properties}. "
                    f"Found: {props_count}."
                )
        return v


class ContractCreate(ContractBase):
    """Fields for creating a contract."""

    pass


class Contract(ContractBase):
    """Contract entity."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    asset_id: UUID
    version: str = Field(..., description="Semantic version")  # Required for stored contracts
    status: ContractStatus = ContractStatus.ACTIVE
    published_at: datetime
    published_by: UUID
    published_by_user_id: UUID | None = None
