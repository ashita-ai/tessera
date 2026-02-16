"""Schemas API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.rate_limit import limit_read
from tessera.db import get_session
from tessera.services import check_schema_validity

router = APIRouter()


@router.post("/validate")
@limit_read
async def validate_schema(
    request: Request,
    schema: dict[str, Any],
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Validate a JSON Schema.

    Checks whether the provided dictionary is a valid JSON Schema (Draft 7).
    Requires read scope. Rate-limited to prevent CPU abuse from deeply nested schemas.

    Returns:
        - valid: boolean indicating if the schema is valid
        - errors: list of error messages (empty if valid)
    """
    return check_schema_validity(schema)
