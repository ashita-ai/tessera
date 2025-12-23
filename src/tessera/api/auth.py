"""Authentication dependencies for API endpoints."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.errors import ErrorCode, ForbiddenError, UnauthorizedError
from tessera.config import settings
from tessera.db.database import get_session
from tessera.db.models import APIKeyDB, TeamDB
from tessera.models.enums import APIKeyScope
from tessera.services.auth import validate_api_key

# API key header scheme
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


class AuthContext:
    """Authentication context containing the authenticated team and API key."""

    def __init__(
        self,
        team: TeamDB,
        api_key: APIKeyDB,
        scopes: list[APIKeyScope],
    ):
        self.team = team
        self.api_key = api_key
        self.scopes = scopes

    @property
    def team_id(self) -> UUID:
        """Get the authenticated team ID."""
        return self.team.id

    def has_scope(self, scope: APIKeyScope) -> bool:
        """Check if the authenticated key has a specific scope."""
        # Admin has all permissions
        if APIKeyScope.ADMIN in self.scopes:
            return True
        return scope in self.scopes

    def require_scope(self, scope: APIKeyScope) -> None:
        """Raise ForbiddenError if the key doesn't have the required scope."""
        if not self.has_scope(scope):
            raise ForbiddenError(
                f"This operation requires the '{scope}' scope",
                code=ErrorCode.INSUFFICIENT_SCOPE,
                extra={"required_scope": scope},
            )


async def get_auth_context(
    request: Request,
    authorization: str | None = Security(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """Get authentication context from the request.

    This dependency validates the API key and returns the authenticated
    team and key information.

    Raises:
        HTTPException: If authentication fails
    """
    # Check if auth is disabled (development only)
    if settings.auth_disabled:
        # Return a mock auth context for development
        from uuid import uuid4

        from sqlalchemy import select

        result = await session.execute(select(TeamDB).limit(1))
        team = result.scalar_one_or_none()

        # If no team exists, create a mock team object (not persisted)
        # This allows endpoints to work even when the database is empty
        if not team:
            mock_team_id = uuid4()
            team = TeamDB(id=mock_team_id, name="mock-dev-team")

        # Create a mock API key DB object
        mock_key = APIKeyDB(
            key_hash="disabled",
            key_prefix="disabled",
            name="Auth Disabled",
            team_id=team.id,
            scopes=[s.value for s in APIKeyScope],
        )
        auth_context = AuthContext(
            team=team,
            api_key=mock_key,
            scopes=list(APIKeyScope),
        )
        request.state.auth = auth_context
        return auth_context

    # Check for Authorization header
    if not authorization:
        raise UnauthorizedError(
            "Missing Authorization header. Use 'Authorization: Bearer <api_key>'",
            code=ErrorCode.MISSING_API_KEY,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parse Bearer token
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError(
            "Invalid format. Use 'Authorization: Bearer <api_key>'",
            code=ErrorCode.INVALID_AUTH_HEADER,
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key = authorization[7:]  # Remove "Bearer " prefix

    # Check bootstrap key
    if settings.bootstrap_api_key and api_key == settings.bootstrap_api_key:
        # Bootstrap key has full admin access to the first team
        from sqlalchemy import select

        result = await session.execute(select(TeamDB).limit(1))
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "NO_TEAMS",
                    "message": "No teams exist. Create a team first using the bootstrap key.",
                },
            )
        mock_key = APIKeyDB(
            key_hash="bootstrap",
            key_prefix="bootstrap",
            name="Bootstrap Key",
            team_id=team.id,
            scopes=[s.value for s in APIKeyScope],
        )
        auth_context = AuthContext(
            team=team,
            api_key=mock_key,
            scopes=list(APIKeyScope),
        )
        request.state.auth = auth_context
        return auth_context

    # Validate the API key
    validated = await validate_api_key(session, api_key)
    if not validated:
        raise UnauthorizedError(
            "Invalid or expired API key",
            code=ErrorCode.INVALID_API_KEY,
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key_db, team_db = validated
    scopes = [APIKeyScope(s) for s in api_key_db.scopes]

    auth_context = AuthContext(
        team=team_db,
        api_key=api_key_db,
        scopes=scopes,
    )
    request.state.auth = auth_context
    return auth_context


# Type alias for dependency injection
Auth = Annotated[AuthContext, Depends(get_auth_context)]


async def get_optional_auth_context(
    request: Request,
    authorization: str | None = Security(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> AuthContext | None:
    """Get optional authentication context.

    Returns None if no authentication is provided, instead of raising an error.
    Useful for endpoints that work with or without authentication.
    """
    if not authorization and not settings.auth_disabled:
        return None

    try:
        return await get_auth_context(request, authorization, session)
    except HTTPException:
        return None


# Type alias for optional auth
OptionalAuth = Annotated[AuthContext | None, Depends(get_optional_auth_context)]


def require_scope(
    scope: APIKeyScope,
) -> Callable[..., Awaitable[None]]:
    """Dependency factory that requires a specific scope.

    Usage:
        @router.post("/admin-only")
        async def admin_endpoint(
            auth: Auth,
            _: None = Depends(require_scope(APIKeyScope.ADMIN))
        ):
            ...
    """

    async def check_scope(auth: Auth) -> None:
        auth.require_scope(scope)

    return check_scope


# Pre-built scope dependencies
RequireRead = Depends(require_scope(APIKeyScope.READ))
RequireWrite = Depends(require_scope(APIKeyScope.WRITE))
RequireAdmin = Depends(require_scope(APIKeyScope.ADMIN))
