"""Tests for soft-delete enforcement across auth, bulk ops, and proposals.

Validates that soft-deleted teams, registrations, and users are properly
excluded from queries that previously leaked ghost records.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.bulk import _check_proposal_completion
from tessera.db.models import (
    AcknowledgmentDB,
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.api_key import APIKeyCreate
from tessera.models.enums import (
    AcknowledgmentResponseType,
    APIKeyScope,
    ChangeType,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.services.auth import create_api_key, validate_api_key


@pytest.mark.asyncio
async def test_validate_api_key_rejects_deleted_team(test_session: AsyncSession):
    """API keys belonging to a soft-deleted team must not authenticate.

    This was a critical bug: validate_api_key joined APIKeyDB to TeamDB
    but did not filter on TeamDB.deleted_at, allowing deleted teams'
    keys to remain valid.
    """
    # Create a team and an API key for it
    team = TeamDB(name="soon-deleted-team")
    test_session.add(team)
    await test_session.flush()

    key_data = APIKeyCreate(
        name="test-key",
        team_id=team.id,
        scopes=[APIKeyScope.READ, APIKeyScope.WRITE],
    )
    created_key = await create_api_key(test_session, key_data)
    raw_key = created_key.key
    await test_session.commit()

    # Verify the key works before deletion
    result = await validate_api_key(test_session, raw_key)
    assert result is not None, "Key should validate before team deletion"
    api_key_db, team_db = result
    assert team_db.id == team.id

    # Soft-delete the team
    team.deleted_at = datetime.now(UTC)
    await test_session.commit()

    # The key must now be rejected
    result = await validate_api_key(test_session, raw_key)
    assert result is None, "validate_api_key must reject keys for soft-deleted teams"


@pytest.mark.asyncio
async def test_check_proposal_completion_ignores_deleted_registrations(
    test_session: AsyncSession,
):
    """_check_proposal_completion should not count soft-deleted registrations.

    If a consumer team unregistered (soft-deleted their registration), their
    acknowledgment should no longer be required for proposal auto-approval.
    """
    # Set up: team, asset, contract
    producer = TeamDB(name="producer-team")
    consumer_active = TeamDB(name="active-consumer")
    consumer_deleted = TeamDB(name="deleted-consumer")
    test_session.add_all([producer, consumer_active, consumer_deleted])
    await test_session.flush()

    asset = AssetDB(
        fqn="test.proposal.completion",
        owner_team_id=producer.id,
        environment="production",
    )
    test_session.add(asset)
    await test_session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object", "properties": {"id": {"type": "integer"}}},
        compatibility_mode="backward",
        status=ContractStatus.ACTIVE,
        published_by=producer.id,
    )
    test_session.add(contract)
    await test_session.flush()

    # Create registrations: one active, one soft-deleted
    reg_active = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer_active.id,
        status=RegistrationStatus.ACTIVE,
    )
    reg_deleted = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer_deleted.id,
        status=RegistrationStatus.ACTIVE,
        deleted_at=datetime.now(UTC),  # Soft-deleted
    )
    test_session.add_all([reg_active, reg_deleted])
    await test_session.flush()

    # Create a proposal for the asset
    proposal = ProposalDB(
        asset_id=asset.id,
        proposed_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        change_type=ChangeType.MAJOR,
        status=ProposalStatus.PENDING,
        proposed_by=producer.id,
    )
    test_session.add(proposal)
    await test_session.flush()

    # Only acknowledge from the active consumer
    ack = AcknowledgmentDB(
        proposal_id=proposal.id,
        consumer_team_id=consumer_active.id,
        response=AcknowledgmentResponseType.APPROVED,
    )
    test_session.add(ack)
    await test_session.flush()

    # Check completion: should be True because the only active registration
    # has acknowledged. The soft-deleted registration should not count.
    all_acked, ack_count = await _check_proposal_completion(proposal, test_session)
    assert all_acked is True, "_check_proposal_completion must ignore soft-deleted registrations"
    assert ack_count == 1


@pytest.mark.asyncio
async def test_check_proposal_completion_requires_active_registrations(
    test_session: AsyncSession,
):
    """_check_proposal_completion returns False when active registrations
    have not yet acknowledged.
    """
    producer = TeamDB(name="producer-team-2")
    consumer_a = TeamDB(name="consumer-a")
    consumer_b = TeamDB(name="consumer-b")
    test_session.add_all([producer, consumer_a, consumer_b])
    await test_session.flush()

    asset = AssetDB(
        fqn="test.partial.completion",
        owner_team_id=producer.id,
        environment="production",
    )
    test_session.add(asset)
    await test_session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object"},
        compatibility_mode="backward",
        status=ContractStatus.ACTIVE,
        published_by=producer.id,
    )
    test_session.add(contract)
    await test_session.flush()

    # Two active registrations
    for consumer in [consumer_a, consumer_b]:
        reg = RegistrationDB(
            contract_id=contract.id,
            consumer_team_id=consumer.id,
            status=RegistrationStatus.ACTIVE,
        )
        test_session.add(reg)
    await test_session.flush()

    proposal = ProposalDB(
        asset_id=asset.id,
        proposed_schema={"type": "object"},
        change_type=ChangeType.MAJOR,
        status=ProposalStatus.PENDING,
        proposed_by=producer.id,
    )
    test_session.add(proposal)
    await test_session.flush()

    # Only consumer_a acknowledges
    ack = AcknowledgmentDB(
        proposal_id=proposal.id,
        consumer_team_id=consumer_a.id,
        response=AcknowledgmentResponseType.APPROVED,
    )
    test_session.add(ack)
    await test_session.flush()

    all_acked, ack_count = await _check_proposal_completion(proposal, test_session)
    assert (
        all_acked is False
    ), "Should not be complete when an active registration hasn't acknowledged"
    assert ack_count == 1


@pytest.mark.asyncio
async def test_check_proposal_completion_no_registrations(
    test_session: AsyncSession,
):
    """When there are no active registrations, all are trivially acknowledged."""
    producer = TeamDB(name="producer-no-reg")
    test_session.add(producer)
    await test_session.flush()

    asset = AssetDB(
        fqn="test.no.registrations",
        owner_team_id=producer.id,
        environment="production",
    )
    test_session.add(asset)
    await test_session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object"},
        compatibility_mode="backward",
        status=ContractStatus.ACTIVE,
        published_by=producer.id,
    )
    test_session.add(contract)
    await test_session.flush()

    proposal = ProposalDB(
        asset_id=asset.id,
        proposed_schema={"type": "object"},
        change_type=ChangeType.MAJOR,
        status=ProposalStatus.PENDING,
        proposed_by=producer.id,
    )
    test_session.add(proposal)
    await test_session.flush()

    all_acked, ack_count = await _check_proposal_completion(proposal, test_session)
    assert all_acked is True
    assert ack_count == 0


@pytest.mark.asyncio
async def test_check_proposal_completion_all_registrations_deleted(
    test_session: AsyncSession,
):
    """When ALL registrations are soft-deleted, proposal is trivially complete."""
    producer = TeamDB(name="producer-all-deleted")
    consumer = TeamDB(name="consumer-all-deleted")
    test_session.add_all([producer, consumer])
    await test_session.flush()

    asset = AssetDB(
        fqn="test.all.deleted",
        owner_team_id=producer.id,
        environment="production",
    )
    test_session.add(asset)
    await test_session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object"},
        compatibility_mode="backward",
        status=ContractStatus.ACTIVE,
        published_by=producer.id,
    )
    test_session.add(contract)
    await test_session.flush()

    # Only soft-deleted registrations
    reg = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer.id,
        status=RegistrationStatus.ACTIVE,
        deleted_at=datetime.now(UTC),
    )
    test_session.add(reg)
    await test_session.flush()

    proposal = ProposalDB(
        asset_id=asset.id,
        proposed_schema={"type": "object"},
        change_type=ChangeType.MAJOR,
        status=ProposalStatus.PENDING,
        proposed_by=producer.id,
    )
    test_session.add(proposal)
    await test_session.flush()

    all_acked, ack_count = await _check_proposal_completion(proposal, test_session)
    assert all_acked is True, "All registrations soft-deleted means trivially complete"
    assert ack_count == 0
