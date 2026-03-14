"""Asset context endpoint — single-call aggregation of all asset data."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_read
from tessera.db import AssetDB, get_session
from tessera.services.asset_context import get_asset_context

router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Not found — asset does not exist"},
    422: {"description": "Validation error — check request format"},
}


@router.get(
    "/{asset_id}/context",
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_asset_context_by_id(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get full context for an asset by ID.

    Returns a composed view with asset metadata, current contract, consumers,
    upstream/downstream lineage, active proposals, and recent audit runs.
    Requires READ scope.
    """
    asset = await _load_asset_by_id(session, asset_id)
    return await get_asset_context(session, asset)


@router.get(
    "/context",
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_read
async def get_asset_context_by_fqn(
    request: Request,
    auth: Auth,
    fqn: str = Query(..., min_length=1, description="Fully qualified name of the asset"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get full context for an asset by FQN.

    Returns a composed view with asset metadata, current contract, consumers,
    upstream/downstream lineage, active proposals, and recent audit runs.
    Requires READ scope.
    """
    if not fqn.strip():
        raise BadRequestError("FQN parameter cannot be empty")

    result = await session.execute(
        select(AssetDB).where(AssetDB.fqn == fqn).where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, f"Asset with FQN '{fqn}' not found")
    return await get_asset_context(session, asset)


async def _load_asset_by_id(session: AsyncSession, asset_id: UUID) -> AssetDB:
    """Load an asset by ID, raising 404 if not found or deleted."""
    result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")
    return asset
