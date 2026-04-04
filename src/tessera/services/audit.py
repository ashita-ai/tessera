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

    # User actions
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    # Team actions
    TEAM_CREATED = "team.created"
    TEAM_UPDATED = "team.updated"
    TEAM_DELETED = "team.deleted"

    # Asset actions
    ASSET_CREATED = "asset.created"
    ASSET_UPDATED = "asset.updated"
    ASSET_DELETED = "asset.deleted"

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
    PROPOSAL_EXPIRED = "proposal.expired"
    PROPOSAL_PUBLISHED = "proposal.published"

    # Restore actions
    ASSET_RESTORED = "asset.restored"
    TEAM_RESTORED = "team.restored"
    USER_REACTIVATED = "user.reactivated"

    # Proposal actions (continued)
    PROPOSAL_OBJECTION_FILED = "proposal.objection_filed"

    # Bulk actions
    BULK_ASSETS_REASSIGNED = "bulk.assets_reassigned"
    BULK_OWNER_ASSIGNED = "bulk.owner_assigned"

    # Dependency actions
    DEPENDENCY_CREATED = "dependency.created"
    DEPENDENCY_DELETED = "dependency.deleted"

    # API Key actions
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    API_KEY_USED = "api_key.used"

    # Repo actions
    REPO_CREATED = "repo.created"
    REPO_UPDATED = "repo.updated"
    REPO_DELETED = "repo.deleted"
    REPO_SYNC_TRIGGERED = "repo.sync_triggered"

    # Service actions
    SERVICE_CREATED = "service.created"
    SERVICE_UPDATED = "service.updated"
    SERVICE_DELETED = "service.deleted"

    # Sync actions
    DBT_SYNC_UPLOAD = "dbt.sync_upload"

    # Consumption actions
    PREFLIGHT_CHECKED = "preflight.checked"

    # Discovery actions
    DISCOVERY_CONFIRMED = "discovery.confirmed"
    DISCOVERY_REJECTED = "discovery.rejected"

    # OTEL actions
    OTEL_CONFIG_CREATED = "otel_config.created"
    OTEL_CONFIG_UPDATED = "otel_config.updated"
    OTEL_CONFIG_DELETED = "otel_config.deleted"
    OTEL_SYNC_COMPLETED = "otel_sync.completed"
    OTEL_SYNC_FAILED = "otel_sync.failed"

    # Slack config actions
    SLACK_CONFIG_CREATED = "slack_config.created"
    SLACK_CONFIG_UPDATED = "slack_config.updated"
    SLACK_CONFIG_DELETED = "slack_config.deleted"
    SLACK_CONFIG_TESTED = "slack_config.tested"


async def log_event(
    session: AsyncSession,
    entity_type: str,
    entity_id: UUID,
    action: AuditAction,
    actor_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    actor_type: str = "human",
) -> AuditEventDB:
    """Log an audit event.

    Args:
        session: Database session
        entity_type: Type of entity (e.g., "team", "asset", "contract")
        entity_id: ID of the affected entity
        action: The action that was performed
        actor_id: ID of the team that performed the action (optional)
        payload: Additional data about the event (optional)
        actor_type: "human" or "agent" — derived from the API key

    Returns:
        The created audit event
    """
    event = AuditEventDB(
        entity_type=entity_type,
        entity_id=entity_id,
        action=str(action),
        actor_id=actor_id,
        actor_type=actor_type,
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
    prerelease: bool = False,
    previous_version: str | None = None,
) -> AuditEventDB:
    """Log a contract publication event.

    Args:
        previous_version: Raw version string of the contract being superseded.
            Captured so the audit trail preserves the original value even when
            lenient parsing normalized it for version-bump computation.
    """
    action = AuditAction.CONTRACT_FORCE_PUBLISHED if force else AuditAction.CONTRACT_PUBLISHED
    payload: dict[str, Any] = {
        "version": version,
        "change_type": change_type,
        "force": force,
        "prerelease": prerelease,
    }
    if previous_version is not None:
        payload["previous_version"] = previous_version
    return await log_event(
        session=session,
        entity_type="contract",
        entity_id=contract_id,
        action=action,
        actor_id=publisher_id,
        payload=payload,
    )


async def log_contract_deprecated(
    session: AsyncSession,
    contract_id: UUID,
    actor_id: UUID,
    version: str,
    superseded_by: UUID,
    superseded_by_version: str,
) -> AuditEventDB:
    """Log a contract deprecation event.

    Called when a new contract version supersedes an existing active contract.
    """
    return await log_event(
        session=session,
        entity_type="contract",
        entity_id=contract_id,
        action=AuditAction.CONTRACT_DEPRECATED,
        actor_id=actor_id,
        payload={
            "version": version,
            "superseded_by": str(superseded_by),
            "superseded_by_version": superseded_by_version,
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


async def log_proposal_published(
    session: AsyncSession,
    proposal_id: UUID,
    contract_id: UUID,
    publisher_id: UUID,
    version: str,
) -> AuditEventDB:
    """Log that an approved proposal was published as a contract."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_PUBLISHED,
        actor_id=publisher_id,
        payload={
            "contract_id": str(contract_id),
            "version": version,
        },
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


async def log_asset_restored(
    session: AsyncSession,
    asset_id: UUID,
    actor_id: UUID,
    fqn: str,
) -> AuditEventDB:
    """Log an asset restoration event."""
    return await log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_id,
        action=AuditAction.ASSET_RESTORED,
        actor_id=actor_id,
        payload={"fqn": fqn},
    )


async def log_team_restored(
    session: AsyncSession,
    team_id: UUID,
    actor_id: UUID,
    name: str,
) -> AuditEventDB:
    """Log a team restoration event."""
    return await log_event(
        session=session,
        entity_type="team",
        entity_id=team_id,
        action=AuditAction.TEAM_RESTORED,
        actor_id=actor_id,
        payload={"name": name},
    )


async def log_user_reactivated(
    session: AsyncSession,
    user_id: UUID,
    actor_id: UUID | None,
    email: str,
    name: str,
) -> AuditEventDB:
    """Log a user reactivation event."""
    return await log_event(
        session=session,
        entity_type="user",
        entity_id=user_id,
        action=AuditAction.USER_REACTIVATED,
        actor_id=actor_id,
        payload={"email": email, "name": name},
    )


async def log_proposal_withdrawn(
    session: AsyncSession,
    proposal_id: UUID,
    actor_id: UUID,
    asset_id: UUID,
) -> AuditEventDB:
    """Log a proposal withdrawal event."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_WITHDRAWN,
        actor_id=actor_id,
        payload={"asset_id": str(asset_id)},
    )


async def log_objection_filed(
    session: AsyncSession,
    proposal_id: UUID,
    objector_team_id: UUID,
    reason: str,
    asset_id: UUID,
) -> AuditEventDB:
    """Log an objection filed against a proposal."""
    return await log_event(
        session=session,
        entity_type="proposal",
        entity_id=proposal_id,
        action=AuditAction.PROPOSAL_OBJECTION_FILED,
        actor_id=objector_team_id,
        payload={"reason": reason, "asset_id": str(asset_id)},
    )


async def log_bulk_assets_reassigned(
    session: AsyncSession,
    source_team_id: UUID,
    target_team_id: UUID,
    asset_count: int,
    actor_id: UUID,
    asset_ids: list[UUID],
) -> AuditEventDB:
    """Log a bulk asset reassignment between teams."""
    return await log_event(
        session=session,
        entity_type="team",
        entity_id=source_team_id,
        action=AuditAction.BULK_ASSETS_REASSIGNED,
        actor_id=actor_id,
        payload={
            "source_team_id": str(source_team_id),
            "target_team_id": str(target_team_id),
            "asset_count": asset_count,
            "asset_ids": [str(aid) for aid in asset_ids],
        },
    )


async def log_bulk_owner_assigned(
    session: AsyncSession,
    actor_id: UUID,
    new_owner_user_id: UUID | None,
    asset_count: int,
    asset_ids: list[UUID],
) -> AuditEventDB:
    """Log a bulk user-owner assignment across assets."""
    return await log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_ids[0] if asset_ids else actor_id,
        action=AuditAction.BULK_OWNER_ASSIGNED,
        actor_id=actor_id,
        payload={
            "new_owner_user_id": str(new_owner_user_id) if new_owner_user_id else None,
            "asset_count": asset_count,
            "asset_ids": [str(aid) for aid in asset_ids],
        },
    )


async def log_dependency_created(
    session: AsyncSession,
    dependency_id: UUID,
    source_asset_id: UUID,
    target_asset_id: UUID,
    actor_id: UUID,
    dependency_type: str,
) -> AuditEventDB:
    """Log a dependency creation event.

    Args:
        session: Database session.
        dependency_id: ID of the newly created dependency.
        source_asset_id: The dependent asset (downstream consumer).
        target_asset_id: The dependency asset (upstream provider).
        actor_id: Team ID that created the dependency.
        dependency_type: Type of dependency (consumes, references, transforms).

    Returns:
        The created audit event.
    """
    return await log_event(
        session=session,
        entity_type="dependency",
        entity_id=dependency_id,
        action=AuditAction.DEPENDENCY_CREATED,
        actor_id=actor_id,
        payload={
            "source_asset_id": str(source_asset_id),
            "target_asset_id": str(target_asset_id),
            "dependency_type": dependency_type,
        },
    )


async def log_dependency_deleted(
    session: AsyncSession,
    dependency_id: UUID,
    source_asset_id: UUID,
    target_asset_id: UUID,
    actor_id: UUID,
) -> AuditEventDB:
    """Log a dependency soft-delete event.

    Args:
        session: Database session.
        dependency_id: ID of the deleted dependency.
        source_asset_id: The dependent asset (downstream consumer).
        target_asset_id: The dependency asset (upstream provider).
        actor_id: Team ID that deleted the dependency.

    Returns:
        The created audit event.
    """
    return await log_event(
        session=session,
        entity_type="dependency",
        entity_id=dependency_id,
        action=AuditAction.DEPENDENCY_DELETED,
        actor_id=actor_id,
        payload={
            "source_asset_id": str(source_asset_id),
            "target_asset_id": str(target_asset_id),
        },
    )


async def log_preflight_checked(
    session: AsyncSession,
    asset_id: UUID,
    actor_id: UUID | None,
    asset_fqn: str,
    contract_version: str,
    freshness_status: str,
    guarantees_checked: bool,
    consumer_type: str | None = None,
) -> AuditEventDB:
    """Log a preflight consumption event.

    Records that a consumer checked contract metadata before querying data.
    This enables contract utilization metrics and agent observability.

    Args:
        session: Database session.
        asset_id: ID of the asset whose contract was checked.
        actor_id: Team ID of the consumer (from API key or query param).
        asset_fqn: Fully qualified name of the asset.
        contract_version: Version of the active contract returned.
        freshness_status: Whether the data was fresh or stale.
        guarantees_checked: Whether guarantee data was included.
        consumer_type: Type of consumer (e.g., "agent", "human", "pipeline").

    Returns:
        The created audit event.
    """
    return await log_event(
        session=session,
        entity_type="asset",
        entity_id=asset_id,
        action=AuditAction.PREFLIGHT_CHECKED,
        actor_id=actor_id,
        payload={
            "asset_fqn": asset_fqn,
            "contract_version": contract_version,
            "freshness_status": freshness_status,
            "guarantees_checked": guarantees_checked,
            "consumer_type": consumer_type,
        },
    )
