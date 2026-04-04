"""Service models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ServiceCreate(BaseModel):
    """Fields for creating a service."""

    name: str = Field(..., min_length=1, max_length=200)
    repo_id: UUID
    root_path: str = Field(default="/", min_length=1, max_length=500)
    otel_service_name: str | None = Field(default=None, max_length=200)
    owner_team_id: UUID


class ServiceUpdate(BaseModel):
    """Fields for updating a service. Only mutable fields are exposed."""

    root_path: str | None = Field(default=None, min_length=1, max_length=500)
    otel_service_name: str | None = None


class Service(BaseModel):
    """Service entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    repo_id: UUID
    root_path: str
    otel_service_name: str | None = None
    owner_team_id: UUID
    created_at: datetime
    updated_at: datetime | None = None
