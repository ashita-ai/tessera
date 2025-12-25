"""Audit logging service.

Provides append-only audit trail for all significant events.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AuditEventDB


class AuditAction(StrEnum):
    """Types of auditable actions."""

    # Team actions
    TEAM_CREATED = "team.created"
    TEAM_UPDATED = "team.updated"

    # Asset actions
    ASSET_CREATED = "asset.created"
    ASSET_UPDATED = "asset.updated"

    # Contract actions
    CONTRACT_PUBLISHED = "contract.published"
    CONTRACT_DEPRECATED = "contract.deprecated"
    CONTRACT_FORCE_PUBLISHED = "contract.force_published"
    CONTRACT_GUARANTEES_UPDATED = "contract.guarantees_updated"

    # Registration actions
    REGISTRATION_CREATED = "registration.created"
    REGISTRATION_UPDATED = "registration.updated"
    REGISTRATION_DELETED = "registration.deleted"

    # Proposal actions
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_ACKNOWLEDGED = "proposal.acknowledged"
    PROPOSAL_WITHDRAWN = "proposal.withdrawn"
    PROPOSAL_FORCE_APPROVED = "proposal.force_approved"
    PROPOSAL_APPROVED = "proposal.approved"
    PROPOSAL_REJECTED = "proposal.rejected"

    # API Key actions
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"


async def log_event(
    session: AsyncSession,
    entity_type: str,
    entity_id: UUID,
    action: AuditAction,
    actor_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEventDB:
    """Log an audit event.

    Args:
        session: Database session
        entity_type: Type of entity (e.g., "team", "asset", "contract")
        entity_id: ID of the affected entity
        action: The action that was performed
        actor_id: ID of the team that performed the action (optional)
        payload: Additional data about the event (optional)

    Returns:
        The created audit event
    """
    event = AuditEventDB(
        entity_type=entity_type,
        entity_id=entity_id,
        action=str(action),
        actor_id=actor_id,
        payload=payload or {},
        occurred_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    return event


async def log_contract_published(
    session: AsyncSession,
    contract_id: UUID,
    publisher_id: UUID,
    version: str,
    change_type: str | None = None,
    force: bool = False,
) -> AuditEventDB:
    """Log a contract publication event."""
    action = AuditAction.CONTRACT_FORCE_PUBLISHED if force else AuditAction.CONTRACT_PUBLISHED
    return await log_event(
        session=session,
        entity_type="contract",
        entity_id=contract_id,
        action=action,
        actor_id=publisher_id,
        payload={
            "version": version,
            "change_type": change_type,
            "force": force,
        },
    )


async def log_proposal_created(
    session: AsyncSession,
    proposal_id: UUID,
    asset_id: UUID,
    proposer_id: UUID,
    change_type: str,
    breaking_changes: list[dict[str, Any]],
) -> AuditEventDB:
    """Log a proposal creation event."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_CREATED,
        actor_id=proposer_id,
        payload={
            "asset_id": str(asset_id),
            "change_type": change_type,
            "breaking_changes_count": len(breaking_changes),
        },
    )


async def log_proposal_acknowledged(
    session: AsyncSession,
    proposal_id: UUID,
    consumer_team_id: UUID,
    response: str,
    notes: str | None = None,
) -> AuditEventDB:
    """Log a proposal acknowledgment event."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_ACKNOWLEDGED,
        actor_id=consumer_team_id,
        payload={
            "response": response,
            "notes": notes,
        },
    )


async def log_proposal_force_approved(
    session: AsyncSession,
    proposal_id: UUID,
    actor_id: UUID,
) -> AuditEventDB:
    """Log a force-approval of a proposal."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_FORCE_APPROVED,
        actor_id=actor_id,
        payload={"warning": "Proposal force-approved without full consumer acknowledgment"},
    )


async def log_proposal_approved(
    session: AsyncSession,
    proposal_id: UUID,
    acknowledged_count: int,
) -> AuditEventDB:
    """Log an auto-approval of a proposal when all consumers acknowledged."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_APPROVED,
        payload={"acknowledged_count": acknowledged_count, "auto_approved": True},
    )


async def log_proposal_rejected(
    session: AsyncSession,
    proposal_id: UUID,
    blocked_by: UUID,
) -> AuditEventDB:
    """Log a proposal rejection when a consumer blocks it."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_REJECTED,
        actor_id=blocked_by,
        payload={"reason": "Consumer blocked the proposal"},
    )


async def log_guarantees_updated(
    session: AsyncSession,
    contract_id: UUID,
    actor_id: UUID,
    old_guarantees: dict[str, Any] | None,
    new_guarantees: dict[str, Any],
) -> AuditEventDB:
    """Log a contract guarantees update event."""
    return await log_event(
        session=session,
        entity_type="contract",
        entity_id=contract_id,
        action=AuditAction.CONTRACT_GUARANTEES_UPDATED,
        actor_id=actor_id,
        payload={
            "old_guarantees": old_guarantees,
            "new_guarantees": new_guarantees,
        },
    )
