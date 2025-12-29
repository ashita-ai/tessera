"""Proposal expiration service."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db import AcknowledgmentDB, ProposalDB
from tessera.models.enums import ProposalStatus
from tessera.services.audit import AuditAction, log_event


async def check_proposal_expiration(
    proposal: ProposalDB,
    session: AsyncSession,
) -> bool:
    """Check if a proposal should be expired.

    A proposal expires if:
    1. It has an explicit expires_at timestamp that has passed
    2. auto_expire=True and all consumer migration_deadlines have passed

    Args:
        proposal: The proposal to check
        session: Database session

    Returns:
        True if the proposal should be expired, False otherwise
    """
    if proposal.status != ProposalStatus.PENDING:
        return False

    now = datetime.now(UTC)

    # Check explicit expiration
    if proposal.expires_at and now > proposal.expires_at:
        return True

    # Check auto-expiration based on migration deadlines
    if proposal.auto_expire:
        ack_result = await session.execute(
            select(AcknowledgmentDB).where(AcknowledgmentDB.proposal_id == proposal.id)
        )
        acknowledgments = ack_result.scalars().all()

        if acknowledgments:
            # Get the latest migration deadline among all acknowledgments
            deadlines = [
                ack.migration_deadline
                for ack in acknowledgments
                if ack.migration_deadline is not None
            ]
            if deadlines:
                max_deadline = max(deadlines)
                if now > max_deadline:
                    return True

    return False


async def expire_proposal(
    proposal_id: UUID,
    session: AsyncSession,
) -> ProposalDB | None:
    """Expire a proposal.

    Args:
        proposal_id: The ID of the proposal to expire
        session: Database session

    Returns:
        The updated proposal if expired, None if not found or not pending
    """
    result = await session.execute(select(ProposalDB).where(ProposalDB.id == proposal_id))
    proposal = result.scalar_one_or_none()

    if not proposal or proposal.status != ProposalStatus.PENDING:
        return None

    proposal.status = ProposalStatus.EXPIRED
    proposal.resolved_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(proposal)

    await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_EXPIRED,
        payload={
            "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
            "auto_expire": proposal.auto_expire,
        },
    )

    return proposal


async def expire_pending_proposals(session: AsyncSession) -> list[UUID]:
    """Expire all pending proposals that should be expired.

    This function is intended to be called periodically (e.g., via cron or background task).

    Args:
        session: Database session

    Returns:
        List of proposal IDs that were expired
    """
    if not settings.proposal_auto_expire_enabled:
        return []

    # Get all pending proposals
    result = await session.execute(
        select(ProposalDB).where(ProposalDB.status == ProposalStatus.PENDING)
    )
    pending_proposals = result.scalars().all()

    expired_ids: list[UUID] = []

    for proposal in pending_proposals:
        should_expire = await check_proposal_expiration(proposal, session)
        if should_expire:
            expired = await expire_proposal(proposal.id, session)
            if expired:
                expired_ids.append(proposal.id)

    return expired_ids


def calculate_default_expiration() -> datetime:
    """Calculate the default expiration timestamp for a new proposal.

    Returns:
        A datetime representing the default expiration (now + configured days)
    """
    from datetime import timedelta

    return datetime.now(UTC) + timedelta(days=settings.proposal_default_expiration_days)
