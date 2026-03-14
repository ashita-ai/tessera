"""Impact preview service for pre-flight schema change analysis.

Composes schema diffing, guarantee diffing, consumer discovery, lineage
traversal, version suggestion, and migration suggestion into a single
read-only operation that tells an agent exactly what would happen if a
proposed schema change were published.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    ContractDB,
    ProposalDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    CompatibilityMode,
    ProposalStatus,
    RegistrationStatus,
)
from tessera.services.affected_parties import get_affected_parties
from tessera.services.migration_suggester import suggest_migrations
from tessera.services.schema_diff import (
    diff_guarantees,
    diff_schemas,
)
from tessera.services.versioning import compute_version_suggestion


@dataclass
class AffectedConsumer:
    """A consumer team affected by the proposed change."""

    team_id: str
    team_name: str
    registration_id: str
    contract_version: str
    pinned_version: str | None
    status: str


@dataclass
class AffectedDownstream:
    """A downstream asset affected via lineage."""

    asset_id: str
    asset_fqn: str
    owner_team_id: str
    owner_team_name: str
    depth: int = 1


@dataclass
class ImpactPreviewResult:
    """Complete result of an impact preview analysis."""

    is_breaking: bool
    breaking_changes: list[dict[str, Any]]
    non_breaking_changes: list[dict[str, Any]]
    guarantee_changes: list[dict[str, Any]]
    affected_consumers: list[dict[str, Any]]
    affected_downstream: list[dict[str, Any]]
    suggested_version: str
    version_reason: str
    would_create_proposal: bool
    migration_suggestions: list[dict[str, Any]]
    current_version: str | None
    compatibility_mode: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "is_breaking": self.is_breaking,
            "breaking_changes": self.breaking_changes,
            "non_breaking_changes": self.non_breaking_changes,
            "guarantee_changes": self.guarantee_changes,
            "affected_consumers": self.affected_consumers,
            "affected_downstream": self.affected_downstream,
            "suggested_version": self.suggested_version,
            "version_reason": self.version_reason,
            "would_create_proposal": self.would_create_proposal,
            "migration_suggestions": self.migration_suggestions,
            "current_version": self.current_version,
            "compatibility_mode": self.compatibility_mode,
        }


async def _get_registrations(
    session: AsyncSession,
    contract_id: UUID,
) -> list[tuple[RegistrationDB, TeamDB]]:
    """Load active registrations for a contract with team info."""
    result = await session.execute(
        select(RegistrationDB, TeamDB)
        .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
        .where(RegistrationDB.contract_id == contract_id)
        .where(RegistrationDB.deleted_at.is_(None))
        .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        .where(TeamDB.deleted_at.is_(None))
    )
    rows = result.all()
    return [(reg, team) for reg, team in rows]


async def _has_pending_proposals(
    session: AsyncSession,
    asset_id: UUID,
) -> bool:
    """Check if an asset already has a pending proposal."""
    result = await session.execute(
        select(func.count(ProposalDB.id))
        .where(ProposalDB.asset_id == asset_id)
        .where(ProposalDB.status == ProposalStatus.PENDING)
    )
    count = result.scalar() or 0
    return count > 0


async def compute_impact_preview(
    session: AsyncSession,
    asset: AssetDB,
    contract: ContractDB,
    proposed_schema: dict[str, Any],
    proposed_guarantees: dict[str, Any] | None = None,
    compatibility_mode_override: CompatibilityMode | None = None,
) -> ImpactPreviewResult:
    """Compute the full impact preview for a proposed schema change.

    This is a read-only operation that does not modify any data.

    Args:
        session: Database session.
        asset: The asset being changed.
        contract: The current active contract for the asset.
        proposed_schema: The proposed new schema.
        proposed_guarantees: Optional proposed new guarantees.
        compatibility_mode_override: Override the contract's compatibility mode.

    Returns:
        ImpactPreviewResult with full analysis.
    """
    compat_mode = compatibility_mode_override or contract.compatibility_mode

    # Step 1: Diff schemas
    diff_result = diff_schemas(contract.schema_def, proposed_schema)
    breaking = diff_result.breaking_for_mode(compat_mode)
    is_breaking = len(breaking) > 0

    # Separate breaking vs non-breaking changes
    non_breaking = [c for c in diff_result.changes if c not in breaking]

    # Step 2: Diff guarantees (if provided)
    guarantee_changes_list: list[dict[str, Any]] = []
    if proposed_guarantees is not None:
        guarantee_diff = diff_guarantees(contract.guarantees or {}, proposed_guarantees)
        guarantee_changes_list = [c.to_dict() for c in guarantee_diff.changes]

    # Step 3: Compute version suggestion
    version_suggestion = compute_version_suggestion(
        current_version=contract.version,
        change_type=diff_result.change_type,
        is_compatible=not is_breaking,
        breaking_changes=[c.to_dict() for c in breaking],
    )

    # Steps 4 & 5: Load registrations and run lineage traversal concurrently
    registrations_task = _get_registrations(session, contract.id)
    affected_parties_task = get_affected_parties(
        session, asset.id, exclude_team_id=asset.owner_team_id
    )

    registrations, (affected_teams, affected_assets) = await asyncio.gather(
        registrations_task,
        affected_parties_task,
    )

    # Build affected consumers list
    affected_consumers = [
        {
            "team_id": str(reg.consumer_team_id),
            "team_name": team.name,
            "registration_id": str(reg.id),
            "contract_version": contract.version,
            "pinned_version": reg.pinned_version,
            "status": str(reg.status),
        }
        for reg, team in registrations
    ]

    # Build affected downstream list (from lineage)
    affected_downstream = [
        {
            "asset_id": a["asset_id"],
            "asset_fqn": a["asset_fqn"],
            "owner_team_id": a["owner_team_id"],
            "owner_team_name": a["owner_team_name"],
            "depth": 1,  # flat depth since get_affected_parties doesn't track depth
        }
        for a in affected_assets
    ]

    # Step 6: Generate migration suggestions if breaking
    migration_suggestions: list[dict[str, Any]] = []
    if is_breaking:
        suggestions = suggest_migrations(
            old_schema=contract.schema_def,
            new_schema=proposed_schema,
            breaking_changes=breaking,
            compatibility_mode=compat_mode,
        )
        migration_suggestions = [
            {
                "strategy": s.strategy,
                "description": s.description,
                "confidence": s.confidence,
                "suggested_schema": s.suggested_schema,
                "changes_made": s.changes_made,
            }
            for s in suggestions
        ]

    # Step 7: Determine if a proposal would be created
    has_consumers = len(registrations) > 0
    would_create_proposal = is_breaking and has_consumers

    return ImpactPreviewResult(
        is_breaking=is_breaking,
        breaking_changes=[c.to_dict() for c in breaking],
        non_breaking_changes=[c.to_dict() for c in non_breaking],
        guarantee_changes=guarantee_changes_list,
        affected_consumers=affected_consumers,
        affected_downstream=affected_downstream,
        suggested_version=version_suggestion.suggested_version,
        version_reason=version_suggestion.reason,
        would_create_proposal=would_create_proposal,
        migration_suggestions=migration_suggestions,
        current_version=contract.version,
        compatibility_mode=str(compat_mode),
    )
