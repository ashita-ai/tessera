"""Authentication dependencies for API endpoints."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.errors import ErrorCode, ForbiddenError, UnauthorizedError
from tessera.config import settings
from tessera.db.database import get_session
from tessera.db.models import APIKeyDB, TeamDB, UserDB
from tessera.models.enums import APIKeyScope
from tessera.services.auth import validate_api_key

logger = logging.getLogger(__name__)

# API key header scheme
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def _get_session_auth_context(
    request: Request,
    session: AsyncSession,
) -> "AuthContext | None":
    """Get auth context from session cookie (for web UI users).

    Returns None if no valid session exists.
    """
    from sqlalchemy import select

    # Check if request has a session with user_id
    if not hasattr(request, "session"):
        return None

    user_id = request.session.get("user_id")
    if not user_id:
        return None

    try:
        # Look up the user
        result = await session.execute(
            select(UserDB).where(UserDB.id == UUID(user_id)).where(UserDB.deactivated_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        # Get the user's team
        if not user.team_id:
            return None

        team_result = await session.execute(select(TeamDB).where(TeamDB.id == user.team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        # Determine scopes based on user role
        if user.role.value == "admin":
            scopes = list(APIKeyScope)
        elif user.role.value == "team_admin":
            scopes = [APIKeyScope.READ, APIKeyScope.WRITE]
        else:
            scopes = [APIKeyScope.READ]

        # Create a mock API key for session auth
        mock_key = APIKeyDB(
            key_hash="session",
            key_prefix="session",
            name=f"Session: {user.email}",
            team_id=team.id,
            scopes=[s.value for s in scopes],
        )

        return AuthContext(
            team=team,
            api_key=mock_key,
            scopes=scopes,
        )
    except ValueError as e:
        logger.debug(f"Session auth failed: {e}")
        return None


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
        """
        Check whether the authenticated API key grants the given scope.

        This method uses a short-circuit permission model: if the API key
        includes the ADMIN scope, it is treated as having all permissions
        and this method returns True regardless of the requested scope.

        Args:
            scope (APIKeyScope): The permission scope to check.

        Returns:
            bool: True if the scope is explicitly present in the key's scopes
            or implicitly granted via the ADMIN scope; otherwise False.
        """
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
    """Get authentication context from the request with rate limiting.

    This dependency validates the API key and returns the authenticated
    team and key information. Rate limited to prevent brute force attacks.

    Raises:
        HTTPException: If authentication fails or rate limit is exceeded
    """
    # Apply rate limiting for authentication attempts
    # This is done inline rather than with a decorator because dependencies
    # need manual rate limit checking
    if settings.rate_limit_enabled:
        from limits import parse

        from tessera.api.rate_limit import get_rate_limit_key, limiter

        # Parse the rate limit string into a RateLimitItem
        rate_limit_item = parse(settings.rate_limit_auth)

        # Get the rate limit key (per-API-key or per-IP)
        limit_key = get_rate_limit_key(request)

        # Test if the limit would be exceeded
        if not limiter.limiter.test(rate_limit_item, limit_key):
            # Limit exceeded - raise HTTPException with 429 status
            # This will be caught by the rate_limit_exceeded_handler
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {settings.rate_limit_auth}",
                headers={"Retry-After": "60"},
            )

        # Hit the limiter to count this request
        limiter.limiter.hit(rate_limit_item, limit_key)

    # Check if auth is disabled (development only)
    if settings.auth_disabled:
        # Return a mock auth context for development
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
        # Try session-based authentication for web UI
        session_auth = await _get_session_auth_context(request, session)
        if session_auth:
            request.state.auth = session_auth
            return session_auth

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
        # Bootstrap key has full admin access
        from sqlalchemy import select

        result = await session.execute(select(TeamDB).limit(1))
        team = result.scalar_one_or_none()

        # If no team exists, create a mock team for bootstrap operations (like creating first team)
        if not team:
            mock_team_id = uuid4()
            team = TeamDB(id=mock_team_id, name="bootstrap-placeholder")

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
    Note: This does not apply rate limiting since it's optional authentication.
    """
    if not authorization and not settings.auth_disabled:
        return None

    try:
        return await get_auth_context(request, authorization, session)
    except HTTPException as e:
        logger.debug("Optional auth failed (status=%s): %s", e.status_code, e.detail)
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
