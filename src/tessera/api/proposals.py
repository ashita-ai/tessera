"""Proposals API endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AcknowledgmentDB, AssetDB, ProposalDB, get_session
from tessera.models import Acknowledgment, AcknowledgmentCreate, Proposal, ProposalCreate
from tessera.models.enums import ChangeType, ProposalStatus

router = APIRouter()


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


@router.post("/{proposal_id}/acknowledge", response_model=Acknowledgment, status_code=201)
async def acknowledge_proposal(
    proposal_id: UUID,
    ack: AcknowledgmentCreate,
    session: AsyncSession = Depends(get_session),
) -> AcknowledgmentDB:
    """Acknowledge a proposal as a consumer."""
    # Verify proposal exists
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Proposal is not pending")

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
    proposal.resolved_at = datetime.utcnow()
    await session.flush()
    await session.refresh(proposal)
    return proposal


@router.post("/{proposal_id}/force", response_model=Proposal)
async def force_proposal(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Force-approve a proposal (bypassing consumer acknowledgments)."""
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    # TODO: Log this force-publish to audit table
    proposal.status = ProposalStatus.APPROVED
    proposal.resolved_at = datetime.utcnow()
    await session.flush()
    await session.refresh(proposal)
    return proposal
