"""Services API endpoints."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    DuplicateError,
    ErrorCode,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import PaginatedResponse
from tessera.db import AssetDB, RepoDB, ServiceDB, get_session
from tessera.models import Asset, Service
from tessera.models.service import ServiceCreate, ServiceUpdate
from tessera.services import audit
from tessera.services.audit import AuditAction


class ServiceWithAssetCount(TypedDict, total=False):
    """Service with asset count for detail responses."""

    id: UUID
    name: str
    repo_id: UUID
    root_path: str
    otel_service_name: str | None
    owner_team_id: UUID  # Computed from repo
    created_at: datetime
    updated_at: datetime | None
    asset_count: int


router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    422: {"description": "Validation error — invalid request body"},
}


@router.post(
    "",
    response_model=Service,
    status_code=201,
    responses={k: _E[k] for k in (401, 403, 404, 409)},
)
@limit_write
async def create_service(
    request: Request,
    body: ServiceCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ServiceDB:
    """Register a new service.

    A service is a deployable unit within a repository. Requires WRITE scope.
    The referenced repo_id must exist (non-deleted).
    """
    # Validate repo exists
    repo_result = await session.execute(
        select(RepoDB).where(RepoDB.id == body.repo_id).where(RepoDB.deleted_at.is_(None))
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise NotFoundError(ErrorCode.REPO_NOT_FOUND, "Repo not found")

    db_service = ServiceDB(
        name=body.name,
        repo_id=body.repo_id,
        root_path=body.root_path,
        otel_service_name=body.otel_service_name,
    )
    session.add(db_service)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_SERVICE,
            f"Service with name '{body.name}' already exists in this repo",
        )
    await session.refresh(db_service)

    await audit.log_event(
        session=session,
        entity_type="service",
        entity_id=db_service.id,
        action=AuditAction.SERVICE_CREATED,
        payload={"name": body.name, "repo_id": str(body.repo_id)},
    )

    return db_service


@router.get("", responses={k: _E[k] for k in (401, 403)})
@limit_read
async def list_services(
    request: Request,
    auth: Auth,
    repo_id: UUID | None = Query(None, description="Filter by repository"),
    team_id: UUID | None = Query(None, description="Filter by owner team"),
    otel_service_name: str | None = Query(None, description="Filter by OTel service name"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List services with filters and pagination.

    Requires READ scope.
    """
    base_query = select(ServiceDB).where(ServiceDB.deleted_at.is_(None))

    if repo_id is not None:
        base_query = base_query.where(ServiceDB.repo_id == repo_id)
    if team_id is not None:
        base_query = base_query.join(RepoDB, ServiceDB.repo_id == RepoDB.id).where(
            RepoDB.owner_team_id == team_id
        )
    if otel_service_name is not None:
        base_query = base_query.where(ServiceDB.otel_service_name == otel_service_name)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = base_query.order_by(ServiceDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    services = list(result.scalars().all())

    results: list[dict[str, object]] = [Service.model_validate(s).model_dump() for s in services]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/{service_id}",
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_service(
    request: Request,
    service_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ServiceWithAssetCount:
    """Get a service by ID, including its asset count.

    Requires READ scope.
    """
    result = await session.execute(
        select(ServiceDB).where(ServiceDB.id == service_id).where(ServiceDB.deleted_at.is_(None))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise NotFoundError(ErrorCode.SERVICE_NOT_FOUND, "Service not found")

    asset_count_result = await session.execute(
        select(func.count(AssetDB.id))
        .where(AssetDB.service_id == service_id)
        .where(AssetDB.deleted_at.is_(None))
    )
    asset_count = asset_count_result.scalar() or 0

    service_dict: ServiceWithAssetCount = Service.model_validate(service).model_dump()  # type: ignore[assignment]
    service_dict["asset_count"] = asset_count
    return service_dict


@router.get(
    "/{service_id}/assets",
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def list_service_assets(
    request: Request,
    service_id: UUID,
    auth: Auth,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List assets belonging to a service.

    Requires READ scope.
    """
    # Verify service exists
    svc_result = await session.execute(
        select(ServiceDB).where(ServiceDB.id == service_id).where(ServiceDB.deleted_at.is_(None))
    )
    if not svc_result.scalar_one_or_none():
        raise NotFoundError(ErrorCode.SERVICE_NOT_FOUND, "Service not found")

    base_query = (
        select(AssetDB).where(AssetDB.service_id == service_id).where(AssetDB.deleted_at.is_(None))
    )

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = base_query.order_by(AssetDB.fqn).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    assets = list(result.scalars().all())

    results: list[dict[str, object]] = [Asset.model_validate(a).model_dump() for a in assets]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.patch(
    "/{service_id}",
    response_model=Service,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def update_service(
    request: Request,
    service_id: UUID,
    body: ServiceUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ServiceDB:
    """Update mutable service fields (root_path, otel_service_name).

    Requires WRITE scope.
    """
    result = await session.execute(
        select(ServiceDB).where(ServiceDB.id == service_id).where(ServiceDB.deleted_at.is_(None))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise NotFoundError(ErrorCode.SERVICE_NOT_FOUND, "Service not found")

    changes: dict[str, object] = {}
    if body.root_path is not None:
        service.root_path = body.root_path
        changes["root_path"] = body.root_path
    if body.otel_service_name is not None:
        service.otel_service_name = body.otel_service_name
        changes["otel_service_name"] = body.otel_service_name

    await session.flush()
    await session.refresh(service)

    await audit.log_event(
        session=session,
        entity_type="service",
        entity_id=service_id,
        action=AuditAction.SERVICE_UPDATED,
        payload=changes,
    )

    return service


@router.delete(
    "/{service_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def delete_service(
    request: Request,
    service_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft delete a service.

    Requires WRITE scope.
    """
    result = await session.execute(
        select(ServiceDB).where(ServiceDB.id == service_id).where(ServiceDB.deleted_at.is_(None))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise NotFoundError(ErrorCode.SERVICE_NOT_FOUND, "Service not found")

    service.deleted_at = datetime.now(UTC)
    await session.flush()

    await audit.log_event(
        session=session,
        entity_type="service",
        entity_id=service_id,
        action=AuditAction.SERVICE_DELETED,
        payload={"name": service.name, "repo_id": str(service.repo_id)},
    )
