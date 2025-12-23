"""Proposals API endpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from tessera.api.rate_limit import limit_read, limit_write
from tessera.db import (
    AcknowledgmentDB,
    AssetDB,
    AuditRunDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
    UserDB,
    get_session,
)
from tessera.models import Acknowledgment, AcknowledgmentCreate, Contract, Proposal
from tessera.models.enums import (
    AcknowledgmentResponseType,
    APIKeyScope,
    AuditRunStatus,
    CompatibilityMode,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.models.webhook import WebhookEventType
from tessera.services import (
    log_contract_published,
    log_proposal_acknowledged,
    log_proposal_approved,
    log_proposal_force_approved,
    log_proposal_rejected,
)
from tessera.services.schema_validator import SchemaValidationError, validate_schema_or_raise
from tessera.services.slack import notify_proposal_acknowledged, notify_proposal_approved
from tessera.services.webhooks import (
    send_contract_published,
    send_proposal_acknowledged,
    send_proposal_status_change,
)

router = APIRouter()


async def _get_asset_audit_info(session: AsyncSession, asset_id: UUID) -> dict[str, Any] | None:
    """Get the most recent audit run info for an asset.

    Returns a dict with audit status info, or None if no audits exist.
    """
    from sqlalchemy import desc

    result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .order_by(desc(AuditRunDB.run_at))
        .limit(1)
    )
    audit_run = result.scalar_one_or_none()
    if not audit_run:
        return None
    return {
        "status": audit_run.status.value,
        "guarantees_failed": audit_run.guarantees_failed,
        "run_at": audit_run.run_at.isoformat(),
        "triggered_by": audit_run.triggered_by,
        "is_passing": audit_run.status == AuditRunStatus.PASSED,
    }


class PublishRequest(BaseModel):
    """Request body for publishing a contract from a proposal."""

    version: str
    published_by: UUID
    published_by_user_id: UUID | None = None


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


@router.get("")
@limit_read
async def list_proposals(
    request: Request,
    auth: Auth,
    asset_id: UUID | None = Query(None, description="Filter by asset ID"),
    status: ProposalStatus | None = Query(None, description="Filter by status"),
    proposed_by: UUID | None = Query(None, description="Filter by proposer team ID"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all proposals with optional filtering and pagination.

    Requires read scope.
    """
    # Build base query with filters
    base_query = select(ProposalDB)
    if asset_id:
        base_query = base_query.where(ProposalDB.asset_id == asset_id)
    if status:
        base_query = base_query.where(ProposalDB.status == status)
    if proposed_by:
        base_query = base_query.where(ProposalDB.proposed_by == proposed_by)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Main query: join proposals with assets in single query (fixes N+1)
    query = select(ProposalDB, AssetDB).join(AssetDB, ProposalDB.asset_id == AssetDB.id)
    if asset_id:
        query = query.where(ProposalDB.asset_id == asset_id)
    if status:
        query = query.where(ProposalDB.status == status)
    if proposed_by:
        query = query.where(ProposalDB.proposed_by == proposed_by)
    query = query.order_by(ProposalDB.proposed_at.desc()).limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    if not rows:
        return {"results": [], "total": total, "limit": limit, "offset": offset}

    # Collect proposal IDs and asset IDs for batch queries
    proposal_ids = [p.id for p, _ in rows]
    asset_ids = [a.id for _, a in rows]

    # Batch fetch acknowledgment counts (fixes N+1)
    ack_counts_result = await session.execute(
        select(AcknowledgmentDB.proposal_id, func.count(AcknowledgmentDB.id))
        .where(AcknowledgmentDB.proposal_id.in_(proposal_ids))
        .group_by(AcknowledgmentDB.proposal_id)
    )
    ack_counts: dict[UUID, int] = {pid: cnt for pid, cnt in ack_counts_result.all()}

    # Batch fetch active contracts for all assets (fixes N+1)
    # Fetch all active contracts and pick most recent per asset in Python
    # (avoids DISTINCT ON which is PostgreSQL-specific)
    active_contracts_result = await session.execute(
        select(ContractDB.id, ContractDB.asset_id, ContractDB.published_at)
        .where(ContractDB.asset_id.in_(asset_ids))
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
    )
    # Map asset_id -> contract_id (keep only the most recent per asset)
    asset_contract_map: dict[UUID, UUID] = {}
    for contract_id, asset_id, _ in active_contracts_result.all():
        if asset_id not in asset_contract_map:
            asset_contract_map[asset_id] = contract_id

    # Batch fetch consumer counts for active contracts (fixes N+1)
    consumer_counts: dict[UUID, int] = {}
    contract_ids = list(asset_contract_map.values())
    if contract_ids:
        consumer_counts_result = await session.execute(
            select(RegistrationDB.contract_id, func.count(RegistrationDB.id))
            .where(RegistrationDB.contract_id.in_(contract_ids))
            .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
            .group_by(RegistrationDB.contract_id)
        )
        consumer_counts = {cid: cnt for cid, cnt in consumer_counts_result.all()}

    # Build response
    proposal_list = []
    for proposal, asset in rows:
        contract_id = asset_contract_map.get(asset.id)
        consumer_count = consumer_counts.get(contract_id, 0) if contract_id else 0

        proposal_list.append(
            {
                "id": str(proposal.id),
                "asset_id": str(proposal.asset_id),
                "asset_fqn": asset.fqn,
                "status": str(proposal.status),
                "change_type": str(proposal.change_type),
                "breaking_changes_count": len(proposal.breaking_changes),
                "proposed_by": str(proposal.proposed_by),
                "proposed_at": proposal.proposed_at.isoformat(),
                "acknowledgment_count": ack_counts.get(proposal.id, 0),
                "total_consumers": consumer_count,
            }
        )

    return {
        "results": proposal_list,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{proposal_id}", response_model=Proposal)
@limit_read
async def get_proposal(
    request: Request,
    auth: Auth,
    proposal_id: UUID,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Get a proposal by ID.

    Requires read scope.
    """
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")
    return proposal


@router.get("/{proposal_id}/status")
@limit_read
async def get_proposal_status(
    request: Request,
    auth: Auth,
    proposal_id: UUID,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get detailed status of a proposal including acknowledgment progress.

    Requires read scope.
    """
    # Get proposal with asset in single query
    result = await session.execute(
        select(ProposalDB, AssetDB)
        .join(AssetDB, ProposalDB.asset_id == AssetDB.id)
        .where(ProposalDB.id == proposal_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")
    proposal, asset = row

    # Get all acknowledgments
    ack_result = await session.execute(
        select(AcknowledgmentDB).where(AcknowledgmentDB.proposal_id == proposal_id)
    )
    acknowledgments = ack_result.scalars().all()

    # Get registered consumers (from current active contract)
    registrations: list[RegistrationDB] = []
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset.id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    contract = contract_result.scalar_one_or_none()
    if contract:
        reg_result = await session.execute(
            select(RegistrationDB)
            .where(RegistrationDB.contract_id == contract.id)
            .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        )
        registrations = list(reg_result.scalars().all())

    # Collect all team IDs we need to look up (fixes N+1)
    team_ids_to_lookup = {proposal.proposed_by}
    team_ids_to_lookup.update(ack.consumer_team_id for ack in acknowledgments)
    team_ids_to_lookup.update(reg.consumer_team_id for reg in registrations)

    # Collect all user IDs we need to look up
    user_ids_to_lookup: set[UUID] = set()
    if proposal.proposed_by_user_id:
        user_ids_to_lookup.add(proposal.proposed_by_user_id)
    for ack in acknowledgments:
        if ack.acknowledged_by_user_id:
            user_ids_to_lookup.add(ack.acknowledged_by_user_id)

    # Batch fetch all teams in single query
    teams_result = await session.execute(select(TeamDB).where(TeamDB.id.in_(team_ids_to_lookup)))
    teams_map: dict[UUID, TeamDB] = {t.id: t for t in teams_result.scalars().all()}

    # Batch fetch all users in single query
    users_map: dict[UUID, UserDB] = {}
    if user_ids_to_lookup:
        users_result = await session.execute(
            select(UserDB).where(UserDB.id.in_(user_ids_to_lookup))
        )
        users_map = {u.id: u for u in users_result.scalars().all()}

    # Build acknowledgment details
    ack_list = []
    acknowledged_team_ids = set()
    blocked_count = 0
    for ack in acknowledgments:
        acknowledged_team_ids.add(ack.consumer_team_id)
        team = teams_map.get(ack.consumer_team_id)
        user = users_map.get(ack.acknowledged_by_user_id) if ack.acknowledged_by_user_id else None
        if str(ack.response) == "blocked":
            blocked_count += 1
        ack_list.append(
            {
                "consumer_team_id": str(ack.consumer_team_id),
                "consumer_team_name": team.name if team else "Unknown",
                "acknowledged_by_user_id": str(ack.acknowledged_by_user_id)
                if ack.acknowledged_by_user_id
                else None,
                "acknowledged_by_user_name": user.name if user else None,
                "response": str(ack.response),
                "responded_at": ack.responded_at.isoformat(),
                "notes": ack.notes,
            }
        )

    # Find consumers who haven't acknowledged yet
    pending_consumers = []
    for reg in registrations:
        if reg.consumer_team_id not in acknowledged_team_ids:
            team = teams_map.get(reg.consumer_team_id)
            pending_consumers.append(
                {
                    "team_id": str(reg.consumer_team_id),
                    "team_name": team.name if team else "Unknown",
                    "registered_at": reg.registered_at.isoformat(),
                }
            )

    proposer = teams_map.get(proposal.proposed_by)
    proposer_user = (
        users_map.get(proposal.proposed_by_user_id) if proposal.proposed_by_user_id else None
    )
    total_consumers = len(registrations)

    # Get audit status for the asset
    audit_info = await _get_asset_audit_info(session, asset.id)

    # Build warnings list
    warnings: list[str] = []
    if audit_info and not audit_info["is_passing"]:
        warnings.append(
            f"Data quality audit {audit_info['status']} with "
            f"{audit_info['guarantees_failed']} failing guarantee(s). "
            "Consider fixing audits before publishing."
        )

    return {
        "proposal_id": str(proposal.id),
        "status": str(proposal.status),
        "asset_fqn": asset.fqn if asset else None,
        "change_type": str(proposal.change_type),
        "breaking_changes": proposal.breaking_changes,
        "proposed_by": {
            "team_id": str(proposal.proposed_by),
            "team_name": proposer.name if proposer else "Unknown",
            "user_id": str(proposal.proposed_by_user_id) if proposal.proposed_by_user_id else None,
            "user_name": proposer_user.name if proposer_user else None,
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
        "audit_status": audit_info,
        "warnings": warnings,
    }


@router.post("/{proposal_id}/acknowledge", response_model=Acknowledgment, status_code=201)
@limit_write
async def acknowledge_proposal(
    request: Request,
    proposal_id: UUID,
    ack: AcknowledgmentCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> AcknowledgmentDB:
    """Acknowledge a proposal as a consumer.

    If the acknowledgment response is 'blocked', the proposal is rejected.
    If all registered consumers have acknowledged (non-blocked), the proposal is auto-approved.
    Requires write scope.
    """
    # Resource-level auth: must own the consumer team or be admin
    if ack.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only acknowledge proposals on behalf of your own team",
            code=ErrorCode.FORBIDDEN,
            extra={"code": "INSUFFICIENT_PERMISSIONS"},
        )

    # Verify proposal exists and get asset info
    result = await session.execute(
        select(ProposalDB, AssetDB)
        .join(AssetDB, ProposalDB.asset_id == AssetDB.id)
        .where(ProposalDB.id == proposal_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")
    proposal: ProposalDB = row[0]
    asset: AssetDB = row[1]

    if proposal.status != ProposalStatus.PENDING:
        raise BadRequestError("Proposal is not pending", code=ErrorCode.PROPOSAL_NOT_PENDING)

    # Get consumer team info
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == ack.consumer_team_id))
    consumer_team = team_result.scalar_one_or_none()
    if not consumer_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Consumer team not found")

    # Check for duplicate acknowledgment from same team
    result = await session.execute(
        select(AcknowledgmentDB)
        .where(AcknowledgmentDB.proposal_id == proposal_id)
        .where(AcknowledgmentDB.consumer_team_id == ack.consumer_team_id)
    )
    if result.scalar_one_or_none():
        raise DuplicateError(
            ErrorCode.DUPLICATE_ACKNOWLEDGMENT, "Already acknowledged by this team"
        )

    db_ack = AcknowledgmentDB(
        proposal_id=proposal_id,
        consumer_team_id=ack.consumer_team_id,
        acknowledged_by_user_id=ack.acknowledged_by_user_id,
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

    # Check current acknowledgment counts before status change
    all_acknowledged, ack_count = await check_proposal_completion(proposal, session)

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
        # Send webhook for rejection
        await send_proposal_status_change(
            event_type=WebhookEventType.PROPOSAL_REJECTED,
            proposal_id=proposal_id,
            asset_id=asset.id,
            asset_fqn=asset.fqn,
            status="rejected",
            actor_team_id=consumer_team.id,
            actor_team_name=consumer_team.name,
        )
        # Send Slack notification
        await notify_proposal_acknowledged(
            asset_fqn=asset.fqn,
            consumer_team=consumer_team.name,
            response="blocked",
            notes=ack.notes,
        )
        return db_ack

    # Send webhook for acknowledgment
    await send_proposal_acknowledged(
        proposal_id=proposal_id,
        asset_id=asset.id,
        asset_fqn=asset.fqn,
        consumer_team_id=consumer_team.id,
        consumer_team_name=consumer_team.name,
        response=str(ack.response),
        migration_deadline=ack.migration_deadline,
        notes=ack.notes,
        pending_count=ack_count - 1 if not all_acknowledged else 0,
        acknowledged_count=ack_count,
    )

    # Send Slack notification for acknowledgment
    await notify_proposal_acknowledged(
        asset_fqn=asset.fqn,
        consumer_team=consumer_team.name,
        response=str(ack.response),
        notes=ack.notes,
    )

    # Check for auto-approval (all consumers acknowledged, none blocked)
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
        # Send webhook for auto-approval
        await send_proposal_status_change(
            event_type=WebhookEventType.PROPOSAL_APPROVED,
            proposal_id=proposal_id,
            asset_id=asset.id,
            asset_fqn=asset.fqn,
            status="approved",
        )
        # Send Slack notification for approval
        # Note: We don't have version here, would need to get from proposal
        await notify_proposal_approved(
            asset_fqn=asset.fqn,
            version="pending",  # Version is determined at publish time
        )

    return db_ack


@router.post("/{proposal_id}/withdraw", response_model=Proposal)
@limit_write
async def withdraw_proposal(
    request: Request,
    proposal_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Withdraw a proposal.

    Requires write scope.
    """
    result = await session.execute(
        select(ProposalDB, AssetDB)
        .join(AssetDB, ProposalDB.asset_id == AssetDB.id)
        .where(ProposalDB.id == proposal_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")
    proposal: ProposalDB = row[0]
    asset: AssetDB = row[1]

    # Resource-level auth: must own the proposer team or be admin
    if proposal.proposed_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only withdraw your own proposals",
            code=ErrorCode.FORBIDDEN,
            extra={"code": "INSUFFICIENT_PERMISSIONS"},
        )

    if proposal.status != ProposalStatus.PENDING:
        raise BadRequestError("Proposal is not pending", code=ErrorCode.PROPOSAL_NOT_PENDING)

    proposal.status = ProposalStatus.WITHDRAWN
    proposal.resolved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(proposal)

    # Send webhook for withdrawal
    await send_proposal_status_change(
        event_type=WebhookEventType.PROPOSAL_WITHDRAWN,
        proposal_id=proposal_id,
        asset_id=asset.id,
        asset_fqn=asset.fqn,
        status="withdrawn",
    )

    return proposal


@router.post("/{proposal_id}/force", response_model=Proposal)
@limit_write
async def force_proposal(
    request: Request,
    auth: Auth,
    proposal_id: UUID,
    actor_id: UUID = Query(..., description="Team ID of the actor forcing approval"),
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ProposalDB:
    """Force-approve a proposal (bypassing consumer acknowledgments).

    Requires write scope.
    """
    # Resource-level auth: actor_id must match auth.team_id or be admin
    if actor_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only force approve on behalf of your own team",
            code=ErrorCode.FORBIDDEN,
            extra={"code": "INSUFFICIENT_PERMISSIONS"},
        )

    result = await session.execute(
        select(ProposalDB, AssetDB)
        .join(AssetDB, ProposalDB.asset_id == AssetDB.id)
        .where(ProposalDB.id == proposal_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")
    proposal: ProposalDB = row[0]
    asset: AssetDB = row[1]

    if proposal.status != ProposalStatus.PENDING:
        raise BadRequestError("Proposal is not pending", code=ErrorCode.PROPOSAL_NOT_PENDING)

    # Get actor team info
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == actor_id))
    actor_team = team_result.scalar_one_or_none()

    proposal.status = ProposalStatus.APPROVED
    proposal.resolved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(proposal)

    await log_proposal_force_approved(
        session=session,
        proposal_id=proposal_id,
        actor_id=actor_id,
    )

    # Send webhook for force approval
    await send_proposal_status_change(
        event_type=WebhookEventType.PROPOSAL_FORCE_APPROVED,
        proposal_id=proposal_id,
        asset_id=asset.id,
        asset_fqn=asset.fqn,
        status="force_approved",
        actor_team_id=actor_id,
        actor_team_name=actor_team.name if actor_team else None,
    )

    return proposal


@router.post("/{proposal_id}/publish")
@limit_write
async def publish_from_proposal(
    request: Request,
    auth: Auth,
    proposal_id: UUID,
    publish_request: PublishRequest,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Publish a contract from an approved proposal.

    Only works on proposals with status=APPROVED.
    Creates a new contract with the proposed schema and deprecates the old one.
    Requires write scope.
    """
    # Resource-level auth: publish_request.published_by must match auth.team_id or be admin
    if publish_request.published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "You can only publish on behalf of your own team",
            code=ErrorCode.FORBIDDEN,
            extra={"code": "INSUFFICIENT_PERMISSIONS"},
        )

    # Get the proposal
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise NotFoundError(ErrorCode.PROPOSAL_NOT_FOUND, "Proposal not found")

    if proposal.status != ProposalStatus.APPROVED:
        raise BadRequestError(
            f"Cannot publish from proposal with status '{proposal.status}'. "
            "Proposal must be approved first.",
            code=ErrorCode.PROPOSAL_NOT_PENDING,
        )

    # Validate the proposed schema before publishing
    try:
        validate_schema_or_raise(proposal.proposed_schema)
    except SchemaValidationError as e:
        raise BadRequestError(
            f"Invalid schema in proposal: {e.message}", code=ErrorCode.INVALID_SCHEMA
        )

    # Get the asset
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == proposal.asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Get the current active contract to deprecate
    current_contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == proposal.asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = current_contract_result.scalar_one_or_none()

    # Use nested transaction (savepoint) to ensure atomicity of the multi-step publish
    # This ensures all-or-nothing: new contract + deprecate old + audit log
    async with session.begin_nested():
        # Create new contract from the proposal
        # Default to BACKWARD compatibility for new contracts (safe for existing consumers)
        compat_mode = (
            current_contract.compatibility_mode if current_contract else CompatibilityMode.BACKWARD
        )
        new_contract = ContractDB(
            asset_id=proposal.asset_id,
            version=publish_request.version,
            schema_def=proposal.proposed_schema,
            compatibility_mode=compat_mode,
            guarantees=current_contract.guarantees if current_contract else {},
            published_by=publish_request.published_by,
            published_by_user_id=publish_request.published_by_user_id,
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

    # Get publisher team info for webhook
    publisher_result = await session.execute(
        select(TeamDB).where(TeamDB.id == publish_request.published_by)
    )
    publisher_team = publisher_result.scalar_one_or_none()

    # Send webhook for contract publication
    await send_contract_published(
        contract_id=new_contract.id,
        asset_id=asset.id,
        asset_fqn=asset.fqn,
        version=new_contract.version,
        producer_team_id=publish_request.published_by,
        producer_team_name=publisher_team.name if publisher_team else "unknown",
        from_proposal_id=proposal_id,
    )

    # Check audit status and add warning if failing
    audit_info = await _get_asset_audit_info(session, proposal.asset_id)
    response: dict[str, Any] = {
        "action": "published",
        "proposal_id": str(proposal_id),
        "contract": Contract.model_validate(new_contract).model_dump(),
        "deprecated_contract_id": str(current_contract.id) if current_contract else None,
    }
    if audit_info and not audit_info["is_passing"]:
        response["audit_warning"] = (
            f"Warning: Most recent audit {audit_info['status']} "
            f"with {audit_info['guarantees_failed']} guarantee(s) failing"
        )

    return response
