"""Bulk operations API endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireWrite
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError
from tessera.api.rate_limit import limit_write
from tessera.db import (
    AcknowledgmentDB,
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
    get_session,
)
from tessera.models import (
    BulkAcknowledgmentRequest,
    BulkAcknowledgmentResponse,
    BulkAssetRequest,
    BulkAssetResponse,
    BulkItemResult,
    BulkRegistrationRequest,
    BulkRegistrationResponse,
)
from tessera.models.enums import (
    AcknowledgmentResponseType,
    APIKeyScope,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.services import (
    log_proposal_acknowledged,
    log_proposal_approved,
    log_proposal_rejected,
)
from tessera.services.audit import AuditAction, log_event

router = APIRouter()


@router.post("/registrations", response_model=BulkRegistrationResponse)
@limit_write
async def bulk_create_registrations(
    request: Request,
    auth: Auth,
    bulk_request: BulkRegistrationRequest,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> BulkRegistrationResponse:
    """Create multiple registrations at once.

    Each registration associates a consumer team with a contract.
    If skip_duplicates is true, duplicate registrations are skipped instead of failing.

    Requires write scope.
    """
    results: list[BulkItemResult] = []
    succeeded = 0
    failed = 0

    for idx, item in enumerate(bulk_request.registrations):
        try:
            # Authorization check: must own the consumer team or be admin
            if item.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
                raise ForbiddenError(
                    "You can only register on behalf of your own team",
                    code=ErrorCode.FORBIDDEN,
                )

            # Verify team exists
            team_result = await session.execute(
                select(TeamDB).where(TeamDB.id == item.consumer_team_id)
            )
            if not team_result.scalar_one_or_none():
                raise BadRequestError(
                    f"Team {item.consumer_team_id} not found",
                    code=ErrorCode.TEAM_NOT_FOUND,
                )

            # Verify contract exists and is active
            contract_result = await session.execute(
                select(ContractDB).where(ContractDB.id == item.contract_id)
            )
            contract = contract_result.scalar_one_or_none()
            if not contract:
                raise BadRequestError(
                    f"Contract {item.contract_id} not found",
                    code=ErrorCode.CONTRACT_NOT_FOUND,
                )
            if contract.status != ContractStatus.ACTIVE:
                raise BadRequestError(
                    f"Contract {item.contract_id} is not active",
                    code=ErrorCode.CONTRACT_NOT_ACTIVE,
                )

            # Check for existing registration
            existing_result = await session.execute(
                select(RegistrationDB)
                .where(RegistrationDB.contract_id == item.contract_id)
                .where(RegistrationDB.consumer_team_id == item.consumer_team_id)
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                if bulk_request.skip_duplicates:
                    results.append(
                        BulkItemResult(
                            success=True,
                            index=idx,
                            id=existing.id,
                            details={"skipped": True, "reason": "duplicate"},
                        )
                    )
                    succeeded += 1
                    continue
                else:
                    raise BadRequestError(
                        f"Registration already exists for team {item.consumer_team_id} "
                        f"and contract {item.contract_id}",
                        code=ErrorCode.DUPLICATE_REGISTRATION,
                    )

            # Create registration
            registration = RegistrationDB(
                contract_id=item.contract_id,
                consumer_team_id=item.consumer_team_id,
                pinned_version=item.pinned_version,
                status=RegistrationStatus.ACTIVE,
            )
            session.add(registration)
            await session.flush()
            await session.refresh(registration)

            # Log audit event
            await log_event(
                session=session,
                entity_type="registration",
                entity_id=registration.id,
                action=AuditAction.REGISTRATION_CREATED,
                actor_id=item.consumer_team_id,
                payload={
                    "contract_id": str(item.contract_id),
                    "bulk_operation": True,
                },
            )

            results.append(
                BulkItemResult(
                    success=True,
                    index=idx,
                    id=registration.id,
                )
            )
            succeeded += 1

        except (BadRequestError, ForbiddenError) as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=str(e.message if hasattr(e, "message") else str(e)),
                )
            )
            failed += 1
        except Exception as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=f"Unexpected error: {str(e)}",
                )
            )
            failed += 1

    return BulkRegistrationResponse(
        total=len(bulk_request.registrations),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.post("/assets", response_model=BulkAssetResponse)
@limit_write
async def bulk_create_assets(
    request: Request,
    auth: Auth,
    bulk_request: BulkAssetRequest,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> BulkAssetResponse:
    """Create multiple assets at once.

    If skip_duplicates is true, duplicate assets (by FQN) are skipped instead of failing.

    Requires write scope.
    """
    results: list[BulkItemResult] = []
    succeeded = 0
    failed = 0

    for idx, item in enumerate(bulk_request.assets):
        try:
            # Authorization check: must own the team or be admin
            if item.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
                raise ForbiddenError(
                    "You can only create assets for your own team",
                    code=ErrorCode.FORBIDDEN,
                )

            # Verify team exists
            team_result = await session.execute(
                select(TeamDB).where(TeamDB.id == item.owner_team_id)
            )
            if not team_result.scalar_one_or_none():
                raise BadRequestError(
                    f"Team {item.owner_team_id} not found",
                    code=ErrorCode.TEAM_NOT_FOUND,
                )

            # Check for existing asset with same FQN
            existing_result = await session.execute(
                select(AssetDB)
                .where(AssetDB.fqn == item.fqn)
                .where(AssetDB.environment == item.environment)
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                if bulk_request.skip_duplicates:
                    results.append(
                        BulkItemResult(
                            success=True,
                            index=idx,
                            id=existing.id,
                            details={"skipped": True, "reason": "duplicate"},
                        )
                    )
                    succeeded += 1
                    continue
                else:
                    raise BadRequestError(
                        f"Asset with FQN '{item.fqn}' already exists "
                        f"in environment '{item.environment}'",
                        code=ErrorCode.DUPLICATE_ASSET,
                    )

            # Create asset
            asset = AssetDB(
                fqn=item.fqn,
                owner_team_id=item.owner_team_id,
                owner_user_id=item.owner_user_id,
                environment=item.environment,
                resource_type=item.resource_type,
                guarantee_mode=item.guarantee_mode,
                metadata_=item.metadata,
            )
            session.add(asset)
            await session.flush()
            await session.refresh(asset)

            # Log audit event
            await log_event(
                session=session,
                entity_type="asset",
                entity_id=asset.id,
                action=AuditAction.ASSET_CREATED,
                actor_id=item.owner_team_id,
                payload={
                    "fqn": item.fqn,
                    "environment": item.environment,
                    "bulk_operation": True,
                },
            )

            results.append(
                BulkItemResult(
                    success=True,
                    index=idx,
                    id=asset.id,
                )
            )
            succeeded += 1

        except (BadRequestError, ForbiddenError) as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=str(e.message if hasattr(e, "message") else str(e)),
                )
            )
            failed += 1
        except Exception as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=f"Unexpected error: {str(e)}",
                )
            )
            failed += 1

    return BulkAssetResponse(
        total=len(bulk_request.assets),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


async def _check_proposal_completion(
    proposal: ProposalDB,
    session: AsyncSession,
) -> tuple[bool, int]:
    """Check if all registered consumers have acknowledged the proposal."""
    # Get the current active contract for this asset
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == proposal.asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    if not current_contract:
        return True, 0

    # Get all active registrations for this contract
    reg_result = await session.execute(
        select(RegistrationDB)
        .where(RegistrationDB.contract_id == current_contract.id)
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
    )
    registrations = reg_result.scalars().all()

    if not registrations:
        return True, 0

    # Get all acknowledgments for this proposal
    ack_result = await session.execute(
        select(AcknowledgmentDB).where(AcknowledgmentDB.proposal_id == proposal.id)
    )
    acknowledgments = ack_result.scalars().all()

    registered_team_ids = {r.consumer_team_id for r in registrations}
    acknowledged_team_ids = {a.consumer_team_id for a in acknowledgments}

    all_acknowledged = registered_team_ids <= acknowledged_team_ids
    return all_acknowledged, len(acknowledgments)


@router.post("/acknowledgments", response_model=BulkAcknowledgmentResponse)
@limit_write
async def bulk_acknowledge_proposals(
    request: Request,
    auth: Auth,
    bulk_request: BulkAcknowledgmentRequest,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> BulkAcknowledgmentResponse:
    """Acknowledge multiple proposals at once.

    If continue_on_error is true (default), processing continues after errors.
    Proposals may auto-approve or get rejected based on acknowledgment responses.

    Requires write scope.
    """
    results: list[BulkItemResult] = []
    succeeded = 0
    failed = 0

    for idx, item in enumerate(bulk_request.acknowledgments):
        try:
            # Authorization check: must own the consumer team or be admin
            if item.consumer_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
                raise ForbiddenError(
                    "You can only acknowledge proposals on behalf of your own team",
                    code=ErrorCode.FORBIDDEN,
                )

            # Verify proposal exists — lock the row to prevent concurrent
            # acks from both triggering auto-approval (matches single-ack
            # pattern in proposals.py).
            proposal_result = await session.execute(
                select(ProposalDB).where(ProposalDB.id == item.proposal_id).with_for_update()
            )
            proposal = proposal_result.scalar_one_or_none()
            if not proposal:
                raise BadRequestError(
                    f"Proposal {item.proposal_id} not found",
                    code=ErrorCode.PROPOSAL_NOT_FOUND,
                )

            if proposal.status != ProposalStatus.PENDING:
                raise BadRequestError(
                    f"Proposal {item.proposal_id} is not pending (status: {proposal.status})",
                    code=ErrorCode.PROPOSAL_NOT_PENDING,
                )

            # Check for duplicate acknowledgment
            existing_ack_result = await session.execute(
                select(AcknowledgmentDB)
                .where(AcknowledgmentDB.proposal_id == item.proposal_id)
                .where(AcknowledgmentDB.consumer_team_id == item.consumer_team_id)
            )
            if existing_ack_result.scalar_one_or_none():
                raise BadRequestError(
                    f"Proposal {item.proposal_id} already acknowledged "
                    f"by team {item.consumer_team_id}",
                    code=ErrorCode.DUPLICATE_ACKNOWLEDGMENT,
                )

            # Parse migration deadline if provided
            migration_deadline = None
            if item.migration_deadline:
                try:
                    migration_deadline = datetime.fromisoformat(
                        item.migration_deadline.replace("Z", "+00:00")
                    )
                except ValueError:
                    raise BadRequestError(
                        f"Invalid migration_deadline format: {item.migration_deadline}",
                        code=ErrorCode.INVALID_INPUT,
                    )

            # Create acknowledgment
            ack = AcknowledgmentDB(
                proposal_id=item.proposal_id,
                consumer_team_id=item.consumer_team_id,
                acknowledged_by_user_id=item.acknowledged_by_user_id,
                response=item.response,
                migration_deadline=migration_deadline,
                notes=item.notes,
            )
            session.add(ack)
            await session.flush()
            await session.refresh(ack)

            # Log acknowledgment
            await log_proposal_acknowledged(
                session=session,
                proposal_id=item.proposal_id,
                consumer_team_id=item.consumer_team_id,
                response=str(item.response),
                notes=item.notes,
            )

            details: dict[str, Any] = {"response": str(item.response)}

            # Handle rejection if consumer blocks
            if item.response == AcknowledgmentResponseType.BLOCKED:
                proposal.status = ProposalStatus.REJECTED
                proposal.resolved_at = datetime.now(UTC)
                await session.flush()
                await log_proposal_rejected(
                    session=session,
                    proposal_id=item.proposal_id,
                    blocked_by=item.consumer_team_id,
                )
                details["proposal_status"] = "rejected"
            else:
                # Check for auto-approval
                all_acknowledged, ack_count = await _check_proposal_completion(proposal, session)
                if all_acknowledged:
                    proposal.status = ProposalStatus.APPROVED
                    proposal.resolved_at = datetime.now(UTC)
                    await session.flush()
                    await log_proposal_approved(
                        session=session,
                        proposal_id=item.proposal_id,
                        acknowledged_count=ack_count,
                    )
                    details["proposal_status"] = "approved"
                else:
                    details["proposal_status"] = "pending"

            results.append(
                BulkItemResult(
                    success=True,
                    index=idx,
                    id=ack.id,
                    details=details,
                )
            )
            succeeded += 1

        except (BadRequestError, ForbiddenError) as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=str(e.message if hasattr(e, "message") else str(e)),
                )
            )
            failed += 1
            if not bulk_request.continue_on_error:
                break
        except Exception as e:
            results.append(
                BulkItemResult(
                    success=False,
                    index=idx,
                    error=f"Unexpected error: {str(e)}",
                )
            )
            failed += 1
            if not bulk_request.continue_on_error:
                break

    return BulkAcknowledgmentResponse(
        total=len(bulk_request.acknowledgments),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
