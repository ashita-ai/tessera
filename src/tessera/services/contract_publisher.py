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
from sqlalchemy.exc import DBAPIError, IntegrityError
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
from tessera.services.slack_dispatcher import dispatch_slack_notifications
from tessera.services.versioning import (
    INITIAL_VERSION,
    compute_version_suggestion,
    is_graduation,
    is_prerelease,
)
from tessera.services.webhooks import send_contract_published, send_proposal_created

logger = logging.getLogger(__name__)


def _extract_field_paths(schema: dict[str, Any], prefix: str = "$.properties") -> set[str]:
    """Extract all field paths from a JSON Schema as JSONPath strings.

    Recurses into nested objects, arrays, and composition keywords
    (allOf, anyOf, oneOf) to discover all leaf field paths.
    """
    paths: set[str] = set()
    if not isinstance(schema, dict):
        return paths

    # Traverse composition keywords — merge field paths from all branches.
    # OpenAPI uses allOf for inheritance; GraphQL produces anyOf for unions.
    for keyword in ("allOf", "anyOf", "oneOf"):
        for subschema in schema.get(keyword, []):
            if isinstance(subschema, dict):
                paths.update(_extract_field_paths(subschema, prefix))

    properties = schema.get("properties", {})
    for prop_name, prop_schema in properties.items():
        path = f"{prefix}.{prop_name}"
        paths.add(path)
        if isinstance(prop_schema, dict):
            if prop_schema.get("type") == "object" and "properties" in prop_schema:
                paths.update(_extract_field_paths(prop_schema, path + ".properties"))
            if "items" in prop_schema and isinstance(prop_schema["items"], dict):
                paths.update(_extract_field_paths(prop_schema["items"], path + ".items.properties"))
    return paths


@dataclass
class ContractToPublish:
    """A contract to be published in a bulk operation."""

    asset_id: UUID
    schema_def: dict[str, Any]
    compatibility_mode: CompatibilityMode | None = None
    guarantees: dict[str, Any] | None = None
    field_descriptions: dict[str, str] = field(default_factory=dict)
    field_tags: dict[str, list[str]] = field(default_factory=dict)


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
                            field_descriptions=item.field_descriptions,
                            field_tags=item.field_tags,
                            status=ContractStatus.ACTIVE,
                            published_by=published_by,
                            published_by_user_id=published_by_user_id,
                        )
                        session.add(new_contract)
                        await session.flush()

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

                suggested_version = compute_version_suggestion(
                    current_version, diff_result.change_type, is_compatible
                ).suggested_version

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

                        # Carry forward field metadata from previous version
                        new_fields = _extract_field_paths(item.schema_def)
                        prev_descs = current_contract.field_descriptions or {}
                        prev_tags = current_contract.field_tags or {}
                        merged_descs = {p: d for p, d in prev_descs.items() if p in new_fields}
                        merged_ftags = {p: t for p, t in prev_tags.items() if p in new_fields}
                        merged_descs.update(item.field_descriptions)
                        merged_ftags.update(item.field_tags)

                        # Publish new contract
                        new_contract = ContractDB(
                            asset_id=item.asset_id,
                            version=suggested_version,
                            schema_def=item.schema_def,
                            compatibility_mode=compat_mode,
                            guarantees=item.guarantees,
                            field_descriptions=merged_descs,
                            field_tags=merged_ftags,
                            status=ContractStatus.ACTIVE,
                            published_by=published_by,
                            published_by_user_id=published_by_user_id,
                        )
                        session.add(new_contract)
                        await session.flush()

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
                            previous_version=current_contract.version,
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
                            status="proposal.created",
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
            logger.exception("Failed to publish contract for asset %s", item.asset_id)
            results.append(
                PublishResult(
                    asset_id=item.asset_id,
                    asset_fqn=asset.fqn if asset else None,
                    status="failed",
                    error=f"Internal error publishing contract for asset {item.asset_id}",
                )
            )
            failed_count += 1
            # If this is a session-level error (connection lost, etc.), stop
            # processing. Subsequent items will fail the same way.
            if isinstance(exc, DBAPIError):
                remaining = len(contracts) - len(results)
                logger.error(
                    "Database-level error detected; aborting remaining %d items",
                    remaining,
                )
                # Account for remaining unprocessed items
                for skip_item in contracts[len(results) :]:
                    results.append(
                        PublishResult(
                            asset_id=skip_item.asset_id,
                            asset_fqn=None,
                            status="failed",
                            error="Skipped — database connection lost",
                        )
                    )
                    failed_count += 1
                break

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
    FORCE_PUBLISHED = "force.published"
    PROPOSAL_CREATED = "proposal.created"
    VERSION_REQUIRED = "version.required"


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
        force_reason: str | None = None,
        audit_warning: str | None = None,
        field_descriptions: dict[str, str] | None = None,
        field_tags: dict[str, list[str]] | None = None,
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
        self.force_reason = force_reason
        self.audit_warning = audit_warning
        self.field_descriptions = field_descriptions or {}
        self.field_tags = field_tags or {}

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

    def _resolve_field_metadata(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        """Resolve field metadata by carrying forward from previous version.

        For fields that still exist in the new schema, carry forward descriptions
        and tags from the previous contract version. Drop metadata for fields that
        were removed. Explicitly provided metadata takes precedence.
        """
        if not self.current_contract:
            return self.field_descriptions, self.field_tags

        # Determine which field paths exist in the new schema
        new_fields = _extract_field_paths(self.schema_to_store)

        # Start with previous metadata, filtered to fields that still exist
        prev_descriptions: dict[str, str] = self.current_contract.field_descriptions or {}
        prev_tags: dict[str, list[str]] = self.current_contract.field_tags or {}

        merged_descriptions: dict[str, str] = {
            path: desc for path, desc in prev_descriptions.items() if path in new_fields
        }
        merged_tags: dict[str, list[str]] = {
            path: tags for path, tags in prev_tags.items() if path in new_fields
        }

        # Explicitly provided metadata overrides carried-forward values
        merged_descriptions.update(self.field_descriptions)
        merged_tags.update(self.field_tags)

        return merged_descriptions, merged_tags

    async def _publish_contract(self) -> ContractDB:
        """Create and save the new contract.

        Handles deprecation of the previous contract within the same savepoint
        and logs both deprecation and guarantee changes to the audit trail.
        """
        resolved_descriptions, resolved_tags = self._resolve_field_metadata()

        async with self.session.begin_nested():
            db_contract = ContractDB(
                asset_id=self.asset.id,
                version=self.version,
                schema_def=self.schema_to_store,
                schema_format=self.schema_format,
                compatibility_mode=self.compatibility_mode,
                guarantees=self.guarantees,
                field_descriptions=resolved_descriptions,
                field_tags=resolved_tags,
                published_by=self.published_by,
                published_by_user_id=self.published_by_user_id,
            )
            self.session.add(db_contract)

            # Deprecate old contract if exists
            if self.current_contract:
                self.current_contract.status = ContractStatus.DEPRECATED

            await self.session.flush()

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
            .where(RegistrationDB.deleted_at.is_(None))
            .where(TeamDB.deleted_at.is_(None))
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

    async def _notify_contract_published(self, contract: ContractDB) -> None:
        """Send webhook and Slack notifications for a published contract."""
        publisher_team = await self.session.get(TeamDB, self.published_by)
        publisher_team_name = publisher_team.name if publisher_team else "unknown"

        await send_contract_published(
            contract_id=contract.id,
            asset_id=self.asset.id,
            asset_fqn=self.asset.fqn,
            version=contract.version,
            producer_team_id=self.published_by,
            producer_team_name=publisher_team_name,
        )

        # Notify registered consumer teams via Slack
        consumer_team_ids = [c.team_id for c in await self._get_impacted_consumers()]
        if consumer_team_ids:
            await dispatch_slack_notifications(
                session=self.session,
                event_type="contract.published",
                team_ids=consumer_team_ids,
                payload={
                    "asset_fqn": self.asset.fqn,
                    "version": contract.version,
                    "publisher_team": publisher_team_name,
                    "contract_id": str(contract.id),
                },
            )

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
                self.compatibility_mode,
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
            await self._notify_contract_published(contract)

            return self._build_result(PublishAction.PUBLISHED, contract=contract)

        # Diff and check compatibility
        diff_result = diff_schemas(self.current_contract.schema_def, self.schema_to_store)
        is_compatible, breaking_changes = check_compatibility(
            self.current_contract.schema_def,
            self.schema_to_store,
            self.compatibility_mode,
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
                previous_version=self.current_contract.version,
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())
            await self._notify_contract_published(contract)

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
                force_reason=self.force_reason,
                previous_version=self.current_contract.version,
            )
            await invalidate_asset(str(self.asset.id))
            await cache_contract(str(contract.id), Contract.model_validate(contract).model_dump())
            await self._notify_contract_published(contract)

            # Notify affected teams via Slack about force publish
            affected_team_ids = [ap.team_id for ap in await self._get_impacted_consumers()]
            await dispatch_slack_notifications(
                session=self.session,
                event_type="force.publish",
                team_ids=affected_team_ids,
                payload={
                    "asset_fqn": self.asset.fqn,
                    "version": contract.version,
                    "publisher_team": self.publisher_team.name,
                    "publisher_user": None,
                    "reason": self.force_reason,
                    "contract_id": str(contract.id),
                },
            )

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
                previous_version=self.current_contract.version,
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
                previous_version=self.current_contract.version,
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
        # Use a savepoint so an IntegrityError from the partial unique index
        # (uq_one_pending_proposal_per_asset) rolls back only this INSERT,
        # not the outer request transaction.
        try:
            async with self.session.begin_nested():
                self.session.add(proposal)
                await self.session.flush()
        except IntegrityError:
            # Concurrent duplicate — another request already created a pending
            # proposal for this asset. Return it instead of creating a second.
            existing = await self._check_pending_proposal()
            existing_id = existing.id if existing else "unknown"
            return self._build_result(
                PublishAction.PROPOSAL_CREATED,
                proposal=existing,
                message=f"Asset already has pending proposal: {existing_id}",
            )
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

        # Dispatch per-team Slack notifications for proposal_created
        await dispatch_slack_notifications(
            session=self.session,
            event_type="proposal.created",
            team_ids=[c.team_id for c in impacted_consumers],
            payload={
                "asset_fqn": self.asset.fqn,
                "version": self.version,
                "producer_team": self.publisher_team.name,
                "affected_consumers": [c.team_name for c in impacted_consumers],
                "breaking_changes": breaking_changes_list,
                "proposal_id": str(proposal.id),
            },
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
