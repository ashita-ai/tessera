"""Tests for authentication with session-based auth and bootstrap key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import (
    AuthContext,
    _get_session_auth_context,
    get_auth_context,
    get_optional_auth_context,
    require_scope,
)
from tessera.db.models import APIKeyDB, TeamDB
from tessera.models.enums import APIKeyScope, UserRole

pytestmark = pytest.mark.asyncio


class TestAuthContext:
    """Tests for AuthContext class."""

    def test_team_id_property(self):
        """team_id property returns team's id."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["read"],
        )
        ctx = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.READ])

        assert ctx.team_id == team.id

    def test_has_scope_direct_match(self):
        """has_scope returns True for matching scope."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["read", "write"],
        )
        ctx = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.READ, APIKeyScope.WRITE])

        assert ctx.has_scope(APIKeyScope.READ) is True
        assert ctx.has_scope(APIKeyScope.WRITE) is True
        assert ctx.has_scope(APIKeyScope.ADMIN) is False

    def test_has_scope_admin_has_all(self):
        """Admin scope grants access to all scopes."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["admin"],
        )
        ctx = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.ADMIN])

        assert ctx.has_scope(APIKeyScope.READ) is True
        assert ctx.has_scope(APIKeyScope.WRITE) is True
        assert ctx.has_scope(APIKeyScope.ADMIN) is True

    def test_require_scope_success(self):
        """require_scope passes for matching scope."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["read"],
        )
        ctx = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.READ])

        # Should not raise
        ctx.require_scope(APIKeyScope.READ)

    def test_require_scope_failure(self):
        """require_scope raises ForbiddenError for missing scope."""
        from tessera.api.errors import ForbiddenError

        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["read"],
        )
        ctx = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.READ])

        with pytest.raises(ForbiddenError):
            ctx.require_scope(APIKeyScope.ADMIN)


class TestGetSessionAuthContext:
    """Tests for _get_session_auth_context function."""

    async def test_no_session_attribute(self):
        """Returns None when request has no session attribute."""
        request = MagicMock(spec=[])
        session = AsyncMock(spec=AsyncSession)

        result = await _get_session_auth_context(request, session)
        assert result is None

    async def test_no_user_id_in_session(self):
        """Returns None when session has no user_id."""
        request = MagicMock()
        request.session = {}
        session = AsyncMock(spec=AsyncSession)

        result = await _get_session_auth_context(request, session)
        assert result is None

    async def test_user_not_found(self):
        """Returns None when user_id doesn't exist in database."""
        request = MagicMock()
        request.session = {"user_id": str(uuid4())}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        result = await _get_session_auth_context(request, session)
        assert result is None

    async def test_user_without_team(self):
        """Returns None when user has no team_id."""
        user_id = uuid4()
        request = MagicMock()
        request.session = {"user_id": str(user_id)}

        # Create a mock user with team_id = None
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.name = "Test User"
        mock_user.role = UserRole.USER
        mock_user.team_id = None
        mock_user.deactivated_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        result = await _get_session_auth_context(request, session)
        assert result is None

    async def test_team_not_found(self):
        """Returns None when user's team doesn't exist."""
        user_id = uuid4()
        team_id = uuid4()
        request = MagicMock()
        request.session = {"user_id": str(user_id)}

        # Create a mock user with team_id set
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.name = "Test User"
        mock_user.role = UserRole.USER
        mock_user.team_id = team_id
        mock_user.deactivated_at = None

        # First call returns user, second call returns no team
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_team_result = MagicMock()
        mock_team_result.scalar_one_or_none.return_value = None

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[mock_user_result, mock_team_result])

        result = await _get_session_auth_context(request, session)
        assert result is None

    async def test_admin_user_gets_all_scopes(self):
        """Admin user gets all API key scopes."""
        user_id = uuid4()
        team_id = uuid4()
        request = MagicMock()
        request.session = {"user_id": str(user_id)}

        # Create mock user with admin role
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "admin@example.com"
        mock_user.name = "Admin User"
        mock_user.role = UserRole.ADMIN
        mock_user.team_id = team_id
        mock_user.deactivated_at = None

        team = TeamDB(id=team_id, name="admin-team")

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_team_result = MagicMock()
        mock_team_result.scalar_one_or_none.return_value = team

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[mock_user_result, mock_team_result])

        result = await _get_session_auth_context(request, session)
        assert result is not None
        assert result.team == team
        assert APIKeyScope.ADMIN in result.scopes
        assert APIKeyScope.READ in result.scopes
        assert APIKeyScope.WRITE in result.scopes

    async def test_team_admin_gets_read_write_scopes(self):
        """Team admin gets read and write scopes."""
        user_id = uuid4()
        team_id = uuid4()
        request = MagicMock()
        request.session = {"user_id": str(user_id)}

        # Create mock user with team admin role
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "teamadmin@example.com"
        mock_user.name = "Team Admin"
        mock_user.role = UserRole.TEAM_ADMIN
        mock_user.team_id = team_id
        mock_user.deactivated_at = None

        team = TeamDB(id=team_id, name="some-team")

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_team_result = MagicMock()
        mock_team_result.scalar_one_or_none.return_value = team

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[mock_user_result, mock_team_result])

        result = await _get_session_auth_context(request, session)
        assert result is not None
        assert APIKeyScope.READ in result.scopes
        assert APIKeyScope.WRITE in result.scopes
        assert APIKeyScope.ADMIN not in result.scopes

    async def test_member_gets_read_only(self):
        """Regular member gets read-only scope."""
        user_id = uuid4()
        team_id = uuid4()
        request = MagicMock()
        request.session = {"user_id": str(user_id)}

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.email = "member@example.com"
        mock_user.name = "Regular Member"
        mock_user.role = UserRole.USER
        mock_user.team_id = team_id
        mock_user.deactivated_at = None

        team = TeamDB(id=team_id, name="member-team")

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_team_result = MagicMock()
        mock_team_result.scalar_one_or_none.return_value = team

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[mock_user_result, mock_team_result])

        result = await _get_session_auth_context(request, session)
        assert result is not None
        assert result.scopes == [APIKeyScope.READ]

    async def test_exception_returns_none(self):
        """Returns None when an exception occurs."""
        request = MagicMock()
        request.session = {"user_id": "invalid-uuid"}

        session = AsyncMock(spec=AsyncSession)

        result = await _get_session_auth_context(request, session)
        assert result is None


class TestGetAuthContext:
    """Tests for get_auth_context function."""

    async def test_missing_auth_header_no_session(self):
        """Raises UnauthorizedError when no auth header and no session."""
        from tessera.api.errors import UnauthorizedError

        request = MagicMock(spec=[])
        session = AsyncMock(spec=AsyncSession)

        with patch("tessera.api.auth.settings") as mock_settings:
            mock_settings.auth_disabled = False

            with pytest.raises(UnauthorizedError) as exc_info:
                await get_auth_context(request, None, session)
            assert "Missing Authorization header" in str(exc_info.value.message)

    async def test_invalid_auth_format(self):
        """Raises UnauthorizedError for invalid auth format."""
        from tessera.api.errors import UnauthorizedError

        request = MagicMock(spec=[])
        session = AsyncMock(spec=AsyncSession)

        with patch("tessera.api.auth.settings") as mock_settings:
            mock_settings.auth_disabled = False

            with pytest.raises(UnauthorizedError) as exc_info:
                await get_auth_context(request, "Basic abc123", session)
            assert "Invalid format" in str(exc_info.value.message)

    async def test_bootstrap_key_no_teams(self):
        """Raises 503 when using bootstrap key with no teams."""
        from fastapi import HTTPException

        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with patch("tessera.api.auth.settings") as mock_settings:
            mock_settings.auth_disabled = False
            mock_settings.bootstrap_api_key = "bootstrap-key-123"

            with pytest.raises(HTTPException) as exc_info:
                await get_auth_context(request, "Bearer bootstrap-key-123", session)
            assert exc_info.value.status_code == 503

    async def test_bootstrap_key_success(self):
        """Bootstrap key returns admin auth context."""
        team = TeamDB(id=uuid4(), name="first-team")

        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = team
        session.execute = AsyncMock(return_value=mock_result)

        with patch("tessera.api.auth.settings") as mock_settings:
            mock_settings.auth_disabled = False
            mock_settings.bootstrap_api_key = "bootstrap-key-123"

            result = await get_auth_context(request, "Bearer bootstrap-key-123", session)
            assert result.team == team
            assert APIKeyScope.ADMIN in result.scopes

    async def test_invalid_api_key(self):
        """Raises UnauthorizedError for invalid API key."""
        from tessera.api.errors import UnauthorizedError

        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        with (
            patch("tessera.api.auth.settings") as mock_settings,
            patch("tessera.api.auth.validate_api_key") as mock_validate,
        ):
            mock_settings.auth_disabled = False
            mock_settings.bootstrap_api_key = None
            mock_validate.return_value = None

            with pytest.raises(UnauthorizedError) as exc_info:
                await get_auth_context(request, "Bearer invalid-key", session)
            assert "Invalid or expired" in str(exc_info.value.message)

    async def test_valid_api_key(self):
        """Valid API key returns proper auth context."""
        team = TeamDB(id=uuid4(), name="api-team")
        api_key = APIKeyDB(
            id=uuid4(),
            key_hash="hash",
            key_prefix="tsr_",
            name="test-key",
            team_id=team.id,
            scopes=["read", "write"],
        )

        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        with (
            patch("tessera.api.auth.settings") as mock_settings,
            patch("tessera.api.auth.validate_api_key") as mock_validate,
        ):
            mock_settings.auth_disabled = False
            mock_settings.bootstrap_api_key = None
            mock_validate.return_value = (api_key, team)

            result = await get_auth_context(request, "Bearer valid-key", session)
            assert result.team == team
            assert result.api_key == api_key
            assert APIKeyScope.READ in result.scopes
            assert APIKeyScope.WRITE in result.scopes


class TestGetOptionalAuthContext:
    """Tests for get_optional_auth_context function."""

    async def test_no_auth_returns_none(self):
        """Returns None when no authentication provided."""
        request = MagicMock(spec=[])
        session = AsyncMock(spec=AsyncSession)

        with patch("tessera.api.auth.settings") as mock_settings:
            mock_settings.auth_disabled = False

            result = await get_optional_auth_context(request, None, session)
            assert result is None

    async def test_invalid_auth_returns_none(self):
        """Returns None when authentication fails."""
        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        # For optional auth, when invalid key is provided, it should catch
        # the HTTPException and return None. We need to mock at a level where
        # the HTTPException will be raised and caught.
        with patch("tessera.api.auth.get_auth_context") as mock_get_auth:
            from fastapi import HTTPException

            mock_get_auth.side_effect = HTTPException(status_code=401, detail="Invalid")
            result = await get_optional_auth_context(request, "Bearer invalid", session)
            assert result is None

    async def test_valid_auth_returns_context(self):
        """Returns context when authentication succeeds."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            id=uuid4(),
            key_hash="hash",
            key_prefix="tsr_",
            name="test-key",
            team_id=team.id,
            scopes=["read"],
        )

        request = MagicMock()
        request.state = MagicMock()
        session = AsyncMock(spec=AsyncSession)

        with (
            patch("tessera.api.auth.settings") as mock_settings,
            patch("tessera.api.auth.validate_api_key") as mock_validate,
        ):
            mock_settings.auth_disabled = False
            mock_settings.bootstrap_api_key = None
            mock_validate.return_value = (api_key, team)

            result = await get_optional_auth_context(request, "Bearer valid-key", session)
            assert result is not None
            assert result.team == team


class TestRequireScope:
    """Tests for require_scope dependency factory."""

    async def test_require_scope_creates_dependency(self):
        """require_scope creates a callable dependency."""
        dep = require_scope(APIKeyScope.ADMIN)
        assert callable(dep)

    async def test_require_scope_passes_with_scope(self):
        """Dependency passes when scope is present."""
        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["admin"],
        )
        auth = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.ADMIN])

        dep = require_scope(APIKeyScope.ADMIN)
        # Should not raise
        await dep(auth)

    async def test_require_scope_fails_without_scope(self):
        """Dependency raises when scope is missing."""
        from tessera.api.errors import ForbiddenError

        team = TeamDB(id=uuid4(), name="test-team")
        api_key = APIKeyDB(
            key_hash="hash",
            key_prefix="prefix",
            name="test-key",
            team_id=team.id,
            scopes=["read"],
        )
        auth = AuthContext(team=team, api_key=api_key, scopes=[APIKeyScope.READ])

        dep = require_scope(APIKeyScope.ADMIN)
        with pytest.raises(ForbiddenError):
            await dep(auth)
