"""Asset context service — single-call aggregation of all asset data.

Loads asset metadata, current contract, consumers, lineage, proposals,
and recent audit runs sequentially on a single session.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    AuditRunDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import ContractStatus, ProposalStatus, RegistrationStatus


async def _load_current_contract(session: AsyncSession, asset_id: UUID) -> ContractDB | None:
    """Load the most recent active contract for an asset."""
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_consumers(session: AsyncSession, asset_id: UUID) -> list[dict[str, Any]]:
    """Load active consumer registrations for the asset's active contracts."""
    # Find active contracts for this asset
    contracts_result = await session.execute(
        select(ContractDB.id)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    contract_ids = [row[0] for row in contracts_result.all()]
    if not contract_ids:
        return []

    # Find active registrations with team info
    regs_result = await session.execute(
        select(RegistrationDB, TeamDB)
        .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
        .where(RegistrationDB.contract_id.in_(contract_ids))
        .where(RegistrationDB.deleted_at.is_(None))
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        .where(TeamDB.deleted_at.is_(None))
    )

    consumers: list[dict[str, Any]] = []
    for reg, team in regs_result.all():
        consumers.append(
            {
                "registration_id": str(reg.id),
                "consumer_team_id": str(team.id),
                "consumer_team_name": team.name,
                "pinned_version": reg.pinned_version,
                "status": str(reg.status),
                "registered_at": reg.registered_at.isoformat(),
            }
        )
    return consumers


async def _load_upstream_dependencies(
    session: AsyncSession, asset_id: UUID
) -> list[dict[str, Any]]:
    """Load assets that this asset depends on (upstream)."""
    result = await session.execute(
        select(AssetDB, AssetDependencyDB.dependency_type)
        .join(AssetDependencyDB, AssetDependencyDB.dependency_asset_id == AssetDB.id)
        .where(AssetDependencyDB.dependent_asset_id == asset_id)
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(AssetDB.deleted_at.is_(None))
    )
    return [
        {
            "asset_id": str(asset.id),
            "fqn": asset.fqn,
            "resource_type": str(asset.resource_type),
            "dependency_type": str(dep_type),
        }
        for asset, dep_type in result.all()
    ]


async def _load_downstream_dependents(
    session: AsyncSession, asset_id: UUID
) -> list[dict[str, Any]]:
    """Load assets that depend on this asset (downstream, depth=1)."""
    result = await session.execute(
        select(AssetDB, AssetDependencyDB.dependency_type)
        .join(AssetDependencyDB, AssetDependencyDB.dependent_asset_id == AssetDB.id)
        .where(AssetDependencyDB.dependency_asset_id == asset_id)
        .where(AssetDependencyDB.deleted_at.is_(None))
        .where(AssetDB.deleted_at.is_(None))
    )
    return [
        {
            "asset_id": str(asset.id),
            "fqn": asset.fqn,
            "resource_type": str(asset.resource_type),
            "dependency_type": str(dep_type),
        }
        for asset, dep_type in result.all()
    ]


async def _load_active_proposals(session: AsyncSession, asset_id: UUID) -> list[dict[str, Any]]:
    """Load pending proposals for this asset."""
    result = await session.execute(
        select(ProposalDB)
        .where(ProposalDB.asset_id == asset_id)
        .where(ProposalDB.status == ProposalStatus.PENDING)
        .order_by(ProposalDB.proposed_at.desc())
    )
    proposals: list[dict[str, Any]] = []
    for proposal in result.scalars().all():
        proposals.append(
            {
                "id": str(proposal.id),
                "change_type": str(proposal.change_type),
                "status": str(proposal.status),
                "proposed_at": proposal.proposed_at.isoformat(),
                "breaking_changes_count": len(proposal.breaking_changes),
            }
        )
    return proposals


async def _load_recent_audits(
    session: AsyncSession, asset_id: UUID, limit: int = 5
) -> list[dict[str, Any]]:
    """Load the most recent audit runs for this asset."""
    result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .order_by(AuditRunDB.run_at.desc())
        .limit(limit)
    )
    audits: list[dict[str, Any]] = []
    for run in result.scalars().all():
        audits.append(
            {
                "id": str(run.id),
                "status": str(run.status),
                "guarantees_checked": run.guarantees_checked,
                "guarantees_passed": run.guarantees_passed,
                "guarantees_failed": run.guarantees_failed,
                "triggered_by": run.triggered_by,
                "run_at": run.run_at.isoformat(),
            }
        )
    return audits


async def _load_contract_history_count(session: AsyncSession, asset_id: UUID) -> int:
    """Count total published contract versions for this asset."""
    result = await session.execute(
        select(func.count(ContractDB.id)).where(ContractDB.asset_id == asset_id)
    )
    return result.scalar_one()


async def get_asset_context(session: AsyncSession, asset: AssetDB) -> dict[str, Any]:
    """Build the full asset context response.

    Loads all related data sequentially on the provided session. AsyncSession
    wraps a single connection and cannot be shared across concurrent coroutines
    (asyncio.gather would raise InterfaceError on asyncpg).

    Args:
        session: Database session.
        asset: The asset to build context for (must already be loaded).

    Returns:
        Complete asset context dictionary.
    """
    asset_id = asset.id

    current_contract = await _load_current_contract(session, asset_id)
    consumers = await _load_consumers(session, asset_id)
    upstream = await _load_upstream_dependencies(session, asset_id)
    downstream = await _load_downstream_dependents(session, asset_id)
    active_proposals = await _load_active_proposals(session, asset_id)
    recent_audits = await _load_recent_audits(session, asset_id)
    contract_history_count = await _load_contract_history_count(session, asset_id)

    # Build asset section
    asset_section: dict[str, Any] = {
        "id": str(asset.id),
        "fqn": asset.fqn,
        "description": asset.metadata_.get("description"),
        "tags": asset.metadata_.get("tags", []),
        "resource_type": str(asset.resource_type),
        "environment": asset.environment,
        "owner_team_id": str(asset.owner_team_id),
        "owner_team_name": asset.owner_team.name if asset.owner_team else None,
        "owner_user_id": str(asset.owner_user_id) if asset.owner_user_id else None,
        "compatibility_mode": None,
        "guarantee_mode": str(asset.guarantee_mode),
    }

    # Build contract section
    contract_section: dict[str, Any] | None = None
    if current_contract:
        asset_section["compatibility_mode"] = str(current_contract.compatibility_mode)

        # Extract field-level annotations from schema properties
        schema = current_contract.schema_def
        properties = schema.get("properties", {})
        field_descriptions: dict[str, str] = {}
        field_tags: dict[str, list[str]] = {}
        for field_name, field_def in properties.items():
            if isinstance(field_def, dict):
                desc = field_def.get("description")
                if desc:
                    field_descriptions[field_name] = desc
                tags = field_def.get("tags")
                if tags:
                    field_tags[field_name] = tags

        contract_section = {
            "id": str(current_contract.id),
            "version": current_contract.version,
            "schema": current_contract.schema_def,
            "field_descriptions": field_descriptions,
            "field_tags": field_tags,
            "guarantees": current_contract.guarantees,
            "status": str(current_contract.status),
            "published_at": current_contract.published_at.isoformat(),
        }

    return {
        "asset": asset_section,
        "current_contract": contract_section,
        "consumers": consumers,
        "upstream_dependencies": upstream,
        "downstream_dependents": downstream,
        "active_proposals": active_proposals,
        "recent_audits": recent_audits,
        "contract_history_count": contract_history_count,
    }
