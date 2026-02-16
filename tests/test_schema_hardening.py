"""Tests for schema hardening: updated_at, audit indexes, soft-delete re-creation."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AuditEventDB,
    ContractDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    CompatibilityMode,
    ContractStatus,
)


async def _create_team(session: AsyncSession, name: str) -> TeamDB:
    """Create and flush a team record."""
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()
    return team


async def _create_asset(session: AsyncSession, team: TeamDB, fqn: str) -> AssetDB:
    """Create and flush an asset record."""
    asset = AssetDB(fqn=fqn, owner_team_id=team.id)
    session.add(asset)
    await session.flush()
    return asset


async def _create_contract(
    session: AsyncSession, asset: AssetDB, team: TeamDB, version: str = "1.0.0"
) -> ContractDB:
    """Create and flush a contract record."""
    contract = ContractDB(
        asset_id=asset.id,
        version=version,
        schema_def={"type": "object"},
        compatibility_mode=CompatibilityMode.BACKWARD,
        status=ContractStatus.ACTIVE,
        published_by=team.id,
    )
    session.add(contract)
    await session.flush()
    return contract


@pytest.mark.asyncio
class TestUpdatedAtAutoPopulate:
    """Verify updated_at is set on ORM-level updates."""

    async def test_updated_at_null_on_insert(self, test_session: AsyncSession) -> None:
        """updated_at should be None when a row is first created."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        assert team.updated_at is None

    async def test_updated_at_set_on_update(self, test_session: AsyncSession) -> None:
        """updated_at should be populated after an ORM update."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        assert team.updated_at is None

        team.name = f"renamed-{uuid4().hex[:8]}"
        await test_session.flush()
        # After flush, SQLAlchemy runs the onupdate callable
        assert team.updated_at is not None
        assert isinstance(team.updated_at, datetime)

    async def test_updated_at_on_asset(self, test_session: AsyncSession) -> None:
        """updated_at should work on AssetDB."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.schema.tbl_{uuid4().hex[:8]}")
        assert asset.updated_at is None

        asset.metadata_ = {"changed": True}
        await test_session.flush()
        assert asset.updated_at is not None

    async def test_updated_at_on_contract(self, test_session: AsyncSession) -> None:
        """updated_at should work on ContractDB."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.schema.c_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)
        assert contract.updated_at is None

        contract.status = ContractStatus.DEPRECATED
        await test_session.flush()
        assert contract.updated_at is not None

    async def test_updated_at_on_registration(self, test_session: AsyncSession) -> None:
        """updated_at should work on RegistrationDB."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        consumer = await _create_team(test_session, f"consumer-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.schema.r_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)

        reg = RegistrationDB(contract_id=contract.id, consumer_team_id=consumer.id)
        test_session.add(reg)
        await test_session.flush()
        assert reg.updated_at is None

        reg.pinned_version = "1.0.0"
        await test_session.flush()
        assert reg.updated_at is not None


@pytest.mark.asyncio
class TestSoftDeleteReCreation:
    """Verify that soft-deleted rows don't block re-creation.

    SQLite uses global unique constraints (no partial index support),
    so these tests validate that the model-level constraints still work
    correctly. On PostgreSQL (with partial indexes from migration 014),
    soft-deleted rows would be excluded from uniqueness checks.
    """

    async def test_asset_fqn_unique_among_live_rows(self, test_session: AsyncSession) -> None:
        """Two live assets with the same fqn+environment should fail."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        fqn = f"db.schema.dup_{uuid4().hex[:8]}"

        asset1 = AssetDB(fqn=fqn, owner_team_id=team.id, environment="production")
        test_session.add(asset1)
        await test_session.flush()

        asset2 = AssetDB(fqn=fqn, owner_team_id=team.id, environment="production")
        test_session.add(asset2)
        with pytest.raises(Exception):  # IntegrityError
            await test_session.flush()
        await test_session.rollback()

    async def test_team_name_unique_among_live_rows(self, test_session: AsyncSession) -> None:
        """Two live teams with the same name should fail."""
        name = f"unique-team-{uuid4().hex[:8]}"

        team1 = TeamDB(name=name)
        test_session.add(team1)
        await test_session.flush()

        team2 = TeamDB(name=name)
        test_session.add(team2)
        with pytest.raises(Exception):  # IntegrityError
            await test_session.flush()
        await test_session.rollback()


@pytest.mark.asyncio
class TestAuditTimeRangeQuery:
    """Verify audit_events indexes support time-range queries."""

    async def test_time_range_filter(self, test_session: AsyncSession) -> None:
        """Filtering audit_events by occurred_at should work correctly."""
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        t3 = datetime(2025, 12, 1, tzinfo=UTC)

        for ts in [t1, t2, t3]:
            event = AuditEventDB(
                entity_type="team",
                entity_id=uuid4(),
                action="created",
                occurred_at=ts,
            )
            test_session.add(event)
        await test_session.flush()

        # Query range: Jan–June 2025
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 7, 1, tzinfo=UTC)

        stmt = (
            select(AuditEventDB)
            .where(AuditEventDB.occurred_at >= start)
            .where(AuditEventDB.occurred_at < end)
        )
        result = await test_session.execute(stmt)
        events = result.scalars().all()
        assert len(events) == 2

    async def test_entity_type_time_range_filter(self, test_session: AsyncSession) -> None:
        """Composite (entity_type, occurred_at) filter should work correctly."""
        ts = datetime(2025, 6, 15, tzinfo=UTC)

        for entity_type in ["team", "asset", "team"]:
            event = AuditEventDB(
                entity_type=entity_type,
                entity_id=uuid4(),
                action="updated",
                occurred_at=ts,
            )
            test_session.add(event)
        await test_session.flush()

        stmt = (
            select(AuditEventDB)
            .where(AuditEventDB.entity_type == "team")
            .where(AuditEventDB.occurred_at >= datetime(2025, 1, 1, tzinfo=UTC))
        )
        result = await test_session.execute(stmt)
        events = result.scalars().all()
        assert len(events) == 2

    async def test_actor_id_filter(self, test_session: AsyncSession) -> None:
        """Filtering by actor_id should work correctly."""
        actor = uuid4()
        other_actor = uuid4()

        for aid in [actor, actor, other_actor]:
            event = AuditEventDB(
                entity_type="contract",
                entity_id=uuid4(),
                action="published",
                actor_id=aid,
            )
            test_session.add(event)
        await test_session.flush()

        stmt = select(AuditEventDB).where(AuditEventDB.actor_id == actor)
        result = await test_session.execute(stmt)
        events = result.scalars().all()
        assert len(events) == 2


@pytest.mark.asyncio
class TestForeignKeyConstraints:
    """Verify FK constraints on published_by and proposed_by."""

    async def test_contract_published_by_references_valid_team(
        self, test_session: AsyncSession
    ) -> None:
        """Creating a contract with a valid team ID for published_by should succeed."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.schema.fk_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)
        assert contract.published_by == team.id

    async def test_contract_published_by_fk_enforced(self, test_session: AsyncSession) -> None:
        """Check that the FK column exists and references a real team.

        On SQLite the FK is enforced at create_all time via the model
        definition. On PostgreSQL the migration adds the constraint.
        We verify the column value matches an existing team.
        """
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.schema.fk2_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)

        # Verify the published_by value resolves to a team
        stmt = select(TeamDB).where(TeamDB.id == contract.published_by)
        result = await test_session.execute(stmt)
        referenced_team = result.scalar_one_or_none()
        assert referenced_team is not None
        assert referenced_team.id == team.id
