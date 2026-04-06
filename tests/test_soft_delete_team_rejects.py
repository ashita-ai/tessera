"""Tests: asset creation and contract publishing reject soft-deleted owner teams.

Covers issue #447 — verifies that the TeamDB.deleted_at.is_(None) filters
in create_asset (crud.py) and create_contract (publishing.py) correctly
reject requests referencing a soft-deleted team.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import AssetDB, TeamDB

pytestmark = pytest.mark.asyncio


async def _create_team(session: AsyncSession, name: str) -> TeamDB:
    """Insert a team directly into the DB and return it."""
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()
    return team


async def _soft_delete_team(session: AsyncSession, team: TeamDB) -> None:
    """Set deleted_at on a team to simulate soft deletion."""
    team.deleted_at = datetime.now(UTC)
    session.add(team)
    await session.flush()


class TestCreateAssetRejectsSoftDeletedTeam:
    """create_asset should return 404 when owner_team_id references a soft-deleted team."""

    async def test_create_asset_with_soft_deleted_owner_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        team = await _create_team(session, "doomed-team")
        await _soft_delete_team(session, team)

        resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "data.warehouse.orders", "owner_team_id": str(team.id)},
        )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TEAM_NOT_FOUND"

    async def test_create_asset_with_active_team_still_works(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        """Sanity check: an active team should succeed."""
        team = await _create_team(session, "alive-team")
        await session.commit()

        resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "data.warehouse.users", "owner_team_id": str(team.id)},
        )

        assert resp.status_code == 201
        assert resp.json()["owner_team_id"] == str(team.id)


class TestCreateContractRejectsSoftDeletedPublisherTeam:
    """create_contract should return 404 when published_by references a soft-deleted team."""

    async def test_publish_contract_with_soft_deleted_publisher_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        # Create two teams: one to own the asset, one to publish (then delete).
        owner_team = await _create_team(session, "owner-team")
        publisher_team = await _create_team(session, "publisher-team")

        asset = AssetDB(
            fqn="data.warehouse.events",
            owner_team_id=owner_team.id,
            environment="production",
        )
        session.add(asset)
        await session.commit()

        # Soft-delete the publisher team
        await _soft_delete_team(session, publisher_team)
        await session.commit()

        resp = await client.post(
            f"/api/v1/assets/{asset.id}/publish?published_by={publisher_team.id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"event_id": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TEAM_NOT_FOUND"

    async def test_publish_contract_with_active_publisher_team_still_works(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        """Sanity check: publishing with an active team should succeed."""
        team = await _create_team(session, "active-publisher")
        asset = AssetDB(
            fqn="data.warehouse.clicks",
            owner_team_id=team.id,
            environment="production",
        )
        session.add(asset)
        await session.commit()

        resp = await client.post(
            f"/api/v1/assets/{asset.id}/publish?published_by={team.id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"click_id": {"type": "integer"}},
                },
                "compatibility_mode": "backward",
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["contract"]["version"] == "1.0.0"
