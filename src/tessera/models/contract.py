"""Contract models."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tessera.models.enums import CompatibilityMode, ContractStatus

# Maximum schema size in bytes (1MB)
MAX_SCHEMA_SIZE_BYTES = 1_000_000


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

    version: str = Field(
        ...,
        min_length=5,  # Minimum: "0.0.0"
        max_length=50,
        pattern=r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$",
        description="Semantic version (e.g., '1.0.0', '2.1.0-beta.1')",
    )
    schema_def: dict[str, Any] = Field(..., alias="schema", description="JSON Schema definition")
    compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD
    guarantees: Guarantees | None = None

    @field_validator("schema_def")
    @classmethod
    def validate_schema_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate schema size to prevent DoS attacks."""
        serialized = json.dumps(v, separators=(",", ":"))
        if len(serialized) > MAX_SCHEMA_SIZE_BYTES:
            raise ValueError(
                f"Schema too large. Maximum size: {MAX_SCHEMA_SIZE_BYTES:,} bytes "
                f"({MAX_SCHEMA_SIZE_BYTES // 1024 // 1024}MB). "
                f"Current size: {len(serialized):,} bytes."
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
    status: ContractStatus = ContractStatus.ACTIVE
    published_at: datetime
    published_by: UUID
