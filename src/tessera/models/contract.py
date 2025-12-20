"""Contract models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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

    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", description="Semantic version")
    schema_def: dict[str, Any] = Field(..., alias="schema", description="JSON Schema definition")
    compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD
    guarantees: Guarantees | None = None


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
