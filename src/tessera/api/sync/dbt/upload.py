"""dbt manifest upload endpoint."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import BadRequestError, ConflictError, ErrorCode
from tessera.api.rate_limit import limit_admin
from tessera.api.sync.dbt.mapper import map_dbt_resource_type
from tessera.api.sync.dbt.models import DbtManifestUploadRequest
from tessera.api.sync.dbt.parser import (
    TesseraMetaConfig,
    extract_asset_tags_from_node,
    extract_guarantees_from_tests,
    extract_tessera_meta,
)
from tessera.api.sync.dbt.upload_ops import (
    auto_create_proposals,
    auto_delete_stale_assets,
    auto_publish_contracts,
    auto_register_consumers,
    get_active_contract,
)
from tessera.api.sync.helpers import (
    deep_merge_metadata,
    resolve_team_by_name,
    resolve_user_by_email,
)
from tessera.db import AssetDB, AssetDependencyDB, ContractDB, TeamDB, UserDB, get_session
from tessera.models.enums import DependencyType, ResourceType
from tessera.services import audit
from tessera.services.audit import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter()

# NOTE: sync_from_dbt endpoint removed (security hardening, Spec 04).
# It accepted a server-side file path (manifest_path) enabling arbitrary file reads
# via path traversal. Use upload_dbt_manifest (POST /dbt/upload) instead, which
# accepts manifest JSON in the request body.


def _build_fqn(node: dict[str, Any]) -> str:
    """Build a fully-qualified name from dbt node metadata."""
    database = node.get("database", "")
    schema = node.get("schema", "")
    name = node.get("name", "")
    return f"{database}.{schema}.{name}".lower()


def _build_node_id_to_fqn(manifest: dict[str, Any]) -> dict[str, str]:
    """Build a mapping of dbt node IDs to FQNs for dependency resolution."""
    mapping: dict[str, str] = {}

    for node_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") in ("model", "seed", "snapshot"):
            mapping[node_id] = _build_fqn(node)

    for source_id, source in manifest.get("sources", {}).items():
        mapping[source_id] = _build_fqn(source)

    return mapping


async def _resolve_ownership(
    tessera_meta: TesseraMetaConfig,
    default_team_id: UUID | None,
    team_cache: dict[str, TeamDB | None],
    user_cache: dict[str, UserDB | None],
    session: AsyncSession,
    fqn: str,
    warnings: list[str],
) -> tuple[UUID | None, UUID | None]:
    """Resolve team and user IDs from tessera meta, falling back to defaults.

    Returns (team_id, user_id). team_id may be None if unresolvable.
    """
    resolved_team_id = default_team_id
    resolved_user_id: UUID | None = None

    if tessera_meta.owner_team:
        if tessera_meta.owner_team not in team_cache:
            team_cache[tessera_meta.owner_team] = await resolve_team_by_name(
                session, tessera_meta.owner_team
            )
        team = team_cache[tessera_meta.owner_team]
        if team:
            resolved_team_id = team.id
        else:
            warnings.append(
                f"{fqn}: owner_team '{tessera_meta.owner_team}' not found, using default"
            )

    if tessera_meta.owner_user:
        if tessera_meta.owner_user not in user_cache:
            user_cache[tessera_meta.owner_user] = await resolve_user_by_email(
                session, tessera_meta.owner_user
            )
        user = user_cache[tessera_meta.owner_user]
        if user:
            resolved_user_id = user.id
        else:
            warnings.append(f"{fqn}: owner_user '{tessera_meta.owner_user}' not found")

    return resolved_team_id, resolved_user_id


def _merge_meta_guarantees(
    guarantees: dict[str, Any] | None,
    tessera_meta: TesseraMetaConfig,
) -> dict[str, Any] | None:
    """Merge freshness/volume from tessera meta into guarantees dict."""
    if not (tessera_meta.freshness or tessera_meta.volume):
        return guarantees
    if guarantees is None:
        guarantees = {}
    if tessera_meta.freshness:
        guarantees["freshness"] = tessera_meta.freshness
    if tessera_meta.volume:
        guarantees["volume"] = tessera_meta.volume
    return guarantees


def _build_node_metadata(
    node: dict[str, Any],
    node_id: str,
    resource_type: str,
    node_id_to_fqn: dict[str, str],
    guarantees: dict[str, Any] | None,
    tessera_meta: TesseraMetaConfig,
    *,
    is_source: bool = False,
) -> dict[str, Any]:
    """Build the metadata dict stored on an asset from a dbt node."""
    depends_on_node_ids = node.get("depends_on", {}).get("nodes", [])
    depends_on_fqns = [
        node_id_to_fqn[dep_id] for dep_id in depends_on_node_ids if dep_id in node_id_to_fqn
    ]

    id_key = "dbt_source_id" if is_source else "dbt_node_id"
    metadata: dict[str, Any] = {
        id_key: node_id,
        "resource_type": resource_type,
        "description": node.get("description", ""),
    }

    if not is_source:
        metadata["tags"] = node.get("tags", [])
        metadata["dbt_fqn"] = node.get("fqn", [])
        metadata["path"] = node.get("path", "")
        metadata["depends_on"] = depends_on_fqns

    metadata["columns"] = {
        col_name: {
            "description": col_info.get("description", ""),
            "data_type": col_info.get("data_type"),
        }
        for col_name, col_info in node.get("columns", {}).items()
    }

    if guarantees:
        metadata["guarantees"] = guarantees
    if tessera_meta.consumers:
        metadata["tessera_consumers"] = tessera_meta.consumers

    return metadata


def _dependency_type_for_node_id(node_id: str) -> DependencyType:
    """Determine DependencyType from a dbt node ID prefix.

    Model-to-model edges are TRANSFORMS. Everything else (source, seed,
    snapshot) is CONSUMES.
    """
    if node_id.startswith("model."):
        return DependencyType.TRANSFORMS
    return DependencyType.CONSUMES


async def _sync_asset_dependencies(
    session: AsyncSession,
    asset: AssetDB,
    depends_on_node_ids: list[str],
    node_id_to_fqn: dict[str, str],
    assets_by_fqn: dict[str, AssetDB],
) -> dict[str, int]:
    """Sync AssetDependencyDB rows from dbt depends_on for a single asset.

    Creates new rows for dependencies that don't exist yet, and soft-deletes
    rows for dependencies that were removed from the manifest. Reactivates
    previously soft-deleted rows if the dependency reappears.

    Returns counts: {"created": N, "reactivated": M, "soft_deleted": P, "skipped": Q}
    """
    counts = {"created": 0, "reactivated": 0, "soft_deleted": 0, "skipped": 0}

    # Resolve node IDs to (asset, dependency_type) pairs
    resolved: dict[UUID, DependencyType] = {}
    for node_id in depends_on_node_ids:
        fqn = node_id_to_fqn.get(node_id)
        if not fqn:
            counts["skipped"] += 1
            continue
        dep_asset = assets_by_fqn.get(fqn)
        if not dep_asset:
            logger.warning("Dependency FQN %s not found in Tessera, skipping", fqn)
            counts["skipped"] += 1
            continue
        if dep_asset.id == asset.id:
            continue
        resolved[dep_asset.id] = _dependency_type_for_node_id(node_id)

    # Fetch all existing dependency rows for this asset (including soft-deleted)
    existing_result = await session.execute(
        select(AssetDependencyDB).where(
            AssetDependencyDB.dependent_asset_id == asset.id,
        )
    )
    existing_rows = {
        (row.dependency_asset_id, row.dependency_type): row
        for row in existing_result.scalars().all()
    }

    # Upsert: create or reactivate
    seen_keys: set[tuple[UUID, DependencyType]] = set()
    for dep_asset_id, dep_type in resolved.items():
        key = (dep_asset_id, dep_type)
        seen_keys.add(key)
        existing = existing_rows.get(key)
        if existing:
            if existing.deleted_at is not None:
                existing.deleted_at = None
                counts["reactivated"] += 1
            # else: already active, nothing to do
        else:
            session.add(
                AssetDependencyDB(
                    dependent_asset_id=asset.id,
                    dependency_asset_id=dep_asset_id,
                    dependency_type=dep_type,
                )
            )
            counts["created"] += 1

    # Soft-delete rows not in the current depends_on
    for key, row in existing_rows.items():
        if key not in seen_keys and row.deleted_at is None:
            row.deleted_at = datetime.now(UTC)
            counts["soft_deleted"] += 1

    return counts


@router.post("/dbt/upload")
@limit_admin
async def upload_dbt_manifest(
    request: Request,
    upload_req: DbtManifestUploadRequest,
    auth: Auth,
    response: Response,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Import assets from an uploaded dbt manifest.json.

    Accepts manifest JSON in the request body with conflict handling options:
    - overwrite: Update existing assets with new data
    - ignore: Skip assets that already exist (default)
    - fail: Return error if any asset already exists
    """
    manifest = upload_req.manifest
    owner_team_id = upload_req.owner_team_id
    conflict_mode = upload_req.conflict_mode

    if conflict_mode not in ("overwrite", "ignore", "fail"):
        raise BadRequestError(
            f"Invalid conflict_mode: {conflict_mode}. Use 'overwrite', 'ignore', or 'fail'",
            code=ErrorCode.CONFLICT_MODE_INVALID,
        )

    # Counters
    assets_created = 0
    assets_updated = 0
    assets_skipped = 0
    tests_extracted = 0
    conflicts: list[str] = []
    ownership_warnings: list[str] = []
    contract_warnings: list[str] = []
    registration_warnings: list[str] = []

    # Audit tracking
    created_assets_audit: list[tuple[AssetDB, UUID]] = []
    updated_assets_audit: list[tuple[AssetDB, str, UUID]] = []

    # Post-processing collectors
    assets_for_proposals: list[
        tuple[
            AssetDB,
            dict[str, Any],
            dict[str, Any] | None,
            ContractDB,
            UUID,
            UUID | None,
        ]
    ] = []
    new_assets_for_contracts: list[
        tuple[AssetDB, dict[str, Any], dict[str, Any] | None, str | None]
    ] = []
    existing_assets_for_contracts: list[
        tuple[
            AssetDB,
            dict[str, Any],
            dict[str, Any] | None,
            str | None,
            ContractDB | None,
        ]
    ] = []
    asset_consumer_map: dict[str, tuple[AssetDB, UUID, list[str], list[dict[str, Any]]]] = {}
    dependency_sync_queue: list[tuple[AssetDB, list[str]]] = []

    # Caches
    team_cache: dict[str, TeamDB | None] = {}
    user_cache: dict[str, UserDB | None] = {}
    node_id_to_fqn = _build_node_id_to_fqn(manifest)

    # ---- Process nodes and sources ----
    entries: list[tuple[str, dict[str, Any], str, bool]] = []

    for node_id, node in manifest.get("nodes", {}).items():
        rt = node.get("resource_type")
        if rt in ("model", "seed", "snapshot"):
            entries.append((node_id, node, rt, False))

    for source_id, source in manifest.get("sources", {}).items():
        entries.append((source_id, source, "source", True))

    all_nodes = manifest.get("nodes", {})

    for entry_id, node, resource_type, is_source in entries:
        fqn = _build_fqn(node)
        result = await session.execute(select(AssetDB).where(AssetDB.fqn == fqn))
        existing = result.scalar_one_or_none()

        if existing:
            if conflict_mode == "fail":
                conflicts.append(fqn)
                continue
            elif conflict_mode == "ignore":
                assets_skipped += 1
                continue

        tessera_meta = extract_tessera_meta(node)
        resolved_team_id, resolved_user_id = await _resolve_ownership(
            tessera_meta,
            owner_team_id,
            team_cache,
            user_cache,
            session,
            fqn,
            ownership_warnings,
        )

        if resolved_team_id is None:
            ownership_warnings.append(
                f"{fqn}: No owner_team_id provided and no meta.tessera.owner_team set, skipping"
            )
            assets_skipped += 1
            continue

        guarantees = extract_guarantees_from_tests(entry_id, node, all_nodes)
        if guarantees:
            tests_extracted += 1
        guarantees = _merge_meta_guarantees(guarantees, tessera_meta)

        metadata = _build_node_metadata(
            node,
            entry_id,
            resource_type,
            node_id_to_fqn,
            guarantees,
            tessera_meta,
            is_source=is_source,
        )
        columns = node.get("columns", {})
        depends_on_node_ids = node.get("depends_on", {}).get("nodes", [])
        infer_refs = upload_req.infer_consumers_from_refs and not is_source

        if existing:
            existing.metadata_ = deep_merge_metadata(
                existing.metadata_ or {},
                metadata,
            )
            existing.owner_team_id = resolved_team_id
            existing.resource_type = (
                ResourceType.SOURCE if is_source else map_dbt_resource_type(resource_type)
            )
            existing.tags = extract_asset_tags_from_node(node)
            if resolved_user_id:
                existing.owner_user_id = resolved_user_id
            assets_updated += 1
            updated_assets_audit.append((existing, fqn, resolved_team_id))

            if upload_req.auto_create_proposals and columns:
                contract = await get_active_contract(session, existing.id)
                if contract:
                    assets_for_proposals.append(
                        (
                            existing,
                            columns,
                            guarantees,
                            contract,
                            resolved_team_id,
                            resolved_user_id,
                        )
                    )

            if not is_source:
                dependency_sync_queue.append((existing, depends_on_node_ids))

            if upload_req.auto_register_consumers:
                asset_consumer_map[fqn] = (
                    existing,
                    resolved_team_id,
                    depends_on_node_ids if infer_refs else [],
                    tessera_meta.consumers,
                )

            if upload_req.auto_publish_contracts and columns:
                contract = await get_active_contract(session, existing.id)
                existing_assets_for_contracts.append(
                    (
                        existing,
                        columns,
                        guarantees,
                        tessera_meta.compatibility_mode,
                        contract,
                    )
                )
        else:
            asset_tags = extract_asset_tags_from_node(node)
            new_asset = AssetDB(
                fqn=fqn,
                owner_team_id=resolved_team_id,
                owner_user_id=resolved_user_id,
                resource_type=(
                    ResourceType.SOURCE if is_source else map_dbt_resource_type(resource_type)
                ),
                metadata_=metadata,
                tags=asset_tags,
            )
            session.add(new_asset)
            assets_created += 1
            created_assets_audit.append((new_asset, resolved_team_id))

            if upload_req.auto_publish_contracts and columns:
                new_assets_for_contracts.append(
                    (new_asset, columns, guarantees, tessera_meta.compatibility_mode)
                )

            if not is_source:
                dependency_sync_queue.append((new_asset, depends_on_node_ids))

            if upload_req.auto_register_consumers:
                asset_consumer_map[fqn] = (
                    new_asset,
                    resolved_team_id,
                    depends_on_node_ids if infer_refs else [],
                    tessera_meta.consumers,
                )

    # ---- Conflict check ----
    if conflict_mode == "fail" and conflicts:
        raise ConflictError(
            ErrorCode.SYNC_CONFLICT,
            f"Found {len(conflicts)} existing assets",
            details={"conflicts": conflicts[:20]},
        )

    # ---- Dependency sync ----
    # Flush first so new assets have IDs assigned, then build the FQN lookup.
    await session.flush()

    dependencies_created = 0
    dependency_warnings: list[str] = []
    if dependency_sync_queue:
        # Build FQN→asset lookup from the database (covers assets from this sync
        # and any pre-existing assets that dependencies may reference).
        all_fqns: set[str] = set()
        for _asset, dep_node_ids in dependency_sync_queue:
            for nid in dep_node_ids:
                dep_fqn = node_id_to_fqn.get(nid)
                if dep_fqn:
                    all_fqns.add(dep_fqn)

        assets_by_fqn: dict[str, AssetDB] = {}
        if all_fqns:
            fqn_result = await session.execute(
                select(AssetDB).where(
                    AssetDB.fqn.in_(list(all_fqns)),
                    AssetDB.deleted_at.is_(None),
                )
            )
            assets_by_fqn = {a.fqn: a for a in fqn_result.scalars().all()}

        for sync_asset, dep_node_ids in dependency_sync_queue:
            try:
                counts = await _sync_asset_dependencies(
                    session, sync_asset, dep_node_ids, node_id_to_fqn, assets_by_fqn
                )
                dependencies_created += counts["created"] + counts["reactivated"]
            except Exception:
                logger.exception("Failed to sync dependencies for %s", sync_asset.fqn)
                dependency_warnings.append(f"{sync_asset.fqn}: failed to sync dependencies")

    # ---- Post-processing ----
    contracts_published = 0
    if upload_req.auto_publish_contracts:
        contracts_published = await auto_publish_contracts(
            session,
            new_assets_for_contracts,
            existing_assets_for_contracts,
            contract_warnings,
        )

    registrations_created = 0
    if upload_req.auto_register_consumers and asset_consumer_map:
        registrations_created = await auto_register_consumers(
            session,
            asset_consumer_map,
            node_id_to_fqn,
            upload_req.infer_consumers_from_refs,
            team_cache,
            registration_warnings,
        )

    proposals_created = 0
    proposals_info: list[dict[str, Any]] = []
    if upload_req.auto_create_proposals and assets_for_proposals:
        proposals_created, proposals_info = await auto_create_proposals(
            session, assets_for_proposals
        )

    await session.flush()

    assets_deleted = 0
    deleted_assets_info: list[str] = []
    if upload_req.auto_delete:
        resolved_delete_team = upload_req.owner_team_id or auth.team_id
        assets_deleted, deleted_assets_info = await auto_delete_stale_assets(
            session, manifest, resolved_delete_team, auth.team_id
        )

    # ---- Audit logging ----
    for asset, team_id in created_assets_audit:
        await audit.log_event(
            session=session,
            entity_type="asset",
            entity_id=asset.id,
            action=AuditAction.ASSET_CREATED,
            actor_id=team_id,
            payload={"fqn": asset.fqn, "triggered_by": "dbt_sync_upload"},
        )
    for asset, fqn, team_id in updated_assets_audit:
        await audit.log_event(
            session=session,
            entity_type="asset",
            entity_id=asset.id,
            action=AuditAction.ASSET_UPDATED,
            actor_id=team_id,
            payload={"fqn": fqn, "triggered_by": "dbt_sync_upload"},
        )

    await audit.log_event(
        session=session,
        entity_type="sync",
        entity_id=auth.team_id,
        action=AuditAction.DBT_SYNC_UPLOAD,
        actor_id=auth.team_id,
        payload={
            "assets_created": assets_created,
            "assets_updated": assets_updated,
            "assets_skipped": assets_skipped,
            "dependencies_synced": dependencies_created,
            "contracts_published": contracts_published,
            "proposals_created": proposals_created,
            "registrations_created": registrations_created,
            "conflict_mode": conflict_mode,
        },
    )

    has_failures = bool(contract_warnings or registration_warnings or dependency_warnings)
    if has_failures:
        response.status_code = 207

    return {
        "status": "partial_success" if has_failures else "success",
        "conflict_mode": conflict_mode,
        "assets": {
            "created": assets_created,
            "updated": assets_updated,
            "skipped": assets_skipped,
            "deleted": assets_deleted,
            "deleted_fqns": (deleted_assets_info[:20] if deleted_assets_info else []),
        },
        "dependencies": {
            "synced": dependencies_created,
        },
        "contracts": {
            "published": contracts_published,
        },
        "proposals": {
            "created": proposals_created,
            "details": proposals_info[:20] if proposals_info else [],
        },
        "registrations": {
            "created": registrations_created,
        },
        "guarantees_extracted": tests_extracted,
        "ownership_warnings": (ownership_warnings[:20] if ownership_warnings else []),
        "contract_warnings": (contract_warnings[:20] if contract_warnings else []),
        "registration_warnings": (registration_warnings[:20] if registration_warnings else []),
        "dependency_warnings": (dependency_warnings[:20] if dependency_warnings else []),
    }
