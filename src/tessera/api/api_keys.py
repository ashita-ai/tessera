"""API key management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import (
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from tessera.api.rate_limit import limit_admin
from tessera.db.database import get_session
from tessera.models.api_key import APIKey, APIKeyCreate, APIKeyCreated, APIKeyList
from tessera.models.enums import APIKeyScope
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.auth import (
    create_api_key,
    get_api_key,
    list_api_keys,
    revoke_api_key,
)

router = APIRouter()


@router.post("", response_model=APIKeyCreated, status_code=201)
@limit_admin
async def create_key(
    request: Request,
    key_data: APIKeyCreate,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> APIKeyCreated:
    """Create a new API key.

    Requires admin scope. The raw key is only returned once in this response.
    Store it securely - it cannot be retrieved again.
    """
    try:
        api_key = await create_api_key(session, key_data)

        # Audit log
        await audit.log_event(
            session=session,
            entity_type="api_key",
            entity_id=api_key.id,
            action=AuditAction.API_KEY_CREATED,
            actor_id=auth.team_id,
            payload={
                "name": api_key.name,
                "team_id": str(api_key.team_id),
                "scopes": [s.value for s in api_key.scopes],
            },
        )

        return api_key
    except ValueError as e:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, str(e))


@router.get("", response_model=APIKeyList)
@limit_admin
async def list_keys(
    request: Request,
    auth: Auth,
    team_id: UUID | None = None,
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_session),
) -> APIKeyList:
    """List API keys.

    Non-admin users can only see keys for their own team.
    Admin users can see keys for any team or all teams.
    """
    # Non-admins can only see their own team's keys
    if not auth.has_scope(APIKeyScope.ADMIN):
        team_id = auth.team_id

    keys = await list_api_keys(session, team_id=team_id, include_revoked=include_revoked)
    return APIKeyList(keys=keys)


@router.get("/{key_id}", response_model=APIKey)
@limit_admin
async def get_key(
    request: Request,
    key_id: UUID,
    auth: Auth,
    session: AsyncSession = Depends(get_session),
) -> APIKey:
    """Get an API key by ID.

    Non-admin users can only view keys for their own team.
    """
    api_key = await get_api_key(session, key_id)
    if not api_key:
        raise NotFoundError(ErrorCode.API_KEY_NOT_FOUND, f"API key {key_id} not found")

    # Non-admins can only see their own team's keys
    if not auth.has_scope(APIKeyScope.ADMIN) and api_key.team_id != auth.team_id:
        raise ForbiddenError("Cannot view keys for other teams")

    return api_key


@router.delete("/{key_id}", response_model=APIKey)
@limit_admin
async def revoke_key(
    request: Request,
    key_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> APIKey:
    """Revoke an API key.

    Requires admin scope. Revoked keys cannot be used for authentication.
    """
    api_key = await revoke_api_key(session, key_id)
    if not api_key:
        raise NotFoundError(ErrorCode.API_KEY_NOT_FOUND, f"API key {key_id} not found")

    # Audit log
    await audit.log_event(
        session=session,
        entity_type="api_key",
        entity_id=api_key.id,
        action=AuditAction.API_KEY_REVOKED,
        actor_id=auth.team_id,
        payload={
            "name": api_key.name,
            "team_id": str(api_key.team_id),
        },
    )

    return api_key
