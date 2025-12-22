"""Pagination utilities for API endpoints."""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters extracted from query params."""

    limit: int = settings.pagination_limit_default
    offset: int = 0


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response structure."""

    results: list[T]
    total: int
    limit: int
    offset: int


def pagination_params(
    limit: int = Query(
        settings.pagination_limit_default,
        ge=1,
        le=settings.pagination_limit_max,
        description="Results per page",
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PaginationParams:
    """FastAPI dependency for pagination parameters."""
    return PaginationParams(limit=limit, offset=offset)


async def paginate(
    session: AsyncSession,
    query: Select[tuple[T]],
    params: PaginationParams,
    response_model: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """Execute a paginated query and return structured response.

    Args:
        session: Database session
        query: SQLAlchemy select query (without limit/offset applied)
        params: Pagination parameters
        response_model: Optional Pydantic model to validate/serialize results

    Returns:
        Dict with results, total, limit, offset keys
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    items: Sequence[Any] = result.scalars().all()

    # Serialize using response model if provided
    if response_model is not None:
        results = [response_model.model_validate(item).model_dump() for item in items]
    else:
        results = list(items)

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }
