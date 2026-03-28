"""Tests for batch fetch utilities."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, TeamDB
from tessera.services.batch import (
    fetch_asset_counts_by_team,
    fetch_asset_counts_by_user,
    fetch_team_names,
)

pytestmark = pytest.mark.asyncio


async def _create_team(session: AsyncSession, name: str) -> TeamDB:
    """Create a team and flush to get its ID."""
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()
    return team


async def _create_asset(
    session: AsyncSession,
    fqn: str,
    owner_team_id: ...,
    owner_user_id: ... = None,
) -> AssetDB:
    """Create an asset and flush to get its ID."""
    asset = AssetDB(fqn=fqn, owner_team_id=owner_team_id, owner_user_id=owner_user_id)
    session.add(asset)
    await session.flush()
    return asset


class TestFetchAssetCountsByTeam:
    """Tests for fetch_asset_counts_by_team."""

    async def test_empty_input_returns_empty_dict(self, test_session: AsyncSession) -> None:
        """Passing an empty list of team IDs returns an empty dict."""
        result = await fetch_asset_counts_by_team(test_session, [])
        assert result == {}

    async def test_team_with_no_assets(self, test_session: AsyncSession) -> None:
        """A team with no assets does not appear in the result."""
        team = await _create_team(test_session, "empty-team")
        result = await fetch_asset_counts_by_team(test_session, [team.id])
        assert team.id not in result

    async def test_single_team_with_assets(self, test_session: AsyncSession) -> None:
        """Correctly counts assets for a single team."""
        team = await _create_team(test_session, "asset-team")
        await _create_asset(test_session, "db.schema.t1", team.id)
        await _create_asset(test_session, "db.schema.t2", team.id)

        result = await fetch_asset_counts_by_team(test_session, [team.id])
        assert result[team.id] == 2

    async def test_multiple_teams(self, test_session: AsyncSession) -> None:
        """Counts are correct across multiple teams in a single query."""
        team_a = await _create_team(test_session, "team-a")
        team_b = await _create_team(test_session, "team-b")
        await _create_asset(test_session, "db.schema.a1", team_a.id)
        await _create_asset(test_session, "db.schema.b1", team_b.id)
        await _create_asset(test_session, "db.schema.b2", team_b.id)
        await _create_asset(test_session, "db.schema.b3", team_b.id)

        result = await fetch_asset_counts_by_team(test_session, [team_a.id, team_b.id])
        assert result[team_a.id] == 1
        assert result[team_b.id] == 3

    async def test_excludes_soft_deleted_assets(self, test_session: AsyncSession) -> None:
        """Soft-deleted assets are not counted."""
        from datetime import UTC, datetime

        team = await _create_team(test_session, "del-team")
        asset = await _create_asset(test_session, "db.schema.deleted", team.id)
        asset.deleted_at = datetime.now(UTC)
        await _create_asset(test_session, "db.schema.alive", team.id)
        await test_session.flush()

        result = await fetch_asset_counts_by_team(test_session, [team.id])
        assert result[team.id] == 1

    async def test_unknown_team_ids_absent(self, test_session: AsyncSession) -> None:
        """Team IDs with no matching assets do not appear in the dict."""
        bogus_id = uuid4()
        result = await fetch_asset_counts_by_team(test_session, [bogus_id])
        assert bogus_id not in result


class TestFetchAssetCountsByUser:
    """Tests for fetch_asset_counts_by_user."""

    async def test_empty_input_returns_empty_dict(self, test_session: AsyncSession) -> None:
        """Passing an empty list of user IDs returns an empty dict."""
        result = await fetch_asset_counts_by_user(test_session, [])
        assert result == {}

    async def test_user_with_assets(self, test_session: AsyncSession) -> None:
        """Correctly counts assets owned by a specific user."""
        team = await _create_team(test_session, "user-team")
        user_id = uuid4()
        await _create_asset(test_session, "db.schema.u1", team.id, owner_user_id=user_id)
        await _create_asset(test_session, "db.schema.u2", team.id, owner_user_id=user_id)

        result = await fetch_asset_counts_by_user(test_session, [user_id])
        assert result[user_id] == 2

    async def test_excludes_soft_deleted_assets(self, test_session: AsyncSession) -> None:
        """Soft-deleted assets are not counted for users."""
        from datetime import UTC, datetime

        team = await _create_team(test_session, "user-del-team")
        user_id = uuid4()
        asset = await _create_asset(test_session, "db.schema.ud1", team.id, owner_user_id=user_id)
        asset.deleted_at = datetime.now(UTC)
        await test_session.flush()

        result = await fetch_asset_counts_by_user(test_session, [user_id])
        assert user_id not in result


class TestFetchTeamNames:
    """Tests for fetch_team_names."""

    async def test_empty_input_returns_empty_dict(self, test_session: AsyncSession) -> None:
        """Passing an empty list of team IDs returns an empty dict."""
        result = await fetch_team_names(test_session, [])
        assert result == {}

    async def test_single_team(self, test_session: AsyncSession) -> None:
        """Returns the correct name for a single team."""
        team = await _create_team(test_session, "my-team")
        result = await fetch_team_names(test_session, [team.id])
        assert result[team.id] == "my-team"

    async def test_multiple_teams(self, test_session: AsyncSession) -> None:
        """Returns correct names for multiple teams in a single query."""
        team_a = await _create_team(test_session, "alpha")
        team_b = await _create_team(test_session, "bravo")

        result = await fetch_team_names(test_session, [team_a.id, team_b.id])
        assert result[team_a.id] == "alpha"
        assert result[team_b.id] == "bravo"

    async def test_excludes_soft_deleted_teams(self, test_session: AsyncSession) -> None:
        """Soft-deleted teams are not returned."""
        from datetime import UTC, datetime

        team = await _create_team(test_session, "deleted-team")
        team.deleted_at = datetime.now(UTC)
        await test_session.flush()

        result = await fetch_team_names(test_session, [team.id])
        assert team.id not in result

    async def test_unknown_team_ids_absent(self, test_session: AsyncSession) -> None:
        """Unknown team IDs do not appear in the result."""
        bogus_id = uuid4()
        result = await fetch_team_names(test_session, [bogus_id])
        assert bogus_id not in result
