"""Git sync API endpoints.

Enables schema management via git by exporting/importing contracts to/from YAML files.
Designed to work with dbt manifest.json for auto-registering assets.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_admin
from tessera.config import settings
from tessera.db import AssetDB, ContractDB, RegistrationDB, TeamDB, get_session
from tessera.models.enums import CompatibilityMode, ContractStatus, RegistrationStatus
from tessera.services.schema_diff import check_compatibility, diff_schemas

router = APIRouter()


def _require_git_sync_path() -> Path:
    """Require git_sync_path to be configured, raise 400 if not."""
    if settings.git_sync_path is None:
        raise BadRequestError(
            "GIT_SYNC_PATH not configured. Set the GIT_SYNC_PATH environment variable.",
            code=ErrorCode.BAD_REQUEST,
        )
    return settings.git_sync_path


def dbt_columns_to_json_schema(columns: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt column definitions to JSON Schema.

    Maps dbt data types to JSON Schema types for compatibility checking.
    """
    type_mapping = {
        # String types
        "string": "string",
        "text": "string",
        "varchar": "string",
        "char": "string",
        "character varying": "string",
        # Numeric types
        "integer": "integer",
        "int": "integer",
        "bigint": "integer",
        "smallint": "integer",
        "int64": "integer",
        "int32": "integer",
        "number": "number",
        "numeric": "number",
        "decimal": "number",
        "float": "number",
        "double": "number",
        "real": "number",
        "float64": "number",
        # Boolean
        "boolean": "boolean",
        "bool": "boolean",
        # Date/time (represented as strings in JSON)
        "date": "string",
        "datetime": "string",
        "timestamp": "string",
        "timestamp_ntz": "string",
        "timestamp_tz": "string",
        "time": "string",
        # Other
        "json": "object",
        "jsonb": "object",
        "array": "array",
        "variant": "object",
        "object": "object",
    }

    properties: dict[str, Any] = {}
    required: list[str] = []

    for col_name, col_info in columns.items():
        data_type = (col_info.get("data_type") or "string").lower()
        # Extract base type (e.g., "varchar(255)" -> "varchar")
        base_type = data_type.split("(")[0].strip()

        json_type = type_mapping.get(base_type, "string")
        prop: dict[str, Any] = {"type": json_type}

        # Add description if present
        if col_info.get("description"):
            prop["description"] = col_info["description"]

        properties[col_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class DbtManifestRequest(BaseModel):
    """Request body for dbt manifest impact check."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    owner_team_id: UUID = Field(..., description="Team ID to use for new assets")


class DbtImpactResult(BaseModel):
    """Impact analysis result for a single dbt model."""

    fqn: str
    node_id: str
    has_contract: bool
    safe_to_publish: bool
    change_type: str | None = None
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class DbtImpactResponse(BaseModel):
    """Response from dbt manifest impact analysis."""

    status: str
    total_models: int
    models_with_contracts: int
    breaking_changes_count: int
    results: list[DbtImpactResult]


@router.post("/push")
@limit_admin
async def sync_push(
    request: Request,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Export database state to git-friendly YAML files.

    Creates a directory structure:
    {git_sync_path}/
    ├── teams/
    │   └── {team_name}.yaml
    └── assets/
        └── {fqn_escaped}.yaml  (includes contracts and registrations)

    Requires GIT_SYNC_PATH environment variable to be set.
    """
    sync_path = _require_git_sync_path()
    sync_path.mkdir(parents=True, exist_ok=True)

    teams_path = sync_path / "teams"
    teams_path.mkdir(exist_ok=True)

    assets_path = sync_path / "assets"
    assets_path.mkdir(exist_ok=True)

    # Export teams
    teams_result = await session.execute(select(TeamDB))
    teams = teams_result.scalars().all()
    teams_exported = 0

    for team in teams:
        team_file = teams_path / f"{team.name}.yaml"
        team_data = {
            "id": str(team.id),
            "name": team.name,
            "metadata": team.metadata_,
        }
        team_file.write_text(yaml.dump(team_data, default_flow_style=False, sort_keys=False))
        teams_exported += 1

    # Export assets with their contracts and registrations
    assets_result = await session.execute(select(AssetDB))
    assets = assets_result.scalars().all()
    assets_exported = 0
    contracts_exported = 0

    for asset in assets:
        # Escape FQN for filename (replace dots and slashes)
        fqn_escaped = asset.fqn.replace("/", "__").replace(".", "_")
        asset_file = assets_path / f"{fqn_escaped}.yaml"

        # Get contracts for this asset
        contracts_result = await session.execute(
            select(ContractDB).where(ContractDB.asset_id == asset.id)
        )
        contracts = contracts_result.scalars().all()

        # Get registrations for each contract
        contracts_data = []
        for contract in contracts:
            regs_result = await session.execute(
                select(RegistrationDB).where(RegistrationDB.contract_id == contract.id)
            )
            registrations = regs_result.scalars().all()

            contract_data = {
                "id": str(contract.id),
                "version": contract.version,
                "schema": contract.schema_def,
                "compatibility_mode": str(contract.compatibility_mode),
                "guarantees": contract.guarantees,
                "status": str(contract.status),
                "registrations": [
                    {
                        "id": str(reg.id),
                        "consumer_team_id": str(reg.consumer_team_id),
                        "pinned_version": reg.pinned_version,
                        "status": str(reg.status),
                    }
                    for reg in registrations
                ],
            }
            contracts_data.append(contract_data)
            contracts_exported += 1

        asset_data = {
            "id": str(asset.id),
            "fqn": asset.fqn,
            "owner_team_id": str(asset.owner_team_id),
            "metadata": asset.metadata_,
            "contracts": contracts_data,
        }
        asset_file.write_text(yaml.dump(asset_data, default_flow_style=False, sort_keys=False))
        assets_exported += 1

    return {
        "status": "success",
        "path": str(sync_path),
        "exported": {
            "teams": teams_exported,
            "assets": assets_exported,
            "contracts": contracts_exported,
        },
    }


@router.post("/pull")
@limit_admin
async def sync_pull(
    request: Request,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Import contracts from git-friendly YAML files into the database.

    Reads the directory structure created by /sync/push and upserts into the database.
    Requires GIT_SYNC_PATH environment variable to be set.
    """
    sync_path = _require_git_sync_path()
    if not sync_path.exists():
        raise NotFoundError(
            ErrorCode.SYNC_PATH_NOT_FOUND,
            f"Sync path not found: {sync_path}",
        )

    teams_imported = 0
    assets_imported = 0
    contracts_imported = 0

    # Import teams
    teams_path = sync_path / "teams"
    if teams_path.exists():
        for team_file in teams_path.glob("*.yaml"):
            team_data = yaml.safe_load(team_file.read_text())
            team_id = UUID(team_data["id"])

            result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = team_data["name"]
                existing.metadata_ = team_data.get("metadata", {})
            else:
                new_team = TeamDB(
                    id=team_id,
                    name=team_data["name"],
                    metadata_=team_data.get("metadata", {}),
                )
                session.add(new_team)
            teams_imported += 1

    # Import assets with contracts and registrations
    assets_path = sync_path / "assets"
    if assets_path.exists():
        for asset_file in assets_path.glob("*.yaml"):
            asset_data = yaml.safe_load(asset_file.read_text())
            asset_id = UUID(asset_data["id"])

            asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
            existing_asset = asset_result.scalar_one_or_none()

            if existing_asset:
                existing_asset.fqn = asset_data["fqn"]
                existing_asset.owner_team_id = UUID(asset_data["owner_team_id"])
                existing_asset.metadata_ = asset_data.get("metadata", {})
            else:
                new_asset = AssetDB(
                    id=asset_id,
                    fqn=asset_data["fqn"],
                    owner_team_id=UUID(asset_data["owner_team_id"]),
                    metadata_=asset_data.get("metadata", {}),
                )
                session.add(new_asset)
            assets_imported += 1

            # Import contracts
            for contract_data in asset_data.get("contracts", []):
                contract_id = UUID(contract_data["id"])

                contract_result = await session.execute(
                    select(ContractDB).where(ContractDB.id == contract_id)
                )
                existing_contract = contract_result.scalar_one_or_none()

                # Parse enums from strings
                compat_mode = CompatibilityMode(contract_data["compatibility_mode"])
                contract_status = ContractStatus(contract_data["status"])

                if existing_contract:
                    existing_contract.version = contract_data["version"]
                    existing_contract.schema_def = contract_data["schema"]
                    existing_contract.compatibility_mode = compat_mode
                    existing_contract.guarantees = contract_data.get("guarantees")
                    existing_contract.status = contract_status
                else:
                    new_contract = ContractDB(
                        id=contract_id,
                        asset_id=asset_id,
                        version=contract_data["version"],
                        schema_def=contract_data["schema"],
                        compatibility_mode=compat_mode,
                        guarantees=contract_data.get("guarantees"),
                        status=contract_status,
                        published_by=UUID(asset_data["owner_team_id"]),
                    )
                    session.add(new_contract)
                contracts_imported += 1

                # Import registrations
                for reg_data in contract_data.get("registrations", []):
                    reg_id = UUID(reg_data["id"])
                    reg_status = RegistrationStatus(reg_data["status"])

                    reg_result = await session.execute(
                        select(RegistrationDB).where(RegistrationDB.id == reg_id)
                    )
                    existing_reg = reg_result.scalar_one_or_none()

                    if existing_reg:
                        existing_reg.pinned_version = reg_data.get("pinned_version")
                        existing_reg.status = reg_status
                    else:
                        new_reg = RegistrationDB(
                            id=reg_id,
                            contract_id=contract_id,
                            consumer_team_id=UUID(reg_data["consumer_team_id"]),
                            pinned_version=reg_data.get("pinned_version"),
                            status=reg_status,
                        )
                        session.add(new_reg)

    return {
        "status": "success",
        "path": str(sync_path),
        "imported": {
            "teams": teams_imported,
            "assets": assets_imported,
            "contracts": contracts_imported,
        },
    }


@router.post("/dbt")
@limit_admin
async def sync_from_dbt(
    request: Request,
    auth: Auth,
    manifest_path: str = Query(..., description="Path to dbt manifest.json"),
    owner_team_id: UUID = Query(..., description="Team ID to assign as owner"),
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Import assets from a dbt manifest.json file.

    Parses the dbt manifest and creates assets for each model/source.
    This is the primary integration point for dbt projects.
    """
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise NotFoundError(
            ErrorCode.MANIFEST_NOT_FOUND,
            f"Manifest not found: {manifest_path}",
        )

    import json

    manifest = json.loads(manifest_file.read_text())

    assets_created = 0
    assets_updated = 0

    # Process nodes (models, seeds, snapshots)
    nodes = manifest.get("nodes", {})
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue

        # Build FQN from dbt metadata
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()

        # Check if asset exists
        result = await session.execute(select(AssetDB).where(AssetDB.fqn == fqn))
        existing = result.scalar_one_or_none()

        # Build metadata from dbt
        metadata = {
            "dbt_node_id": node_id,
            "resource_type": resource_type,
            "description": node.get("description", ""),
            "tags": node.get("tags", []),
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in node.get("columns", {}).items()
            },
        }

        if existing:
            existing.metadata_ = metadata
            assets_updated += 1
        else:
            new_asset = AssetDB(
                fqn=fqn,
                owner_team_id=owner_team_id,
                metadata_=metadata,
            )
            session.add(new_asset)
            assets_created += 1

    # Process sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()

        result = await session.execute(select(AssetDB).where(AssetDB.fqn == fqn))
        existing = result.scalar_one_or_none()

        metadata = {
            "dbt_source_id": source_id,
            "resource_type": "source",
            "description": source.get("description", ""),
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in source.get("columns", {}).items()
            },
        }

        if existing:
            existing.metadata_ = metadata
            assets_updated += 1
        else:
            new_asset = AssetDB(
                fqn=fqn,
                owner_team_id=owner_team_id,
                metadata_=metadata,
            )
            session.add(new_asset)
            assets_created += 1

    return {
        "status": "success",
        "manifest": str(manifest_path),
        "assets": {
            "created": assets_created,
            "updated": assets_updated,
        },
    }


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
