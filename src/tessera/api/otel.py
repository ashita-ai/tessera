"""OTEL dependency discovery API endpoints.

Provides CRUD for OTEL sync configs, manual sync trigger,
OTEL-discovered dependency listing, and reconciliation.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import PaginatedResponse
from tessera.config import settings
from tessera.db import AssetDependencyDB, OtelSyncConfigDB, get_session
from tessera.models.enums import DependencySource
from tessera.models.otel import (
    OtelDependency,
    OtelSyncConfig,
    OtelSyncConfigCreate,
    OtelSyncConfigUpdate,
    ReconciliationReport,
    SyncResult,
)
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.otel import build_reconciliation_report, run_sync

router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    422: {"description": "Validation error — invalid request body"},
}


# ── Config CRUD ───────────────────────────────────────────────


@router.post(
    "/configs",
    response_model=OtelSyncConfig,
    status_code=201,
    responses={k: _E[k] for k in (401, 403, 409)},
)
@limit_write
async def create_otel_config(
    request: Request,
    body: OtelSyncConfigCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> OtelSyncConfigDB:
    """Register a new OTEL trace backend for dependency discovery.

    Requires WRITE scope.
    """
    db_config = OtelSyncConfigDB(
        name=body.name,
        backend_type=body.backend_type,
        endpoint_url=body.endpoint_url,
        auth_header=body.auth_header,
        lookback_seconds=body.lookback_seconds,
        poll_interval_seconds=body.poll_interval_seconds,
        min_call_count=body.min_call_count,
        enabled=body.enabled,
    )
    session.add(db_config)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_OTEL_CONFIG,
            f"OTEL config with name '{body.name}' already exists",
        )
    await session.refresh(db_config)

    await audit.log_event(
        session=session,
        entity_type="otel_config",
        entity_id=db_config.id,
        action=AuditAction.OTEL_CONFIG_CREATED,
        payload={"name": body.name, "backend_type": body.backend_type},
    )

    return db_config


@router.get(
    "/configs",
    responses={k: _E[k] for k in (401, 403)},
)
@limit_read
async def list_otel_configs(
    request: Request,
    auth: Auth,
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List configured OTEL backends.

    Requires READ scope.
    """
    base_query = select(OtelSyncConfigDB)
    if enabled is not None:
        base_query = base_query.where(OtelSyncConfigDB.enabled == enabled)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = base_query.order_by(OtelSyncConfigDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    configs = list(result.scalars().all())

    results: list[dict[str, object]] = [
        OtelSyncConfig.model_validate(c).model_dump() for c in configs
    ]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/configs/{config_id}",
    response_model=OtelSyncConfig,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_otel_config(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> OtelSyncConfigDB:
    """Get an OTEL config by ID.

    Requires READ scope.
    """
    result = await session.execute(select(OtelSyncConfigDB).where(OtelSyncConfigDB.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.OTEL_CONFIG_NOT_FOUND, "OTEL config not found")
    return config


@router.patch(
    "/configs/{config_id}",
    response_model=OtelSyncConfig,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def update_otel_config(
    request: Request,
    config_id: UUID,
    body: OtelSyncConfigUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> OtelSyncConfigDB:
    """Update an OTEL config. Requires WRITE scope."""
    result = await session.execute(select(OtelSyncConfigDB).where(OtelSyncConfigDB.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.OTEL_CONFIG_NOT_FOUND, "OTEL config not found")

    changes: dict[str, object] = {}
    if body.name is not None:
        config.name = body.name
        changes["name"] = body.name
    if body.endpoint_url is not None:
        config.endpoint_url = body.endpoint_url
        changes["endpoint_url"] = body.endpoint_url
    if body.auth_header is not None:
        config.auth_header = body.auth_header
        changes["auth_header"] = "***"  # Don't log the actual header
    if body.lookback_seconds is not None:
        config.lookback_seconds = body.lookback_seconds
        changes["lookback_seconds"] = body.lookback_seconds
    if body.poll_interval_seconds is not None:
        config.poll_interval_seconds = body.poll_interval_seconds
        changes["poll_interval_seconds"] = body.poll_interval_seconds
    if body.min_call_count is not None:
        config.min_call_count = body.min_call_count
        changes["min_call_count"] = body.min_call_count
    if body.enabled is not None:
        config.enabled = body.enabled
        changes["enabled"] = body.enabled

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_OTEL_CONFIG,
            f"OTEL config with name '{body.name}' already exists",
        )
    await session.refresh(config)

    await audit.log_event(
        session=session,
        entity_type="otel_config",
        entity_id=config_id,
        action=AuditAction.OTEL_CONFIG_UPDATED,
        payload=changes,
    )

    return config


@router.delete(
    "/configs/{config_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def delete_otel_config(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete an OTEL config. Requires ADMIN scope.

    This is a hard delete since OTEL configs are infrastructure configuration,
    not user data with audit trail requirements.
    """
    result = await session.execute(select(OtelSyncConfigDB).where(OtelSyncConfigDB.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.OTEL_CONFIG_NOT_FOUND, "OTEL config not found")

    config_name = config.name
    await session.delete(config)
    await session.flush()

    await audit.log_event(
        session=session,
        entity_type="otel_config",
        entity_id=config_id,
        action=AuditAction.OTEL_CONFIG_DELETED,
        payload={"name": config_name},
    )


# ── Sync Trigger ──────────────────────────────────────────────


@router.post(
    "/configs/{config_id}/sync",
    response_model=SyncResult,
    status_code=202,
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_write
async def trigger_sync(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> SyncResult:
    """Trigger immediate dependency discovery for an OTEL config.

    Requires WRITE scope. Returns 202 with sync results.
    If OTEL discovery is globally disabled, returns 400.
    """
    if not settings.otel_enabled:
        raise BadRequestError(
            "OTEL dependency discovery is disabled (TESSERA_OTEL_ENABLED=false)",
            code=ErrorCode.OTEL_DISABLED,
        )

    result = await session.execute(select(OtelSyncConfigDB).where(OtelSyncConfigDB.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.OTEL_CONFIG_NOT_FOUND, "OTEL config not found")

    try:
        sync_result = await run_sync(session, config)
    except Exception as exc:
        config.last_sync_error = str(exc)
        config.last_synced_at = datetime.now(UTC)
        await session.flush()

        await audit.log_event(
            session=session,
            entity_type="otel_config",
            entity_id=config_id,
            action=AuditAction.OTEL_SYNC_FAILED,
            payload={"error": str(exc)},
        )
        raise BadRequestError(
            f"OTEL sync failed: {exc}",
            code=ErrorCode.OTEL_SYNC_FAILED,
        )

    await audit.log_event(
        session=session,
        entity_type="otel_config",
        entity_id=config_id,
        action=AuditAction.OTEL_SYNC_COMPLETED,
        payload={
            "edges_fetched": sync_result.edges_fetched,
            "edges_resolved": sync_result.edges_resolved,
            "edges_created": sync_result.edges_created,
            "edges_updated": sync_result.edges_updated,
            "edges_stale": sync_result.edges_stale,
            "unresolved_count": len(sync_result.unresolved_services),
        },
    )

    return sync_result


# ── OTEL Dependencies ─────────────────────────────────────────


@router.get(
    "/dependencies",
    responses={k: _E[k] for k in (401, 403)},
)
@limit_read
async def list_otel_dependencies(
    request: Request,
    auth: Auth,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    stale: bool | None = Query(None, description="Show only stale dependencies"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List OTEL-discovered dependencies with optional filters.

    Requires READ scope.
    """
    base_query = select(AssetDependencyDB).where(
        AssetDependencyDB.source == DependencySource.OTEL,
        AssetDependencyDB.deleted_at.is_(None),
    )

    if min_confidence is not None:
        base_query = base_query.where(AssetDependencyDB.confidence >= min_confidence)
    if stale is True:
        base_query = base_query.where(AssetDependencyDB.confidence <= 0.05)
    elif stale is False:
        base_query = base_query.where(AssetDependencyDB.confidence > 0.05)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = (
        base_query.order_by(AssetDependencyDB.created_at.desc())
        .limit(params.limit)
        .offset(params.offset)
    )
    result = await session.execute(query)
    deps = list(result.scalars().all())

    results: list[dict[str, object]] = [OtelDependency.model_validate(d).model_dump() for d in deps]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


# ── Reconciliation ────────────────────────────────────────────


@router.get(
    "/reconciliation",
    response_model=ReconciliationReport,
    responses={k: _E[k] for k in (401, 403)},
)
@limit_read
async def get_reconciliation(
    request: Request,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationReport:
    """Compare declared (manual) vs observed (OTEL) dependencies.

    Returns three buckets:
    - declared_only: manual deps not observed in traces (possibly stale)
    - observed_only: OTEL deps with no manual registration (undeclared)
    - both: deps confirmed by both sources

    Requires READ scope.
    """
    return await build_reconciliation_report(session)
