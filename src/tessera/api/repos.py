"""Repo CRUD API endpoints."""

import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    DuplicateError,
    ErrorCode,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import PaginatedResponse
from tessera.db import RepoDB, ServiceDB, SyncEventDB, TeamDB, get_session
from tessera.models.repo import Repo, RepoCreate, RepoUpdate, SyncEvent
from tessera.services import audit
from tessera.services.audit import AuditAction

router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    422: {"description": "Validation error — invalid request body"},
}


async def _get_active_repo(session: AsyncSession, repo_id: UUID) -> RepoDB:
    """Fetch an active (non-deleted) repo or raise NotFoundError."""
    result = await session.execute(
        select(RepoDB).where(RepoDB.id == repo_id).where(RepoDB.deleted_at.is_(None))
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise NotFoundError(ErrorCode.REPO_NOT_FOUND, "Repository not found")
    return repo


@router.post(
    "",
    response_model=Repo,
    status_code=201,
    responses={k: _E[k] for k in (401, 403, 404, 409)},
)
@limit_write
async def create_repo(
    request: Request,
    repo: RepoCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> RepoDB:
    """Register a new repository.

    Requires write scope. The owner_team_id must reference an existing team.
    """
    # Verify owner team exists
    team_result = await session.execute(
        select(TeamDB).where(TeamDB.id == repo.owner_team_id).where(TeamDB.deleted_at.is_(None))
    )
    if not team_result.scalar_one_or_none():
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

    db_repo = RepoDB(
        name=repo.name,
        git_url=repo.git_url,
        default_branch=repo.default_branch,
        spec_paths=repo.spec_paths,
        owner_team_id=repo.owner_team_id,
        sync_enabled=repo.sync_enabled,
        codeowners_path=repo.codeowners_path,
        git_token=repo.git_token,
        ssh_key=repo.ssh_key,
    )
    session.add(db_repo)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_REPO,
            f"Repository with name '{repo.name}' or git URL '{repo.git_url}' already exists",
        )
    await session.refresh(db_repo)

    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=db_repo.id,
        action=AuditAction.REPO_CREATED,
        actor_id=auth.team_id,
        payload={"name": repo.name, "git_url": repo.git_url},
    )

    return db_repo


@router.get("", responses={k: _E[k] for k in (401, 403)})
@limit_read
async def list_repos(
    request: Request,
    auth: Auth,
    team_id: UUID | None = Query(None, description="Filter by owner team ID"),
    sync_enabled: bool | None = Query(None, description="Filter by sync_enabled flag"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List repositories with optional filters and pagination.

    Requires read scope.
    """
    base_query = select(RepoDB).where(RepoDB.deleted_at.is_(None))

    if team_id is not None:
        base_query = base_query.where(RepoDB.owner_team_id == team_id)
    if sync_enabled is not None:
        base_query = base_query.where(RepoDB.sync_enabled == sync_enabled)

    # Total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginated results
    query = base_query.order_by(RepoDB.name).limit(params.limit).offset(params.offset)
    result = await session.execute(query)
    repos = list(result.scalars().all())

    results: list[dict[str, object]] = [Repo.model_validate(r).model_dump() for r in repos]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/{repo_id}",
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_repo(
    request: Request,
    repo_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Get a single repository by ID, including its services count.

    Requires read scope.
    """
    repo = await _get_active_repo(session, repo_id)

    # Count active services for this repo
    count_result = await session.execute(
        select(func.count(ServiceDB.id))
        .where(ServiceDB.repo_id == repo_id)
        .where(ServiceDB.deleted_at.is_(None))
    )
    services_count = count_result.scalar() or 0

    repo_dict: dict[str, object] = Repo.model_validate(repo).model_dump()
    repo_dict["services_count"] = services_count
    return repo_dict


@router.patch(
    "/{repo_id}",
    response_model=Repo,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def update_repo(
    request: Request,
    repo_id: UUID,
    update: RepoUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> RepoDB:
    """Update mutable fields of a repository.

    Requires write scope. Only spec_paths, sync_enabled, codeowners_path,
    and default_branch can be updated.
    """
    repo = await _get_active_repo(session, repo_id)

    changed: dict[str, object] = {}
    if update.default_branch is not None:
        repo.default_branch = update.default_branch
        changed["default_branch"] = update.default_branch
    if update.spec_paths is not None:
        repo.spec_paths = update.spec_paths
        changed["spec_paths"] = update.spec_paths
    if update.codeowners_path is not None:
        repo.codeowners_path = update.codeowners_path
        changed["codeowners_path"] = update.codeowners_path
    if update.sync_enabled is not None:
        repo.sync_enabled = update.sync_enabled
        changed["sync_enabled"] = update.sync_enabled
    if update.git_token is not None:
        repo.git_token = update.git_token
        changed["git_token"] = "***"  # Never log plaintext
    if update.ssh_key is not None:
        repo.ssh_key = update.ssh_key
        changed["ssh_key"] = "***"  # Never log plaintext

    await session.flush()
    await session.refresh(repo)

    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo_id,
        action=AuditAction.REPO_UPDATED,
        actor_id=auth.team_id,
        payload={"changed_fields": changed},
    )

    return repo


@router.delete(
    "/{repo_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def delete_repo(
    request: Request,
    repo_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete a repository.

    Requires write scope.
    """
    repo = await _get_active_repo(session, repo_id)

    repo.deleted_at = datetime.now(UTC)
    await session.flush()

    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo_id,
        action=AuditAction.REPO_DELETED,
        actor_id=auth.team_id,
        payload={"name": repo.name},
    )


@router.post(
    "/{repo_id}/sync",
    status_code=202,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def trigger_repo_sync(
    request: Request,
    repo_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Trigger an immediate sync for a repository.

    Requires write scope. Runs sync synchronously and returns the result.
    """
    from tessera.services.repo_sync import save_sync_event, sync_repo

    repo = await _get_active_repo(session, repo_id)

    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo_id,
        action=AuditAction.REPO_SYNC_TRIGGERED,
        actor_id=auth.team_id,
        payload={"name": repo.name},
    )

    t0 = time.monotonic()
    sync_result = await sync_repo(session, repo)
    duration = time.monotonic() - t0

    # Persist the sync event for history queries.
    await save_sync_event(
        session,
        sync_result,
        duration_seconds=duration,
        triggered_by="manual",
    )

    if sync_result.success:
        await audit.log_event(
            session=session,
            entity_type="repo",
            entity_id=repo_id,
            action=AuditAction.REPO_SYNCED,
            actor_id=auth.team_id,
            payload={
                "commit_sha": sync_result.commit_sha,
                "specs_found": sync_result.specs_found,
                "contracts_published": sync_result.contracts_published,
                "proposals_created": sync_result.proposals_created,
                "services_created": sync_result.services_created,
            },
        )
    else:
        await audit.log_event(
            session=session,
            entity_type="repo",
            entity_id=repo_id,
            action=AuditAction.REPO_SYNC_FAILED,
            actor_id=auth.team_id,
            payload={"errors": sync_result.errors},
        )

    return {
        "status": "completed" if sync_result.success else "failed",
        "repo_id": str(repo_id),
        "commit_sha": sync_result.commit_sha,
        "specs_found": sync_result.specs_found,
        "contracts_published": sync_result.contracts_published,
        "proposals_created": sync_result.proposals_created,
        "services_created": sync_result.services_created,
        "errors": sync_result.errors,
        "warnings": sync_result.warnings,
    }


@router.get(
    "/{repo_id}/sync/history",
    response_model=PaginatedResponse[SyncEvent],
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_sync_history(
    request: Request,
    repo_id: UUID,
    auth: Auth,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List sync events for a repository, newest first.

    Requires read scope.
    """
    await _get_active_repo(session, repo_id)

    base_query = select(SyncEventDB).where(SyncEventDB.repo_id == repo_id)

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = (
        base_query.order_by(SyncEventDB.created_at.desc()).limit(params.limit).offset(params.offset)
    )
    result = await session.execute(query)
    events = list(result.scalars().all())

    results: list[dict[str, object]] = [SyncEvent.model_validate(e).model_dump() for e in events]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/{repo_id}/sync/latest",
    response_model=SyncEvent,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_latest_sync(
    request: Request,
    repo_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Get the most recent sync event for a repository.

    Requires read scope. Returns 404 if no sync has occurred yet.
    """
    await _get_active_repo(session, repo_id)

    result = await session.execute(
        select(SyncEventDB)
        .where(SyncEventDB.repo_id == repo_id)
        .order_by(SyncEventDB.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise NotFoundError(ErrorCode.NOT_FOUND, "No sync events found for this repository")

    return SyncEvent.model_validate(event).model_dump()
