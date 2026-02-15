"""Tests for unique constraint enforcement on registrations, acknowledgments, and dependencies."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AcknowledgmentDB,
    AssetDB,
    AssetDependencyDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    AcknowledgmentResponseType,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    DependencyType,
    ProposalStatus,
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


async def _create_contract(session: AsyncSession, asset: AssetDB, team: TeamDB) -> ContractDB:
    """Create and flush a contract record."""
    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object"},
        compatibility_mode=CompatibilityMode.BACKWARD,
        status=ContractStatus.ACTIVE,
        published_by=team.id,
    )
    session.add(contract)
    await session.flush()
    return contract


async def _create_proposal(session: AsyncSession, asset: AssetDB, team: TeamDB) -> ProposalDB:
    """Create and flush a proposal record."""
    proposal = ProposalDB(
        asset_id=asset.id,
        proposed_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        change_type=ChangeType.MAJOR,
        breaking_changes=[],
        proposed_by=team.id,
        status=ProposalStatus.PENDING,
    )
    session.add(proposal)
    await session.flush()
    return proposal


@pytest.mark.asyncio
class TestRegistrationUniqueConstraint:
    """Verify uq_registration_contract_consumer."""

    async def test_duplicate_registration_raises(self, test_session: AsyncSession) -> None:
        """Inserting two registrations for the same (contract, consumer_team) should fail."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        consumer = await _create_team(test_session, f"consumer-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.public.orders_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)

        reg1 = RegistrationDB(contract_id=contract.id, consumer_team_id=consumer.id)
        test_session.add(reg1)
        await test_session.flush()

        reg2 = RegistrationDB(contract_id=contract.id, consumer_team_id=consumer.id)
        test_session.add(reg2)
        with pytest.raises(IntegrityError):
            await test_session.flush()

        await test_session.rollback()

    async def test_distinct_registrations_succeed(self, test_session: AsyncSession) -> None:
        """Different consumers on the same contract should succeed."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        consumer_a = await _create_team(test_session, f"consumer-a-{uuid4().hex[:8]}")
        consumer_b = await _create_team(test_session, f"consumer-b-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.public.users_{uuid4().hex[:8]}")
        contract = await _create_contract(test_session, asset, team)

        test_session.add(RegistrationDB(contract_id=contract.id, consumer_team_id=consumer_a.id))
        test_session.add(RegistrationDB(contract_id=contract.id, consumer_team_id=consumer_b.id))
        await test_session.flush()


@pytest.mark.asyncio
class TestAcknowledgmentUniqueConstraint:
    """Verify uq_acknowledgment_proposal_consumer."""

    async def test_duplicate_acknowledgment_raises(self, test_session: AsyncSession) -> None:
        """Inserting two acknowledgments for the same (proposal, consumer_team) should fail."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        consumer = await _create_team(test_session, f"consumer-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.public.events_{uuid4().hex[:8]}")
        proposal = await _create_proposal(test_session, asset, team)

        ack1 = AcknowledgmentDB(
            proposal_id=proposal.id,
            consumer_team_id=consumer.id,
            response=AcknowledgmentResponseType.APPROVED,
        )
        test_session.add(ack1)
        await test_session.flush()

        ack2 = AcknowledgmentDB(
            proposal_id=proposal.id,
            consumer_team_id=consumer.id,
            response=AcknowledgmentResponseType.APPROVED,
        )
        test_session.add(ack2)
        with pytest.raises(IntegrityError):
            await test_session.flush()

        await test_session.rollback()

    async def test_distinct_acknowledgments_succeed(self, test_session: AsyncSession) -> None:
        """Different consumers acknowledging the same proposal should succeed."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        consumer_a = await _create_team(test_session, f"consumer-a-{uuid4().hex[:8]}")
        consumer_b = await _create_team(test_session, f"consumer-b-{uuid4().hex[:8]}")
        asset = await _create_asset(test_session, team, f"db.public.items_{uuid4().hex[:8]}")
        proposal = await _create_proposal(test_session, asset, team)

        test_session.add(
            AcknowledgmentDB(
                proposal_id=proposal.id,
                consumer_team_id=consumer_a.id,
                response=AcknowledgmentResponseType.APPROVED,
            )
        )
        test_session.add(
            AcknowledgmentDB(
                proposal_id=proposal.id,
                consumer_team_id=consumer_b.id,
                response=AcknowledgmentResponseType.APPROVED,
            )
        )
        await test_session.flush()


@pytest.mark.asyncio
class TestDependencyUniqueConstraint:
    """Verify uq_dependency_edge."""

    async def test_duplicate_dependency_raises(self, test_session: AsyncSession) -> None:
        """Inserting the same dependency edge twice should fail."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset_a = await _create_asset(test_session, team, f"db.public.a_{uuid4().hex[:8]}")
        asset_b = await _create_asset(test_session, team, f"db.public.b_{uuid4().hex[:8]}")

        dep1 = AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_b.id,
            dependency_type=DependencyType.CONSUMES,
        )
        test_session.add(dep1)
        await test_session.flush()

        dep2 = AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_b.id,
            dependency_type=DependencyType.CONSUMES,
        )
        test_session.add(dep2)
        with pytest.raises(IntegrityError):
            await test_session.flush()

        await test_session.rollback()

    async def test_distinct_dependencies_succeed(self, test_session: AsyncSession) -> None:
        """Different dependency types for the same asset pair should succeed."""
        team = await _create_team(test_session, f"team-{uuid4().hex[:8]}")
        asset_a = await _create_asset(test_session, team, f"db.public.c_{uuid4().hex[:8]}")
        asset_b = await _create_asset(test_session, team, f"db.public.d_{uuid4().hex[:8]}")

        test_session.add(
            AssetDependencyDB(
                dependent_asset_id=asset_a.id,
                dependency_asset_id=asset_b.id,
                dependency_type=DependencyType.CONSUMES,
            )
        )
        test_session.add(
            AssetDependencyDB(
                dependent_asset_id=asset_a.id,
                dependency_asset_id=asset_b.id,
                dependency_type=DependencyType.REFERENCES,
            )
        )
        await test_session.flush()
