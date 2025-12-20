"""Proposals API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import (
    AcknowledgmentDB,
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
    get_session,
)
from tessera.models import Acknowledgment, AcknowledgmentCreate, Contract, Proposal, ProposalCreate
from tessera.models.enums import (
    AcknowledgmentResponseType,
    ChangeType,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.services import (
    log_contract_published,
    log_proposal_acknowledged,
    log_proposal_approved,
    log_proposal_force_approved,
    log_proposal_rejected,
)

router = APIRouter()


class PublishRequest(BaseModel):
    """Request body for publishing a contract from a proposal."""

    version: str
    published_by: UUID


async def check_proposal_completion(
    proposal: ProposalDB,
    session: AsyncSession,
) -> tuple[bool, int]:
    """Check if all registered consumers have acknowledged the proposal.

    Returns a tuple of (all_acknowledged, acknowledged_count).
    """
    # Get the current active contract for this asset
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == proposal.asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # If no active contract, no consumers to acknowledge
    if not current_contract:
        return True, 0

    # Get all active registrations for this contract
    reg_result = await session.execute(
        select(RegistrationDB)
        .where(RegistrationDB.contract_id == current_contract.id)
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
    )
    registrations = reg_result.scalars().all()

    # If no registrations, proposal auto-approves
    if not registrations:
        return True, 0

    # Get all acknowledgments for this proposal
    ack_result = await session.execute(
        select(AcknowledgmentDB).where(AcknowledgmentDB.proposal_id == proposal.id)
    )
    acknowledgments = ack_result.scalars().all()

    # Build sets for comparison
    registered_team_ids = {r.consumer_team_id for r in registrations}
    acknowledged_team_ids = {a.consumer_team_id for a in acknowledgments}

    # Check if all registered consumers have acknowledged
    all_acknowledged = registered_team_ids <= acknowledged_team_ids

    return all_acknowledged, len(acknowledgments)


@router.post("", response_model=Proposal, status_code=201)
async def create_proposal(
    proposal: ProposalCreate,
    asset_id: UUID = Query(..., description="Asset ID for the proposal"),
    proposed_by: UUID = Query(..., description="Team ID of the proposer"),
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Create a new breaking change proposal."""
    # Verify asset exists
    result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # TODO: Implement actual schema diffing to determine change_type and breaking_changes
    db_proposal = ProposalDB(
        asset_id=asset_id,
        proposed_schema=proposal.proposed_schema,
        change_type=ChangeType.MAJOR,  # Default to major until we implement diffing
        breaking_changes=[],
        proposed_by=proposed_by,
    )
    session.add(db_proposal)
    await session.flush()
    await session.refresh(db_proposal)
    return db_proposal


@router.get("")
async def list_proposals(
    asset_id: UUID | None = Query(None, description="Filter by asset ID"),
    status: ProposalStatus | None = Query(None, description="Filter by status"),
    proposed_by: UUID | None = Query(None, description="Filter by proposer team ID"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all proposals with optional filtering and pagination."""
    # Build query with filters
    query = select(ProposalDB)
    if asset_id:
        query = query.where(ProposalDB.asset_id == asset_id)
    if status:
        query = query.where(ProposalDB.status == status)
    if proposed_by:
        query = query.where(ProposalDB.proposed_by == proposed_by)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(ProposalDB.proposed_at.desc())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    proposals = result.scalars().all()

    # Build response with additional info
    proposal_list = []
    for proposal in proposals:
        # Get asset FQN
        asset_result = await session.execute(
            select(AssetDB).where(AssetDB.id == proposal.asset_id)
        )
        asset = asset_result.scalar_one_or_none()

        # Get acknowledgment count
        ack_count_result = await session.execute(
            select(func.count())
            .select_from(AcknowledgmentDB)
            .where(AcknowledgmentDB.proposal_id == proposal.id)
        )
        ack_count = ack_count_result.scalar() or 0

        # Get total consumers (from current active contract registrations)
        consumer_count = 0
        if asset:
            contract_result = await session.execute(
                select(ContractDB)
                .where(ContractDB.asset_id == asset.id)
                .where(ContractDB.status == ContractStatus.ACTIVE)
                .limit(1)
            )
            contract = contract_result.scalar_one_or_none()
            if contract:
                reg_count_result = await session.execute(
                    select(func.count())
                    .select_from(RegistrationDB)
                    .where(RegistrationDB.contract_id == contract.id)
                    .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
                )
                consumer_count = reg_count_result.scalar() or 0

        proposal_list.append({
            "id": str(proposal.id),
            "asset_id": str(proposal.asset_id),
            "asset_fqn": asset.fqn if asset else None,
            "status": str(proposal.status),
            "change_type": str(proposal.change_type),
            "breaking_changes_count": len(proposal.breaking_changes),
            "proposed_by": str(proposal.proposed_by),
            "proposed_at": proposal.proposed_at.isoformat(),
            "acknowledgment_count": ack_count,
            "total_consumers": consumer_count,
        })

    return {
        "proposals": proposal_list,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{proposal_id}", response_model=Proposal)
async def get_proposal(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Get a proposal by ID."""
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.get("/{proposal_id}/status")
async def get_proposal_status(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get detailed status of a proposal including acknowledgment progress."""
    # Get proposal
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Get asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == proposal.asset_id)
    )
    asset = asset_result.scalar_one_or_none()

    # Get proposer team
    proposer_result = await session.execute(
        select(TeamDB).where(TeamDB.id == proposal.proposed_by)
    )
    proposer = proposer_result.scalar_one_or_none()

    # Get all acknowledgments
    ack_result = await session.execute(
        select(AcknowledgmentDB).where(AcknowledgmentDB.proposal_id == proposal_id)
    )
    acknowledgments = ack_result.scalars().all()

    # Build acknowledgment details with team names
    ack_list = []
    acknowledged_team_ids = set()
    blocked_count = 0
    for ack in acknowledgments:
        acknowledged_team_ids.add(ack.consumer_team_id)
        team_result = await session.execute(
            select(TeamDB).where(TeamDB.id == ack.consumer_team_id)
        )
        team = team_result.scalar_one_or_none()
        if str(ack.response) == "blocked":
            blocked_count += 1
        ack_list.append({
            "consumer_team_id": str(ack.consumer_team_id),
            "consumer_team_name": team.name if team else "Unknown",
            "response": str(ack.response),
            "responded_at": ack.responded_at.isoformat(),
            "notes": ack.notes,
        })

    # Get registered consumers (from current active contract)
    pending_consumers = []
    total_consumers = 0
    if asset:
        contract_result = await session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == asset.id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .limit(1)
        )
        contract = contract_result.scalar_one_or_none()
        if contract:
            reg_result = await session.execute(
                select(RegistrationDB)
                .where(RegistrationDB.contract_id == contract.id)
                .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
            )
            registrations = reg_result.scalars().all()
            total_consumers = len(registrations)

            # Find consumers who haven't acknowledged yet
            for reg in registrations:
                if reg.consumer_team_id not in acknowledged_team_ids:
                    team_result = await session.execute(
                        select(TeamDB).where(TeamDB.id == reg.consumer_team_id)
                    )
                    team = team_result.scalar_one_or_none()
                    pending_consumers.append({
                        "team_id": str(reg.consumer_team_id),
                        "team_name": team.name if team else "Unknown",
                        "registered_at": reg.registered_at.isoformat(),
                    })

    return {
        "proposal_id": str(proposal.id),
        "status": str(proposal.status),
        "asset_fqn": asset.fqn if asset else None,
        "change_type": str(proposal.change_type),
        "breaking_changes": proposal.breaking_changes,
        "proposed_by": {
            "team_id": str(proposal.proposed_by),
            "team_name": proposer.name if proposer else "Unknown",
        },
        "proposed_at": proposal.proposed_at.isoformat(),
        "resolved_at": proposal.resolved_at.isoformat() if proposal.resolved_at else None,
        "consumers": {
            "total": total_consumers,
            "acknowledged": len(acknowledgments),
            "pending": len(pending_consumers),
            "blocked": blocked_count,
        },
        "acknowledgments": ack_list,
        "pending_consumers": pending_consumers,
    }


@router.post("/{proposal_id}/acknowledge", response_model=Acknowledgment, status_code=201)
async def acknowledge_proposal(
    proposal_id: UUID,
    ack: AcknowledgmentCreate,
    session: AsyncSession = Depends(get_session),
) -> AcknowledgmentDB:
    """Acknowledge a proposal as a consumer.

    If the acknowledgment response is 'blocked', the proposal is rejected.
    If all registered consumers have acknowledged (non-blocked), the proposal is auto-approved.
    """
    # Verify proposal exists
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    # Check for duplicate acknowledgment from same team
    result = await session.execute(
        select(AcknowledgmentDB)
        .where(AcknowledgmentDB.proposal_id == proposal_id)
        .where(AcknowledgmentDB.consumer_team_id == ack.consumer_team_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="This team has already acknowledged this proposal"
        )

    db_ack = AcknowledgmentDB(
        proposal_id=proposal_id,
        consumer_team_id=ack.consumer_team_id,
        response=ack.response,
        migration_deadline=ack.migration_deadline,
        notes=ack.notes,
    )
    session.add(db_ack)
    await session.flush()
    await session.refresh(db_ack)

    await log_proposal_acknowledged(
        session=session,
        proposal_id=proposal_id,
        consumer_team_id=ack.consumer_team_id,
        response=str(ack.response),
        notes=ack.notes,
    )

    # Handle rejection if consumer blocks
    if ack.response == AcknowledgmentResponseType.BLOCKED:
        proposal.status = ProposalStatus.REJECTED
        proposal.resolved_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(proposal)
        await log_proposal_rejected(
            session=session,
            proposal_id=proposal_id,
            blocked_by=ack.consumer_team_id,
        )
        return db_ack

    # Check for auto-approval (all consumers acknowledged, none blocked)
    all_acknowledged, ack_count = await check_proposal_completion(proposal, session)
    if all_acknowledged:
        proposal.status = ProposalStatus.APPROVED
        proposal.resolved_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(proposal)
        await log_proposal_approved(
            session=session,
            proposal_id=proposal_id,
            acknowledged_count=ack_count,
        )

    return db_ack


@router.post("/{proposal_id}/withdraw", response_model=Proposal)
async def withdraw_proposal(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Withdraw a proposal."""
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    proposal.status = ProposalStatus.WITHDRAWN
    proposal.resolved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(proposal)
    return proposal


@router.post("/{proposal_id}/force", response_model=Proposal)
async def force_proposal(
    proposal_id: UUID,
    actor_id: UUID = Query(..., description="Team ID of the actor forcing approval"),
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Force-approve a proposal (bypassing consumer acknowledgments)."""
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    proposal.status = ProposalStatus.APPROVED
    proposal.resolved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(proposal)

    await log_proposal_force_approved(
        session=session,
        proposal_id=proposal_id,
        actor_id=actor_id,
    )

    return proposal


@router.post("/{proposal_id}/publish")
async def publish_from_proposal(
    proposal_id: UUID,
    publish_request: PublishRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Publish a contract from an approved proposal.

    Only works on proposals with status=APPROVED.
    Creates a new contract with the proposed schema and deprecates the old one.
    """
    # Get the proposal
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish from proposal with status '{proposal.status}'. "
            "Proposal must be approved first."
        )

    # Get the asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == proposal.asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get the current active contract to deprecate
    current_contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == proposal.asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = current_contract_result.scalar_one_or_none()

    # Create new contract from the proposal
    new_contract = ContractDB(
        asset_id=proposal.asset_id,
        version=publish_request.version,
        schema_def=proposal.proposed_schema,
        compatibility_mode=current_contract.compatibility_mode if current_contract else None,
        guarantees=current_contract.guarantees if current_contract else None,
        published_by=publish_request.published_by,
    )
    session.add(new_contract)

    # Deprecate old contract
    if current_contract:
        current_contract.status = ContractStatus.DEPRECATED

    await session.flush()
    await session.refresh(new_contract)

    await log_contract_published(
        session=session,
        contract_id=new_contract.id,
        publisher_id=publish_request.published_by,
        version=new_contract.version,
        change_type=str(proposal.change_type),
    )

    return {
        "action": "published",
        "proposal_id": str(proposal_id),
        "contract": Contract.model_validate(new_contract).model_dump(),
        "deprecated_contract_id": str(current_contract.id) if current_contract else None,
    }
