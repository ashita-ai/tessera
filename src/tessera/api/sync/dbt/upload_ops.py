"""Post-processing operations for dbt manifest upload.

Handles auto-publish, auto-register consumers, auto-create proposals,
and auto-delete stale assets — extracted from the upload endpoint to
keep individual modules under 500 lines.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.sync.dbt.mapper import (
    dbt_columns_to_json_schema,
    not_null_columns_from_guarantees,
)
from tessera.api.sync.dbt.parser import extract_field_metadata_from_columns
from tessera.api.sync.helpers import resolve_team_by_name
from tessera.db import AssetDB, ContractDB, ProposalDB, RegistrationDB, TeamDB
from tessera.models.enums import CompatibilityMode, ContractStatus, RegistrationStatus
from tessera.services import audit, get_affected_parties
from tessera.services.audit import AuditAction, log_proposal_created
from tessera.services.contract_publisher import ContractToPublish, bulk_publish_contracts
from tessera.services.schema_diff import check_compatibility, diff_schemas


def _parse_compat_mode(
    mode_str: str | None,
    fqn: str,
    warnings: list[str] | None,
) -> CompatibilityMode | None:
    """Parse a compatibility mode string, returning None on invalid input."""
    if not mode_str:
        return None
    try:
        return CompatibilityMode(mode_str.lower())
    except ValueError:
        if warnings is not None:
            warnings.append(f"{fqn}: Unknown compatibility_mode, defaulting to backward")
        return None


async def get_active_contract(session: AsyncSession, asset_id: UUID) -> ContractDB | None:
    """Fetch the active contract for an asset, if any."""
    result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
    )
    return result.scalar_one_or_none()


async def _registration_exists(
    session: AsyncSession, contract_id: UUID, consumer_team_id: UUID
) -> bool:
    """Check whether a registration already exists."""
    result = await session.execute(
        select(RegistrationDB)
        .where(RegistrationDB.contract_id == contract_id)
        .where(RegistrationDB.consumer_team_id == consumer_team_id)
    )
    return result.scalar_one_or_none() is not None


async def auto_publish_contracts(
    session: AsyncSession,
    new_assets: list[tuple[AssetDB, dict[str, Any], dict[str, Any] | None, str | None]],
    existing_assets: list[
        tuple[AssetDB, dict[str, Any], dict[str, Any] | None, str | None, ContractDB | None]
    ],
    warnings: list[str],
) -> int:
    """Bulk-publish contracts for new and existing assets. Returns count published."""
    await session.flush()

    contracts_to_publish: list[ContractToPublish] = []
    asset_publishers: dict[UUID, tuple[UUID, UUID | None]] = {}

    for asset, columns, asset_guarantees, compat_mode_str in new_assets:
        try:
            nn = not_null_columns_from_guarantees(asset_guarantees)
            schema_def = dbt_columns_to_json_schema(columns, not_null_columns=nn)
            f_descs, f_tags = extract_field_metadata_from_columns(columns)
            compat_mode = _parse_compat_mode(compat_mode_str, asset.fqn, warnings)
            contracts_to_publish.append(
                ContractToPublish(
                    asset_id=asset.id,
                    schema_def=schema_def,
                    compatibility_mode=compat_mode,
                    guarantees=asset_guarantees,
                    field_descriptions=f_descs,
                    field_tags=f_tags,
                )
            )
            asset_publishers[asset.id] = (asset.owner_team_id, asset.owner_user_id)
        except Exception as e:
            warnings.append(f"{asset.fqn}: Failed to prepare contract ({type(e).__name__}): {e}")

    for asset, columns, asset_guarantees, compat_mode_str, _existing in existing_assets:
        try:
            nn = not_null_columns_from_guarantees(asset_guarantees)
            schema_def = dbt_columns_to_json_schema(columns, not_null_columns=nn)
            f_descs, f_tags = extract_field_metadata_from_columns(columns)
            compat_mode = _parse_compat_mode(compat_mode_str, asset.fqn, warnings=None)
            contracts_to_publish.append(
                ContractToPublish(
                    asset_id=asset.id,
                    schema_def=schema_def,
                    compatibility_mode=compat_mode,
                    guarantees=asset_guarantees,
                    field_descriptions=f_descs,
                    field_tags=f_tags,
                )
            )
            asset_publishers[asset.id] = (asset.owner_team_id, asset.owner_user_id)
        except Exception as e:
            warnings.append(f"{asset.fqn}: Failed to prepare contract ({type(e).__name__}): {e}")

    if not contracts_to_publish:
        return 0

    first_team_id, first_user_id = asset_publishers[contracts_to_publish[0].asset_id]
    bulk_result = await bulk_publish_contracts(
        session=session,
        contracts=contracts_to_publish,
        published_by=first_team_id,
        published_by_user_id=first_user_id,
        dry_run=False,
        create_proposals_for_breaking=False,
    )

    for pub_result in bulk_result.results:
        if pub_result.status == "failed" and pub_result.error:
            fqn = pub_result.asset_fqn or str(pub_result.asset_id)
            warnings.append(f"{fqn}: {pub_result.error}")

    return bulk_result.published


async def auto_register_consumers(
    session: AsyncSession,
    asset_consumer_map: dict[str, tuple[AssetDB, UUID, list[str], list[dict[str, Any]]]],
    node_id_to_fqn: dict[str, str],
    infer_from_refs: bool,
    team_cache: dict[str, TeamDB | None],
    warnings: list[str],
) -> int:
    """Register consumers from refs and meta.tessera.consumers. Returns count created."""
    # Build FQN -> asset lookup
    fqn_to_asset: dict[str, AssetDB] = {}
    all_fqns = list(node_id_to_fqn.values())
    if all_fqns:
        existing_assets_result = await session.execute(
            select(AssetDB).where(AssetDB.fqn.in_(all_fqns)).where(AssetDB.deleted_at.is_(None))
        )
        for asset in existing_assets_result.scalars().all():
            fqn_to_asset[asset.fqn] = asset

    # Include assets from the consumer map (may not be flushed yet)
    for fqn, (asset, _team_id, _deps, _consumers) in asset_consumer_map.items():
        fqn_to_asset[fqn] = asset

    registrations_created = 0

    for consumer_fqn, (
        consumer_asset,
        consumer_team_id,
        depends_on_node_ids,
        meta_consumers,
    ) in asset_consumer_map.items():
        # From refs (depends_on)
        if infer_from_refs:
            for dep_node_id in depends_on_node_ids:
                upstream_fqn = node_id_to_fqn.get(dep_node_id)
                if not upstream_fqn:
                    continue
                upstream_asset = fqn_to_asset.get(upstream_fqn)
                if not upstream_asset:
                    continue

                contract = await get_active_contract(session, upstream_asset.id)
                if not contract:
                    continue
                if await _registration_exists(session, contract.id, consumer_team_id):
                    continue

                session.add(
                    RegistrationDB(
                        contract_id=contract.id,
                        consumer_team_id=consumer_team_id,
                        status=RegistrationStatus.ACTIVE,
                    )
                )
                registrations_created += 1

        # From meta.tessera.consumers
        for consumer_entry in meta_consumers:
            consumer_team_name = consumer_entry.get("team")
            if not consumer_team_name:
                continue

            if consumer_team_name not in team_cache:
                team_cache[consumer_team_name] = await resolve_team_by_name(
                    session, consumer_team_name
                )
            team = team_cache[consumer_team_name]
            if not team:
                warnings.append(f"{consumer_fqn}: consumer team '{consumer_team_name}' not found")
                continue

            contract = await get_active_contract(session, consumer_asset.id)
            if not contract:
                warnings.append(f"{consumer_fqn}: no active contract for '{consumer_team_name}'")
                continue
            if await _registration_exists(session, contract.id, team.id):
                continue

            session.add(
                RegistrationDB(
                    contract_id=contract.id,
                    consumer_team_id=team.id,
                    status=RegistrationStatus.ACTIVE,
                )
            )
            registrations_created += 1

    return registrations_created


async def auto_create_proposals(
    session: AsyncSession,
    assets_for_proposals: list[
        tuple[
            AssetDB,
            dict[str, Any],
            dict[str, Any] | None,
            ContractDB,
            UUID,
            UUID | None,
        ]
    ],
) -> tuple[int, list[dict[str, Any]]]:
    """Create proposals for breaking schema changes. Returns (count, info list)."""
    await session.flush()
    proposals_created = 0
    proposals_info: list[dict[str, Any]] = []

    for (
        asset,
        columns,
        asset_guarantees,
        existing_contract,
        team_id,
        user_id,
    ) in assets_for_proposals:
        nn = not_null_columns_from_guarantees(asset_guarantees)
        proposed_schema = dbt_columns_to_json_schema(columns, not_null_columns=nn)
        existing_schema = existing_contract.schema_def

        diff_result = diff_schemas(existing_schema, proposed_schema)
        is_compatible, breaking_changes_list = check_compatibility(
            existing_schema,
            proposed_schema,
            existing_contract.compatibility_mode,
        )

        if is_compatible or not breaking_changes_list:
            continue

        affected_teams, affected_assets = await get_affected_parties(
            session, asset.id, exclude_team_id=asset.owner_team_id
        )

        db_proposal = ProposalDB(
            asset_id=asset.id,
            proposed_schema=proposed_schema,
            proposed_guarantees=asset_guarantees,
            change_type=diff_result.change_type,
            breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
            proposed_by=team_id,
            proposed_by_user_id=user_id,
            affected_teams=affected_teams,
            affected_assets=affected_assets,
            objections=[],
        )
        session.add(db_proposal)
        await session.flush()

        await log_proposal_created(
            session,
            proposal_id=db_proposal.id,
            asset_id=asset.id,
            proposer_id=team_id,
            change_type=diff_result.change_type.value,
            breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
        )

        proposals_created += 1
        proposals_info.append(
            {
                "proposal_id": str(db_proposal.id),
                "asset_id": str(asset.id),
                "asset_fqn": asset.fqn,
                "change_type": diff_result.change_type.value,
                "breaking_changes_count": len(breaking_changes_list),
            }
        )

    return proposals_created, proposals_info


def _build_fqn(node: dict[str, Any]) -> str:
    """Build a fully-qualified name from dbt node metadata."""
    database = node.get("database", "")
    schema = node.get("schema", "")
    name = node.get("name", "")
    return f"{database}.{schema}.{name}".lower()


async def auto_delete_stale_assets(
    session: AsyncSession,
    manifest: dict[str, Any],
    owner_team_id: UUID,
    actor_team_id: UUID,
) -> tuple[int, list[str]]:
    """Soft-delete dbt-managed assets not present in the manifest.

    Returns (count, fqns).
    """
    manifest_fqns: set[str] = set()

    for _node_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") in ("model", "seed", "snapshot"):
            manifest_fqns.add(_build_fqn(node))

    for _source_id, source in manifest.get("sources", {}).items():
        manifest_fqns.add(_build_fqn(source))

    # Scoped to the requesting team to prevent cross-team deletions
    existing_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.owner_team_id == owner_team_id)
    )

    deleted = 0
    deleted_fqns: list[str] = []

    for asset in existing_result.scalars().all():
        if asset.fqn in manifest_fqns:
            continue
        metadata = asset.metadata_ or {}
        if not (metadata.get("dbt_node_id") or metadata.get("dbt_source_id")):
            continue

        asset.deleted_at = datetime.now(UTC)
        deleted += 1
        deleted_fqns.append(asset.fqn)

        await audit.log_event(
            session=session,
            entity_type="asset",
            entity_id=asset.id,
            action=AuditAction.ASSET_DELETED,
            actor_id=actor_team_id,
            payload={
                "fqn": asset.fqn,
                "triggered_by": "dbt_sync_upload_auto_delete",
            },
        )

    return deleted, deleted_fqns
