"""Pending proposals endpoint for team inbox.

Provides a single query for consumer agents to discover proposals
awaiting their team's acknowledgment.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import ErrorCode, ForbiddenError
from tessera.api.rate_limit import limit_read
from tessera.db.database import get_session
from tessera.db.models import (
    AcknowledgmentDB,
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    APIKeyScope,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
)

router = APIRouter()


class PendingProposalItem(BaseModel):
    """A single pending proposal awaiting team acknowledgment."""

    proposal_id: UUID
    asset_id: UUID
    asset_fqn: str
    proposed_by_team: str
    proposed_at: datetime
    expires_at: datetime | None
    breaking_changes_summary: list[str]
    total_consumers: int
    acknowledged_count: int
    your_team_status: str


class PendingProposalsResponse(BaseModel):
    """Response from the pending proposals endpoint."""

    pending_proposals: list[PendingProposalItem]
    total: int


@router.get("/proposals/pending/{team_id}", response_model=PendingProposalsResponse)
@limit_read
async def get_pending_proposals(
    request: Request,
    team_id: UUID,
    auth: Auth,
    status: str = Query("PENDING", description="Proposal status filter"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PendingProposalsResponse:
    """Get proposals pending acknowledgment for a team.

    Returns proposals where this team has an active consumer registration
    on the affected asset but has not yet acknowledged the proposal.

    Team-scoped: API key's team must match team_id, or the key must have ADMIN scope.
    """
    # Authorization: team must match or be admin
    if auth.team_id != team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot view pending proposals for other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Validate status
    try:
        proposal_status = ProposalStatus(status)
    except ValueError:
        proposal_status = ProposalStatus.PENDING

    now = datetime.now(UTC)

    # Find proposals where:
    # 1. Status matches (default PENDING)
    # 2. Not expired
    # 3. This team has an active registration on a contract for the proposal's asset
    # 4. This team has NOT already acknowledged the proposal
    #
    # This is a single query with joins to avoid N+1.

    # Subquery: proposal IDs this team has already acknowledged
    acknowledged_subq = (
        select(AcknowledgmentDB.proposal_id)
        .where(AcknowledgmentDB.consumer_team_id == team_id)
        .correlate(ProposalDB)
        .scalar_subquery()
    )

    # Main query: proposals affecting assets where this team has registrations
    proposals_query = (
        select(
            ProposalDB,
            AssetDB.fqn.label("asset_fqn"),
            TeamDB.name.label("proposer_team_name"),
        )
        .join(AssetDB, ProposalDB.asset_id == AssetDB.id)
        .join(TeamDB, ProposalDB.proposed_by == TeamDB.id)
        # Join to find contracts for this asset that this team is registered on
        .join(ContractDB, ContractDB.asset_id == AssetDB.id)
        .join(
            RegistrationDB,
            (RegistrationDB.contract_id == ContractDB.id)
            & (RegistrationDB.consumer_team_id == team_id)
            & (RegistrationDB.deleted_at.is_(None))
            & (RegistrationDB.status == RegistrationStatus.ACTIVE),
        )
        .where(ProposalDB.status == proposal_status)
        .where(AssetDB.deleted_at.is_(None))
        # Exclude expired proposals
        .where((ProposalDB.expires_at.is_(None)) | (ProposalDB.expires_at > now))
        # Exclude proposals this team has already acknowledged
        .where(ProposalDB.id.notin_(acknowledged_subq))
        # Deduplicate (team may have registrations on multiple contracts for same asset)
        .group_by(ProposalDB.id, AssetDB.fqn, TeamDB.name)
        .order_by(ProposalDB.proposed_at.desc())
    )

    # Count total before pagination
    count_query = select(func.count()).select_from(
        proposals_query.with_only_columns(ProposalDB.id).subquery()
    )
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination
    proposals_query = proposals_query.limit(limit).offset(offset)
    result = await session.execute(proposals_query)
    rows = result.all()

    # Build response with consumer counts
    pending_items: list[PendingProposalItem] = []
    for proposal, asset_fqn, proposer_team_name in rows:
        # Count total consumers (registrations on this asset's active contracts)
        consumer_count_result = await session.execute(
            select(func.count(func.distinct(RegistrationDB.consumer_team_id)))
            .join(ContractDB, RegistrationDB.contract_id == ContractDB.id)
            .where(ContractDB.asset_id == proposal.asset_id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .where(RegistrationDB.deleted_at.is_(None))
            .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        )
        total_consumers = consumer_count_result.scalar() or 0

        # Count acknowledgments for this proposal
        ack_count_result = await session.execute(
            select(func.count(AcknowledgmentDB.id)).where(
                AcknowledgmentDB.proposal_id == proposal.id
            )
        )
        acknowledged_count = ack_count_result.scalar() or 0

        # Summarize breaking changes
        breaking_summary = [
            change.get("message", str(change)) for change in (proposal.breaking_changes or [])
        ]

        pending_items.append(
            PendingProposalItem(
                proposal_id=proposal.id,
                asset_id=proposal.asset_id,
                asset_fqn=asset_fqn,
                proposed_by_team=proposer_team_name,
                proposed_at=proposal.proposed_at,
                expires_at=proposal.expires_at,
                breaking_changes_summary=breaking_summary,
                total_consumers=total_consumers,
                acknowledged_count=acknowledged_count,
                your_team_status="AWAITING_RESPONSE",
            )
        )

    return PendingProposalsResponse(
        pending_proposals=pending_items,
        total=total,
    )
