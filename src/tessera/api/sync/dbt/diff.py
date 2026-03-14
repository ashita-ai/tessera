"""dbt diff and impact analysis endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.rate_limit import limit_admin
from tessera.api.sync.dbt.mapper import dbt_columns_to_json_schema
from tessera.api.sync.dbt.models import (
    DbtDiffItem,
    DbtDiffRequest,
    DbtDiffResponse,
    DbtImpactResponse,
    DbtImpactResult,
    DbtManifestRequest,
)
from tessera.api.sync.dbt.parser import extract_tessera_meta
from tessera.api.sync.helpers import resolve_team_by_name
from tessera.db import AssetDB, ContractDB, RegistrationDB, get_session
from tessera.models.enums import ContractStatus, RegistrationStatus
from tessera.services.schema_diff import check_compatibility, diff_schemas

router = APIRouter()


async def _check_dbt_node_impact(
    node_id: str,
    node: dict[str, Any],
    session: AsyncSession,
) -> DbtImpactResult:
    """Check impact of a single dbt node against its registered contract.

    Works for both nodes (models/seeds/snapshots) and sources.
    """
    # Build FQN from dbt metadata
    database = node.get("database", "")
    schema_name = node.get("schema", "")
    name = node.get("name", "")
    fqn = f"{database}.{schema_name}.{name}".lower()

    # Look up existing asset and active contract
    asset_result = await session.execute(select(AssetDB).where(AssetDB.fqn == fqn))
    existing_asset = asset_result.scalar_one_or_none()

    if not existing_asset:
        return DbtImpactResult(
            fqn=fqn,
            node_id=node_id,
            has_contract=False,
            safe_to_publish=True,
            change_type=None,
            breaking_changes=[],
        )

    # Get active contract for this asset
    contract_result = await session.execute(
        select(ContractDB).where(
            ContractDB.asset_id == existing_asset.id,
            ContractDB.status == ContractStatus.ACTIVE,
        )
    )
    existing_contract = contract_result.scalar_one_or_none()

    if not existing_contract:
        return DbtImpactResult(
            fqn=fqn,
            node_id=node_id,
            has_contract=False,
            safe_to_publish=True,
            change_type=None,
            breaking_changes=[],
        )

    # Convert dbt columns to JSON Schema and compare
    columns = node.get("columns", {})
    proposed_schema = dbt_columns_to_json_schema(columns)
    existing_schema = existing_contract.schema_def

    # Use schema_diff to detect changes
    diff_result = diff_schemas(existing_schema, proposed_schema)
    is_compatible, breaking_changes_list = check_compatibility(
        existing_schema,
        proposed_schema,
        existing_contract.compatibility_mode,
    )

    return DbtImpactResult(
        fqn=fqn,
        node_id=node_id,
        has_contract=True,
        safe_to_publish=is_compatible,
        change_type=diff_result.change_type.value,
        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
    )


@router.post("/dbt/impact", response_model=DbtImpactResponse)
@limit_admin
async def check_dbt_impact(
    request: Request,
    compare_req: DbtManifestRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> DbtImpactResponse:
    """Check impact of dbt models against registered contracts.

    Accepts a dbt manifest.json in the request body and checks each model's
    schema against existing contracts. This is the primary CI/CD integration
    point - no file system access required.

    Returns impact analysis for each model, identifying breaking changes.
    """
    manifest = compare_req.manifest
    results: list[DbtImpactResult] = []

    # Process nodes (models, seeds, snapshots)
    nodes = manifest.get("nodes", {})
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        results.append(await _check_dbt_node_impact(node_id, node, session))

    # Process sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        results.append(await _check_dbt_node_impact(source_id, source, session))

    models_with_contracts = sum(1 for r in results if r.has_contract)
    breaking_changes_count = sum(1 for r in results if not r.safe_to_publish)

    return DbtImpactResponse(
        status="success" if breaking_changes_count == 0 else "breaking_changes_detected",
        total_models=len(results),
        models_with_contracts=models_with_contracts,
        breaking_changes_count=breaking_changes_count,
        results=results,
    )


@router.post("/dbt/diff", response_model=DbtDiffResponse)
@limit_admin
async def diff_dbt_manifest(
    request: Request,
    diff_req: DbtDiffRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> DbtDiffResponse:
    """Preview what would change if this manifest is applied (CI dry-run).

    This is the primary CI/CD integration point. Call this in your PR checks to:
    1. See what assets would be created/modified/deleted
    2. Detect breaking schema changes
    3. Validate meta.tessera configuration (team names exist, etc.)
    4. Fail the build if breaking changes aren't acknowledged

    Example CI usage:
    ```yaml
    - name: Check contract impact
      run: |
        dbt compile
        curl -X POST $TESSERA_URL/api/v1/sync/dbt/diff \\
          -H "Authorization: Bearer $TESSERA_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"manifest": '$(cat target/manifest.json)', "fail_on_breaking": true}'
    ```
    """
    manifest = diff_req.manifest
    models: list[DbtDiffItem] = []
    warnings: list[str] = []
    meta_errors: list[str] = []

    # Build FQN -> node_id mapping from manifest
    manifest_fqns: dict[str, tuple[str, dict[str, Any]]] = {}
    nodes = manifest.get("nodes", {})
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        manifest_fqns[fqn] = (node_id, node)

    # Also include sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        manifest_fqns[fqn] = (source_id, source)

    # Get all existing assets
    existing_result = await session.execute(select(AssetDB).where(AssetDB.deleted_at.is_(None)))
    existing_assets = {a.fqn: a for a in existing_result.scalars().all()}

    # Process each model in manifest
    for fqn, (node_id, node) in manifest_fqns.items():
        tessera_meta = extract_tessera_meta(node)
        columns = node.get("columns", {})
        has_schema = bool(columns)

        # Count consumers from refs (models that depend on this one)
        consumers_from_refs = sum(
            1
            for other_fqn, (_, other_node) in manifest_fqns.items()
            if other_fqn != fqn and node_id in other_node.get("depends_on", {}).get("nodes", [])
        )

        # Validate owner_team if specified
        owner_team_name = tessera_meta.owner_team
        if owner_team_name:
            team = await resolve_team_by_name(session, owner_team_name)
            if not team:
                meta_errors.append(f"{fqn}: owner_team '{owner_team_name}' not found")

        # Validate consumer teams
        consumers_declared = len(tessera_meta.consumers)
        for consumer in tessera_meta.consumers:
            consumer_team = consumer.get("team")
            if consumer_team:
                team = await resolve_team_by_name(session, consumer_team)
                if not team:
                    meta_errors.append(f"{fqn}: consumer team '{consumer_team}' not found")

        existing_asset = existing_assets.get(fqn)
        if not existing_asset:
            # New asset
            models.append(
                DbtDiffItem(
                    fqn=fqn,
                    node_id=node_id,
                    change_type="new",
                    owner_team=owner_team_name,
                    consumers_declared=consumers_declared,
                    consumers_from_refs=consumers_from_refs,
                    has_schema=has_schema,
                    schema_change_type=None,
                    breaking_changes=[],
                )
            )
        else:
            # Existing asset - check for schema changes
            contract_result = await session.execute(
                select(ContractDB)
                .where(ContractDB.asset_id == existing_asset.id)
                .where(ContractDB.status == ContractStatus.ACTIVE)
            )
            existing_contract = contract_result.scalar_one_or_none()

            if not existing_contract or not has_schema:
                # No contract or no schema to compare
                models.append(
                    DbtDiffItem(
                        fqn=fqn,
                        node_id=node_id,
                        change_type="unchanged" if not has_schema else "modified",
                        owner_team=owner_team_name,
                        consumers_declared=consumers_declared,
                        consumers_from_refs=consumers_from_refs,
                        has_schema=has_schema,
                        schema_change_type=None,
                        breaking_changes=[],
                    )
                )
            else:
                # Compare schemas
                proposed_schema = dbt_columns_to_json_schema(columns)
                existing_schema = existing_contract.schema_def

                diff_result = diff_schemas(existing_schema, proposed_schema)
                is_compatible, breaking_changes_list = check_compatibility(
                    existing_schema,
                    proposed_schema,
                    existing_contract.compatibility_mode,
                )

                if diff_result.change_type.value == "none":
                    schema_change_type = "none"
                    change_type = "unchanged"
                elif is_compatible:
                    schema_change_type = "compatible"
                    change_type = "modified"
                else:
                    schema_change_type = "breaking"
                    change_type = "modified"

                models.append(
                    DbtDiffItem(
                        fqn=fqn,
                        node_id=node_id,
                        change_type=change_type,
                        owner_team=owner_team_name,
                        consumers_declared=consumers_declared,
                        consumers_from_refs=consumers_from_refs,
                        has_schema=has_schema,
                        schema_change_type=schema_change_type,
                        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
                    )
                )

    # Check for deleted assets (in DB but not in manifest)
    for fqn, asset in existing_assets.items():
        if fqn not in manifest_fqns:
            # Check if it's a dbt-managed asset
            metadata = asset.metadata_ or {}
            node_id = metadata.get("dbt_node_id") or metadata.get("dbt_source_id")
            if node_id:
                # Count registrations (consumers) for this asset via its contracts
                reg_result = await session.execute(
                    select(func.count())
                    .select_from(RegistrationDB)
                    .join(ContractDB, RegistrationDB.contract_id == ContractDB.id)
                    .where(ContractDB.asset_id == asset.id)
                    .where(RegistrationDB.status == RegistrationStatus.ACTIVE)
                )
                consumers_count = reg_result.scalar() or 0

                models.append(
                    DbtDiffItem(
                        fqn=fqn,
                        node_id=node_id,
                        change_type="deleted",
                        owner_team=None,
                        consumers_declared=consumers_count,
                        consumers_from_refs=0,
                        has_schema=False,
                        schema_change_type=None,
                        breaking_changes=[],
                    )
                )
                if consumers_count > 0:
                    warnings.append(
                        f"{fqn}: Model removed but has {consumers_count} registered consumer(s)"
                    )

    # Calculate summary
    summary = {
        "new": sum(1 for m in models if m.change_type == "new"),
        "modified": sum(1 for m in models if m.change_type == "modified"),
        "deleted": sum(1 for m in models if m.change_type == "deleted"),
        "unchanged": sum(1 for m in models if m.change_type == "unchanged"),
        "breaking": sum(1 for m in models if m.schema_change_type == "breaking"),
    }

    # Determine status and blocking
    has_breaking = summary["breaking"] > 0
    has_meta_errors = len(meta_errors) > 0

    if has_breaking:
        status = "breaking_changes_detected"
    elif summary["new"] > 0 or summary["modified"] > 0:
        status = "changes_detected"
    else:
        status = "clean"

    blocking = (has_breaking and diff_req.fail_on_breaking) or has_meta_errors

    return DbtDiffResponse(
        status=status,
        summary=summary,
        blocking=blocking,
        models=models,
        warnings=warnings,
        meta_errors=meta_errors,
    )
