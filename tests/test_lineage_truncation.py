"""Tests for lineage traversal truncation and result capping."""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.impact import get_downstream_assets_recursive
from tessera.db.models import AssetDB, AssetDependencyDB, TeamDB
from tessera.models.enums import DependencyType

pytestmark = pytest.mark.asyncio


async def _create_team(session: AsyncSession, name: str = "test-team") -> TeamDB:
    """Create and return a team."""
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()
    await session.refresh(team)
    return team


async def _create_asset(session: AsyncSession, fqn: str, team_id: UUID) -> AssetDB:
    """Create and return an asset."""
    asset = AssetDB(fqn=fqn, owner_team_id=team_id)
    session.add(asset)
    await session.flush()
    await session.refresh(asset)
    return asset


async def _add_dependency(
    session: AsyncSession,
    dependent_id: UUID,
    dependency_id: UUID,
) -> None:
    """Create a dependency relationship (dependent depends ON dependency)."""
    dep = AssetDependencyDB(
        dependent_asset_id=dependent_id,
        dependency_asset_id=dependency_id,
        dependency_type=DependencyType.CONSUMES,
    )
    session.add(dep)
    await session.flush()


class TestLineageTruncation:
    """Tests for get_downstream_assets_recursive result capping."""

    async def test_no_truncation_small_graph(self, test_session: AsyncSession):
        """Small graph returns all results without truncation."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.table", team.id)
        child1 = await _create_asset(test_session, "child1.table", team.id)
        child2 = await _create_asset(test_session, "child2.table", team.id)

        # child1 and child2 depend on root (root → child1, root → child2)
        await _add_dependency(test_session, child1.id, root.id)
        await _add_dependency(test_session, child2.id, root.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5
        )

        assert truncated is False
        assert len(results) == 2
        result_ids = {r[0].id for r in results}
        assert child1.id in result_ids
        assert child2.id in result_ids

    async def test_empty_graph(self, test_session: AsyncSession):
        """Asset with no dependents returns empty results."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "lonely.table", team.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5
        )

        assert truncated is False
        assert len(results) == 0

    async def test_truncation_at_max_results(self, test_session: AsyncSession):
        """Results are truncated when max_results is exceeded."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.wide_table", team.id)

        # Create 10 children, but cap at 5
        for i in range(10):
            child = await _create_asset(test_session, f"child_{i}.table", team.id)
            await _add_dependency(test_session, child.id, root.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5, max_results=5
        )

        assert truncated is True
        assert len(results) == 5

    async def test_truncation_respects_custom_max(self, test_session: AsyncSession):
        """Custom max_results is honored."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.custom_cap", team.id)

        for i in range(20):
            child = await _create_asset(test_session, f"cap_child_{i}.table", team.id)
            await _add_dependency(test_session, child.id, root.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5, max_results=3
        )

        assert truncated is True
        assert len(results) == 3

    async def test_depth_limited_traversal(self, test_session: AsyncSession):
        """Multi-level chain respects depth limit."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.chain", team.id)
        level1 = await _create_asset(test_session, "level1.chain", team.id)
        level2 = await _create_asset(test_session, "level2.chain", team.id)
        level3 = await _create_asset(test_session, "level3.chain", team.id)

        await _add_dependency(test_session, level1.id, root.id)
        await _add_dependency(test_session, level2.id, level1.id)
        await _add_dependency(test_session, level3.id, level2.id)

        # Depth=2 should get level1 and level2 but not level3
        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=2
        )

        assert truncated is False
        assert len(results) == 2
        result_fqns = {r[0].fqn for r in results}
        assert "level1.chain" in result_fqns
        assert "level2.chain" in result_fqns
        assert "level3.chain" not in result_fqns

    async def test_cycle_detection(self, test_session: AsyncSession):
        """Cycles in the dependency graph don't cause infinite loops."""
        team = await _create_team(test_session)
        a = await _create_asset(test_session, "cycle.a", team.id)
        b = await _create_asset(test_session, "cycle.b", team.id)
        c = await _create_asset(test_session, "cycle.c", team.id)

        # a → b → c → a (cycle)
        await _add_dependency(test_session, b.id, a.id)
        await _add_dependency(test_session, c.id, b.id)
        await _add_dependency(test_session, a.id, c.id)

        results, truncated = await get_downstream_assets_recursive(test_session, a.id, max_depth=10)

        # Should find b and c but not revisit a
        assert truncated is False
        assert len(results) == 2
        result_ids = {r[0].id for r in results}
        assert a.id not in result_ids

    async def test_depth_reported_correctly(self, test_session: AsyncSession):
        """Each result includes its correct depth from the root."""
        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.depth_check", team.id)
        child = await _create_asset(test_session, "child.depth_check", team.id)
        grandchild = await _create_asset(test_session, "grandchild.depth_check", team.id)

        await _add_dependency(test_session, child.id, root.id)
        await _add_dependency(test_session, grandchild.id, child.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5
        )

        assert len(results) == 2
        by_fqn = {r[0].fqn: r[2] for r in results}
        assert by_fqn["child.depth_check"] == 1
        assert by_fqn["grandchild.depth_check"] == 2

    async def test_soft_deleted_assets_excluded(self, test_session: AsyncSession):
        """Soft-deleted downstream assets are not returned."""
        from datetime import UTC, datetime

        team = await _create_team(test_session)
        root = await _create_asset(test_session, "root.softdel", team.id)
        active_child = await _create_asset(test_session, "active.child", team.id)
        deleted_child = await _create_asset(test_session, "deleted.child", team.id)

        # Soft-delete one child
        deleted_child.deleted_at = datetime.now(UTC)
        await test_session.flush()

        await _add_dependency(test_session, active_child.id, root.id)
        await _add_dependency(test_session, deleted_child.id, root.id)

        results, truncated = await get_downstream_assets_recursive(
            test_session, root.id, max_depth=5
        )

        assert len(results) == 1
        assert results[0][0].fqn == "active.child"
