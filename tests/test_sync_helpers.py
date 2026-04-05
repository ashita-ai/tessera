"""Tests for sync helper functions (resolve_team_by_name, resolve_user_by_email)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.sync.helpers import resolve_team_by_name, resolve_user_by_email
from tessera.db.models import TeamDB, UserDB

pytestmark = pytest.mark.asyncio


class TestResolveTeamByName:
    """Tests for resolve_team_by_name — exact match semantics."""

    async def test_exact_match_found(self, session: AsyncSession):
        team = TeamDB(id=uuid4(), name="Analytics")
        session.add(team)
        await session.flush()

        result = await resolve_team_by_name(session, "Analytics")
        assert result is not None
        assert result.id == team.id

    async def test_case_mismatch_returns_none(self, session: AsyncSession):
        """Exact match must be case-sensitive — 'analytics' should not match 'Analytics'."""
        team = TeamDB(id=uuid4(), name="Analytics")
        session.add(team)
        await session.flush()

        result = await resolve_team_by_name(session, "analytics")
        assert result is None

    async def test_nonexistent_team_returns_none(self, session: AsyncSession):
        result = await resolve_team_by_name(session, "NoSuchTeam")
        assert result is None

    async def test_soft_deleted_team_excluded(self, session: AsyncSession):
        team = TeamDB(
            id=uuid4(),
            name="Deleted",
            deleted_at=datetime.now(UTC),
        )
        session.add(team)
        await session.flush()

        result = await resolve_team_by_name(session, "Deleted")
        assert result is None

    async def test_exact_match_among_similar_names(self, session: AsyncSession):
        """When teams exist with similar names in different cases, only exact match returns."""
        team_upper = TeamDB(id=uuid4(), name="PLATFORM")
        session.add(team_upper)
        await session.flush()

        # Exact match should find the team
        result = await resolve_team_by_name(session, "PLATFORM")
        assert result is not None
        assert result.id == team_upper.id

        # Different case should not
        assert await resolve_team_by_name(session, "platform") is None
        assert await resolve_team_by_name(session, "Platform") is None


class TestResolveUserByEmail:
    """Tests for resolve_user_by_email — exact match semantics."""

    async def test_exact_match_found(self, session: AsyncSession):
        user = UserDB(
            id=uuid4(),
            username="alice",
            email="alice@example.com",
            name="Alice",
        )
        session.add(user)
        await session.flush()

        result = await resolve_user_by_email(session, "alice@example.com")
        assert result is not None
        assert result.id == user.id

    async def test_case_mismatch_returns_none(self, session: AsyncSession):
        """Exact match must be case-sensitive — 'Alice@Example.com' should not match."""
        user = UserDB(
            id=uuid4(),
            username="bob",
            email="bob@example.com",
            name="Bob",
        )
        session.add(user)
        await session.flush()

        result = await resolve_user_by_email(session, "Bob@Example.com")
        assert result is None

    async def test_nonexistent_email_returns_none(self, session: AsyncSession):
        result = await resolve_user_by_email(session, "nobody@nowhere.com")
        assert result is None

    async def test_deactivated_user_excluded(self, session: AsyncSession):
        user = UserDB(
            id=uuid4(),
            username="gone",
            email="gone@example.com",
            name="Gone",
            deactivated_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()

        result = await resolve_user_by_email(session, "gone@example.com")
        assert result is None
