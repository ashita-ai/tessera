"""Bulk contract publishing service.

Provides core logic for publishing multiple contracts efficiently,
used by both the /api/v1/contracts/bulk endpoint and dbt sync.
"""

from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, ContractDB, ProposalDB
from tessera.models.enums import ChangeType, CompatibilityMode, ContractStatus, ProposalStatus
from tessera.services import get_affected_parties, validate_json_schema
from tessera.services.audit import log_contract_published, log_proposal_created
from tessera.services.cache import invalidate_asset
from tessera.services.schema_diff import check_compatibility, diff_schemas

# Named constants for version handling
INITIAL_VERSION: Final[str] = "1.0.0"
"""Version assigned to the first contract published for an asset."""


@dataclass
class ContractToPublish:
    """A contract to be published in a bulk operation."""

    asset_id: UUID
    schema_def: dict[str, Any]
    compatibility_mode: CompatibilityMode | None = None
    guarantees: dict[str, Any] | None = None


@dataclass
class PublishResult:
    """Result of attempting to publish a single contract."""

    asset_id: UUID
    asset_fqn: str | None = None
    status: str = "failed"  # will_publish, published, skipped, breaking, etc.
    contract_id: UUID | None = None
    proposal_id: UUID | None = None
    suggested_version: str | None = None
    current_version: str | None = None
    reason: str | None = None
    breaking_changes: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class BulkPublishResult:
    """Aggregate result of a bulk publish operation."""

    preview: bool
    total: int
    published: int = 0
    skipped: int = 0
    proposals_created: int = 0
    failed: int = 0
    results: list[PublishResult] = field(default_factory=list)


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string into (major, minor, patch).

    Returns (1, 0, 0) as a fallback if the version string is malformed.
    """
    base = version.split("-")[0].split("+")[0]
    parts = base.split(".")
    if len(parts) != 3:
        # Fallback to initial version components for malformed input
        return (1, 0, 0)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def compute_next_version(
    current_version: str | None,
    is_compatible: bool,
    change_type: ChangeType,
) -> str:
    """Compute the next version based on compatibility and change type."""
    if current_version is None:
        return INITIAL_VERSION

    major, minor, patch = parse_semver(current_version)

    if not is_compatible:
        return f"{major + 1}.0.0"
    elif change_type in (ChangeType.MAJOR, ChangeType.MINOR):
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


async def bulk_publish_contracts(
    session: AsyncSession,
    contracts: list[ContractToPublish],
    published_by: UUID,
    published_by_user_id: UUID | None = None,
    dry_run: bool = True,
    create_proposals_for_breaking: bool = False,
) -> BulkPublishResult:
    """Publish multiple contracts in a single operation.

    Args:
        session: Database session
        contracts: List of contracts to publish
        published_by: Team ID of the publisher
        published_by_user_id: Optional user ID who published
        dry_run: If True, only preview what would happen
        create_proposals_for_breaking: If True, create proposals for breaking changes

    Returns:
        BulkPublishResult with details of each contract's outcome
    """
    if not contracts:
        return BulkPublishResult(preview=dry_run, total=0)

    # Collect all asset IDs and fetch them in one query
    asset_ids = [c.asset_id for c in contracts]
    assets_result = await session.execute(
        select(AssetDB).where(AssetDB.id.in_(asset_ids)).where(AssetDB.deleted_at.is_(None))
    )
    assets_map: dict[UUID, AssetDB] = {a.id: a for a in assets_result.scalars().all()}

    # Fetch all active contracts for these assets in one query
    contracts_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id.in_(asset_ids))
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    active_contracts: dict[UUID, ContractDB] = {}
    for contract in contracts_result.scalars().all():
        if contract.asset_id not in active_contracts:
            active_contracts[contract.asset_id] = contract
        elif contract.published_at > active_contracts[contract.asset_id].published_at:
            active_contracts[contract.asset_id] = contract

    # Check for existing pending proposals
    pending_proposals_result = await session.execute(
        select(ProposalDB.asset_id)
        .where(ProposalDB.asset_id.in_(asset_ids))
        .where(ProposalDB.status == ProposalStatus.PENDING)
    )
    assets_with_pending_proposals = {row[0] for row in pending_proposals_result.all()}

    # Process each contract
    results: list[PublishResult] = []
    published_count = 0
    skipped_count = 0
    proposals_count = 0
    failed_count = 0

    for item in contracts:
        asset = assets_map.get(item.asset_id)

        # Asset not found
        if not asset:
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    status="failed",
                    error=f"Asset not found: {item.asset_id}",
                )
            )
            failed_count += 1
            continue

        # Validate schema
        is_valid, errors = validate_json_schema(item.schema_def)
        if not is_valid:
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="failed",
                    error=f"Invalid schema: {errors}",
                )
            )
            failed_count += 1
            continue

        # Check for pending proposal
        if item.asset_id in assets_with_pending_proposals:
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="failed",
                    error="Asset has a pending proposal. Resolve it before publishing.",
                )
            )
            failed_count += 1
            continue

        current_contract = active_contracts.get(item.asset_id)
        current_version = current_contract.version if current_contract else None

        # Determine compatibility mode
        if item.compatibility_mode:
            compat_mode = item.compatibility_mode
        elif current_contract:
            compat_mode = current_contract.compatibility_mode
        else:
            compat_mode = CompatibilityMode.BACKWARD

        # First contract - always publishable
        if not current_contract:
            suggested_version = INITIAL_VERSION
            if dry_run:
                results.append(
                    PublishResult(
                        asset_id=item.asset_id,
                        asset_fqn=asset.fqn,
                        status="will_publish",
                        suggested_version=suggested_version,
                        reason="First contract for this asset",
                    )
                )
                published_count += 1
            else:
                new_contract = ContractDB(
                    asset_id=item.asset_id,
                    version=suggested_version,
                    schema_def=item.schema_def,
                    compatibility_mode=compat_mode,
                    guarantees=item.guarantees,
                    status=ContractStatus.ACTIVE,
                    published_by=published_by,
                    published_by_user_id=published_by_user_id,
                )
                session.add(new_contract)
                await session.flush()
                await session.refresh(new_contract)

                await log_contract_published(
                    session=session,
                    contract_id=new_contract.id,
                    publisher_id=published_by,
                    version=suggested_version,
                )
                await invalidate_asset(str(item.asset_id))

                results.append(
                    PublishResult(
                        asset_id=item.asset_id,
                        asset_fqn=asset.fqn,
                        status="published",
                        contract_id=new_contract.id,
                        suggested_version=suggested_version,
                        reason="First contract for this asset",
                    )
                )
                published_count += 1
            continue

        # Existing contract - diff schemas
        diff_result = diff_schemas(current_contract.schema_def, item.schema_def)
        is_compatible, breaking_changes = check_compatibility(
            current_contract.schema_def,
            item.schema_def,
            compat_mode,
        )

        # No changes - skip
        if not diff_result.has_changes:
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="will_skip" if dry_run else "skipped",
                    current_version=current_version,
                    reason="No schema changes detected",
                )
            )
            skipped_count += 1
            continue

        suggested_version = compute_next_version(
            current_version, is_compatible, diff_result.change_type
        )

        # Compatible change - can publish
        if is_compatible:
            if dry_run:
                results.append(
                    PublishResult(
                        asset_id=item.asset_id,
                        asset_fqn=asset.fqn,
                        status="will_publish",
                        suggested_version=suggested_version,
                        current_version=current_version,
                        reason=f"Compatible {diff_result.change_type.value} change",
                    )
                )
                published_count += 1
            else:
                # Deprecate old contract
                current_contract.status = ContractStatus.DEPRECATED

                # Publish new contract
                new_contract = ContractDB(
                    asset_id=item.asset_id,
                    version=suggested_version,
                    schema_def=item.schema_def,
                    compatibility_mode=compat_mode,
                    guarantees=item.guarantees,
                    status=ContractStatus.ACTIVE,
                    published_by=published_by,
                    published_by_user_id=published_by_user_id,
                )
                session.add(new_contract)
                await session.flush()
                await session.refresh(new_contract)

                await log_contract_published(
                    session=session,
                    contract_id=new_contract.id,
                    publisher_id=published_by,
                    version=suggested_version,
                    change_type=str(diff_result.change_type.value),
                )
                await invalidate_asset(str(item.asset_id))

                results.append(
                    PublishResult(
                        asset_id=item.asset_id,
                        asset_fqn=asset.fqn,
                        status="published",
                        contract_id=new_contract.id,
                        suggested_version=suggested_version,
                        current_version=current_version,
                        reason=f"Compatible {diff_result.change_type.value} change",
                    )
                )
                published_count += 1
            continue

        # Breaking change
        breaking_changes_list = [bc.to_dict() for bc in breaking_changes]

        if dry_run:
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="breaking",
                    suggested_version=suggested_version,
                    current_version=current_version,
                    breaking_changes=breaking_changes_list,
                    reason=f"Breaking change: {len(breaking_changes)} incompatible modification(s)",
                )
            )
            if create_proposals_for_breaking:
                proposals_count += 1
            else:
                failed_count += 1
        elif create_proposals_for_breaking:
            # Create proposal for breaking change
            affected_teams, affected_assets = await get_affected_parties(
                session, item.asset_id, exclude_team_id=asset.owner_team_id
            )

            proposal = ProposalDB(
                asset_id=item.asset_id,
                proposed_schema=item.schema_def,
                change_type=diff_result.change_type,
                breaking_changes=breaking_changes_list,
                proposed_by=published_by,
                proposed_by_user_id=published_by_user_id,
                affected_teams=affected_teams,
                affected_assets=affected_assets,
                objections=[],
            )
            session.add(proposal)
            await session.flush()
            await session.refresh(proposal)

            await log_proposal_created(
                session=session,
                proposal_id=proposal.id,
                asset_id=item.asset_id,
                proposer_id=published_by,
                change_type=str(diff_result.change_type.value),
                breaking_changes=breaking_changes_list,
            )

            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="proposal_created",
                    proposal_id=proposal.id,
                    suggested_version=suggested_version,
                    current_version=current_version,
                    breaking_changes=breaking_changes_list,
                    reason=(
                        f"Breaking change: proposal created for "
                        f"{len(breaking_changes)} incompatible modification(s)"
                    ),
                )
            )
            proposals_count += 1
        else:
            # Skip breaking change
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn,
                    status="failed",
                    suggested_version=suggested_version,
                    current_version=current_version,
                    breaking_changes=breaking_changes_list,
                    error=(
                        "Breaking change requires proposal. "
                        "Use create_proposals_for_breaking=true or resolve manually."
                    ),
                )
            )
            failed_count += 1

    return BulkPublishResult(
        preview=dry_run,
        total=len(contracts),
        published=published_count,
        skipped=skipped_count,
        proposals_created=proposals_count,
        failed=failed_count,
        results=results,
    )
