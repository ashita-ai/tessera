"""Contract publishing services.

Provides core logic for publishing contracts:
- Bulk publishing: efficiently handle multiple contracts
- Single publishing: ContractPublishingWorkflow for the API endpoint
"""

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, AuditRunDB, ContractDB, ProposalDB, RegistrationDB, TeamDB
from tessera.models import Contract, VersionSuggestion
from tessera.models.enums import (
    AuditRunStatus,
    ChangeType,
    CompatibilityMode,
    ContractStatus,
    ProposalStatus,
    RegistrationStatus,
    SchemaFormat,
    SemverMode,
)
from tessera.services.affected_parties import get_affected_parties
from tessera.services.audit import (
    log_contract_deprecated,
    log_contract_published,
    log_guarantees_updated,
    log_proposal_created,
)
from tessera.services.avro import AvroConversionError, avro_to_json_schema, validate_avro_schema
from tessera.services.cache import cache_contract, invalidate_asset
from tessera.services.schema_diff import check_compatibility, diff_schemas
from tessera.services.schema_validator import validate_json_schema
from tessera.services.slack import notify_proposal_created
from tessera.services.versioning import (
    INITIAL_VERSION,
    compute_version_suggestion,
    is_graduation,
    is_prerelease,
    parse_semver_lenient,
)
from tessera.services.webhooks import send_proposal_created

logger = logging.getLogger(__name__)


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


def compute_next_version(
    current_version: str | None,
    is_compatible: bool,
    change_type: ChangeType,
) -> str:
    """Compute the next version based on compatibility and change type."""
    if current_version is None:
        return INITIAL_VERSION

    major, minor, patch = parse_semver_lenient(current_version)

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

    # Fetch all active contracts for these assets in one query.
    # Use FOR UPDATE to prevent concurrent bulk publishes from both reading the
    # same active contract and both attempting to deprecate it.
    contracts_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id.in_(asset_ids))
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .with_for_update()
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

        try:
            async with session.begin_nested():
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

                        await log_contract_deprecated(
                            session=session,
                            contract_id=current_contract.id,
                            actor_id=published_by,
                            version=current_contract.version,
                            superseded_by=new_contract.id,
                            superseded_by_version=suggested_version,
                        )
                        await log_contract_published(
                            session=session,
                            contract_id=new_contract.id,
                            publisher_id=published_by,
                            version=suggested_version,
                            change_type=str(diff_result.change_type.value),
                        )

                        # Log guarantee changes if guarantees differ
                        old_g = current_contract.guarantees
                        new_g = item.guarantees
                        if old_g != new_g and (old_g or new_g):
                            await log_guarantees_updated(
                                session=session,
                                contract_id=new_contract.id,
                                actor_id=published_by,
                                old_guarantees=old_g,
                                new_guarantees=new_g or {},
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
                            reason=(
                                f"Breaking change: {len(breaking_changes)}"
                                f" incompatible modification(s)"
                            ),
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
                        proposed_guarantees=item.guarantees,
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
        except Exception as exc:
            logger.exception("Failed to publish contract for asset %s: %s", item.asset_id, exc)
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn if asset else None,
                    status="failed",
                    error=(
                        f"Internal error publishing contract for asset {item.asset_id}"
                        f": {type(exc).__name__}: {exc}"
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


# =============================================================================
# Single Contract Publishing Workflow
# =============================================================================


class PublishAction(StrEnum):
    """Actions that can result from contract publishing."""

    PUBLISHED = "published"
    FORCE_PUBLISHED = "force_published"
    PROPOSAL_CREATED = "proposal_created"
    VERSION_REQUIRED = "version_required"


@dataclass
class ImpactedConsumer:
    """A consumer impacted by a breaking change."""

    team_id: UUID
    team_name: str
    pinned_version: str | None


@dataclass
class SinglePublishResult:
    """Result of a single contract publishing operation."""

    action: PublishAction
    contract: ContractDB | None = None
    proposal: ProposalDB | None = None
    change_type: ChangeType | None = None
    breaking_changes: list[dict[str, Any]] = field(default_factory=list)
    message: str | None = None
    warning: str | None = None
    version_auto_generated: bool = False
    schema_converted_from: str | None = None
    audit_warning: str | None = None
    version_suggestion: VersionSuggestion | None = None
    impacted_consumers: list[ImpactedConsumer] = field(default_factory=list)


class ContractPublishingWorkflow:
    """Orchestrates single contract publishing.

    This class encapsulates the complex logic for publishing a single contract,
    including validation, version handling, compatibility checking, and
    proposal creation for breaking changes.

    Usage:
        workflow = ContractPublishingWorkflow(
            session=session,
            asset=asset,
            publisher_team=team,
            schema_def=schema,
            schema_format=SchemaFormat.JSON_SCHEMA,
            compatibility_mode=CompatibilityMode.BACKWARD,
            version=None,  # Auto-generate
            published_by=team_id,
            force=False,
        )
        result = await workflow.execute()
    """

    def __init__(
        self,
        session: AsyncSession,
        asset: AssetDB,
        publisher_team: TeamDB,
        schema_def: dict[str, Any],
        schema_format: SchemaFormat,
        compatibility_mode: CompatibilityMode,
        version: str | None,
        published_by: UUID,
        published_by_user_id: UUID | None = None,
        guarantees: dict[str, Any] | None = None,
        force: bool = False,
        audit_warning: str | None = None,
    ):
        self.session = session
        self.asset = asset
        self.publisher_team = publisher_team
        self.schema_format = schema_format
        self.compatibility_mode = compatibility_mode
        self.provided_version = version
        self.published_by = published_by
        self.published_by_user_id = published_by_user_id
        self.guarantees = guarantees
        self.force = force
        self.audit_warning = audit_warning

        # Schema handling: convert Avro to JSON Schema for storage
        self.schema_to_store = schema_def
        self.schema_converted_from: str | None = None

        # State computed during execution
        self.current_contract: ContractDB | None = None
        self.version_suggestion: VersionSuggestion | None = None
        self.version: str = ""
        self.version_auto_generated: bool = False

    async def validate_schema(self) -> tuple[bool, list[str]]:
        """Validate and optionally convert the schema.

        Returns:
            Tuple of (is_valid, errors). If valid, self.schema_to_store is set.
        """
        if self.schema_format == SchemaFormat.AVRO:
            is_valid, errors = validate_avro_schema(self.schema_to_store)
            if not is_valid:
                return False, errors
            try:
                self.schema_to_store = avro_to_json_schema(self.schema_to_store)
                self.schema_converted_from = "avro"
            except AvroConversionError as e:
                return False, [f"Failed to convert Avro schema: {e.message}"]
        else:
            is_valid, errors = validate_json_schema(self.schema_to_store)
            if not is_valid:
                return False, errors

        return True, []

    async def check_version_exists(self, version: str) -> ContractDB | None:
        """Check if a version already exists for this asset."""
        result = await self.session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == self.asset.id)
            .where(ContractDB.version == version)
        )
        return result.scalar_one_or_none()

    async def _get_current_contract(self) -> ContractDB | None:
        """Get the current active contract for the asset.

        Uses ``FOR UPDATE`` to prevent concurrent publishes from reading the
        same active contract and both attempting to deprecate it.
        """
        result = await self.session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == self.asset.id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .order_by(ContractDB.published_at.desc())
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _check_pending_proposal(self) -> ProposalDB | None:
        """Check if there's already a pending proposal for this asset.

        Uses ``FOR UPDATE`` to prevent two concurrent breaking-change publishes
        from both seeing "no pending proposal" and both creating one.
        """
        result = await self.session.execute(
            select(ProposalDB)
            .where(ProposalDB.asset_id == self.asset.id)
            .where(ProposalDB.status == ProposalStatus.PENDING)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _publish_contract(self) -> ContractDB:
        """Create and save the new contract.

        Handles deprecation of the previous contract within the same savepoint
        and logs both deprecation and guarantee changes to the audit trail.
        """
        async with self.session.begin_nested():
            db_contract = ContractDB(
                asset_id=self.asset.id,
                version=self.version,
                schema_def=self.schema_to_store,
                schema_format=self.schema_format,
                compatibility_mode=self.compatibility_mode,
                guarantees=self.guarantees,
                published_by=self.published_by,
                published_by_user_id=self.published_by_user_id,
            )
            self.session.add(db_contract)

            # Deprecate old contract if exists
            if self.current_contract:
                self.current_contract.status = ContractStatus.DEPRECATED

            await self.session.flush()
            await self.session.refresh(db_contract)

            # Audit: log deprecation of the old contract
            if self.current_contract:
                await log_contract_deprecated(
                    session=self.session,
                    contract_id=self.current_contract.id,
                    actor_id=self.published_by,
                    version=self.current_contract.version,
                    superseded_by=db_contract.id,
                    superseded_by_version=self.version,
                )

                # Audit: log guarantee changes if guarantees differ
                old_g = self.current_contract.guarantees
                new_g = self.guarantees
                if old_g != new_g and (old_g or new_g):
                    await log_guarantees_updated(
                        session=self.session,
                        contract_id=db_contract.id,
                        actor_id=self.published_by,
                        old_guarantees=old_g,
                        new_guarantees=new_g or {},
                    )

        return db_contract

    async def _get_impacted_consumers(self) -> list[ImpactedConsumer]:
        """Get consumers who would be impacted by a breaking change."""
        if not self.current_contract:
            return []

        result = await self.session.execute(
            select(RegistrationDB, TeamDB)
            .join(TeamDB, RegistrationDB.consumer_team_id == TeamDB.id)
            .where(RegistrationDB.contract_id == self.current_contract.id)
            .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
        )
        consumers = []
        for reg, team in result.all():
            consumers.append(
                ImpactedConsumer(
                    team_id=team.id,
                    team_name=team.name,
                    pinned_version=reg.pinned_version,
                )
            )
        return consumers

    def _build_result(
        self,
        action: PublishAction,
        contract: ContractDB | None = None,
        proposal: ProposalDB | None = None,
        change_type: ChangeType | None = None,
        breaking_changes: list[dict[str, Any]] | None = None,
        message: str | None = None,
        warning: str | None = None,
        impacted_consumers: list[ImpactedConsumer] | None = None,
    ) -> SinglePublishResult:
        """Build a standardized result object."""
        return SinglePublishResult(
            action=action,
            contract=contract,
            proposal=proposal,
            change_type=change_type,
            breaking_changes=breaking_changes or [],
            message=message,
            warning=warning,
            version_auto_generated=self.version_auto_generated,
            schema_converted_from=self.schema_converted_from,
            audit_warning=self.audit_warning,
            version_suggestion=self.version_suggestion,
            impacted_consumers=impacted_consumers or [],
        )

    async def execute(self) -> SinglePublishResult:
        """Execute the contract publishing workflow.

        This method assumes validation has already been done by the caller
        (asset exists, auth checks passed, schema validated).

        Returns:
            SinglePublishResult with the outcome of the operation.
        """
        # Get current contract
        self.current_contract = await self._get_current_contract()

        # Compute version suggestion
        if self.current_contract:
            diff = diff_schemas(self.current_contract.schema_def, self.schema_to_store)
            is_compat, breaks = check_compatibility(
                self.current_contract.schema_def,
                self.schema_to_store,
                self.current_contract.compatibility_mode,
            )
            self.version_suggestion = compute_version_suggestion(
                self.current_contract.version,
                diff.change_type,
                is_compat,
                [bc.to_dict() for bc in breaks],
            )
        else:
            self.version_suggestion = compute_version_suggestion(None, ChangeType.PATCH, True)

        # Handle version
        semver_mode = self.asset.semver_mode
        if self.provided_version is None:
            if semver_mode == SemverMode.SUGGEST:
                # Return suggestion without auto-generating
                return self._build_result(PublishAction.VERSION_REQUIRED)
            else:
                # AUTO mode: use suggested version
                self.version_auto_generated = True
                self.version = self.version_suggestion.suggested_version
        else:
            self.version = self.provided_version

        # First contract = auto-publish
        if not self.current_contract:
            contract = await self._publish_contract()
            await log_contract_published(
                session=self.session,
                contract_id=contract.id,
                publisher_id=self.published_by,
                version=contract.version,
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())

            return self._build_result(PublishAction.PUBLISHED, contract=contract)

        # Diff and check compatibility
        diff_result = diff_schemas(self.current_contract.schema_def, self.schema_to_store)
        is_compatible, breaking_changes = check_compatibility(
            self.current_contract.schema_def,
            self.schema_to_store,
            self.current_contract.compatibility_mode,
        )
        breaking_changes_list = [bc.to_dict() for bc in breaking_changes]

        # Compatible change = auto-publish
        if is_compatible:
            contract = await self._publish_contract()
            await log_contract_published(
                session=self.session,
                contract_id=contract.id,
                publisher_id=self.published_by,
                version=contract.version,
                change_type=str(diff_result.change_type),
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())

            return self._build_result(
                PublishAction.PUBLISHED,
                contract=contract,
                change_type=diff_result.change_type,
            )

        # Breaking change with force = publish anyway
        if self.force:
            contract = await self._publish_contract()
            await log_contract_published(
                session=self.session,
                contract_id=contract.id,
                publisher_id=self.published_by,
                version=contract.version,
                change_type=str(diff_result.change_type),
                force=True,
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())

            return self._build_result(
                PublishAction.FORCE_PUBLISHED,
                contract=contract,
                change_type=diff_result.change_type,
                breaking_changes=breaking_changes_list,
                warning="Breaking change was force-published. Consumers may be affected.",
            )

        # Pre-release versions skip proposal workflow
        if is_prerelease(self.version):
            contract = await self._publish_contract()
            await log_contract_published(
                session=self.session,
                contract_id=contract.id,
                publisher_id=self.published_by,
                version=contract.version,
                change_type=str(diff_result.change_type),
                prerelease=True,
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())

            return self._build_result(
                PublishAction.PUBLISHED,
                contract=contract,
                change_type=diff_result.change_type,
                breaking_changes=breaking_changes_list,
                message="Pre-release version published. Breaking changes allowed without ack.",
            )

        # Graduation: prerelease -> release skips proposal
        if is_graduation(self.current_contract.version, self.version):
            contract = await self._publish_contract()
            await log_contract_published(
                session=self.session,
                contract_id=contract.id,
                publisher_id=self.published_by,
                version=contract.version,
                change_type=str(diff_result.change_type),
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())

            return self._build_result(
                PublishAction.PUBLISHED,
                contract=contract,
                change_type=diff_result.change_type,
                breaking_changes=breaking_changes_list,
                message=f"Graduated from {self.current_contract.version} to stable release.",
            )

        # Breaking change without force = create proposal
        existing_proposal = await self._check_pending_proposal()
        if existing_proposal:
            # Caller should handle this as a duplicate error
            return self._build_result(
                PublishAction.PROPOSAL_CREATED,
                proposal=existing_proposal,
                message=f"Asset already has pending proposal: {existing_proposal.id}",
            )

        # Create proposal
        affected_teams, affected_assets = await get_affected_parties(
            self.session, self.asset.id, exclude_team_id=self.asset.owner_team_id
        )

        proposal = ProposalDB(
            asset_id=self.asset.id,
            proposed_schema=self.schema_to_store,
            proposed_guarantees=self.guarantees,
            change_type=diff_result.change_type,
            breaking_changes=breaking_changes_list,
            proposed_by=self.published_by,
            proposed_by_user_id=self.published_by_user_id,
            affected_teams=affected_teams,
            affected_assets=affected_assets,
            objections=[],
        )
        self.session.add(proposal)
        await self.session.flush()
        await self.session.refresh(proposal)

        await log_proposal_created(
            session=self.session,
            proposal_id=proposal.id,
            asset_id=self.asset.id,
            proposer_id=self.published_by,
            change_type=str(diff_result.change_type),
            breaking_changes=breaking_changes_list,
        )

        # Get impacted consumers
        impacted_consumers = await self._get_impacted_consumers()

        # Send notifications
        await send_proposal_created(
            proposal_id=proposal.id,
            asset_id=self.asset.id,
            asset_fqn=self.asset.fqn,
            producer_team_id=self.publisher_team.id,
            producer_team_name=self.publisher_team.name,
            proposed_version=self.version,
            breaking_changes=breaking_changes_list,
            impacted_consumers=[
                {
                    "team_id": str(c.team_id),
                    "team_name": c.team_name,
                    "pinned_version": c.pinned_version,
                }
                for c in impacted_consumers
            ],
        )

        await notify_proposal_created(
            asset_fqn=self.asset.fqn,
            version=self.version,
            producer_team=self.publisher_team.name,
            affected_consumers=[c.team_name for c in impacted_consumers],
            breaking_changes=breaking_changes_list,
        )

        return self._build_result(
            PublishAction.PROPOSAL_CREATED,
            proposal=proposal,
            change_type=diff_result.change_type,
            breaking_changes=breaking_changes_list,
            message="Breaking change detected. Proposal created for consumer acknowledgment.",
            impacted_consumers=impacted_consumers,
        )


async def get_last_audit_status(
    session: AsyncSession, asset_id: UUID
) -> tuple[AuditRunStatus | None, int, Any]:
    """Get the most recent audit status for an asset.

    Returns:
        Tuple of (status, failed_count, run_at). All None if no audits.
    """
    result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .order_by(AuditRunDB.run_at.desc())
        .limit(1)
    )
    audit_run = result.scalar_one_or_none()
    if not audit_run:
        return None, 0, None
    return audit_run.status, audit_run.guarantees_failed, audit_run.run_at
