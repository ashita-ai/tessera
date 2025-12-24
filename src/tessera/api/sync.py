"""Git sync API endpoints.

Enables schema management via git by exporting/importing contracts to/from YAML files.
Designed to work with dbt manifest.json for auto-registering assets.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_admin
from tessera.config import settings
from tessera.db import AssetDB, ContractDB, ProposalDB, RegistrationDB, TeamDB, UserDB, get_session
from tessera.models.enums import CompatibilityMode, ContractStatus, RegistrationStatus
from tessera.services import validate_json_schema
from tessera.services.audit import log_proposal_created
from tessera.services.schema_diff import check_compatibility, diff_schemas

router = APIRouter()


class TesseraMetaConfig:
    """Parsed tessera configuration from dbt model meta."""

    def __init__(
        self,
        owner_team: str | None = None,
        owner_user: str | None = None,
        consumers: list[dict[str, Any]] | None = None,
        freshness: dict[str, Any] | None = None,
        volume: dict[str, Any] | None = None,
        compatibility_mode: str | None = None,
    ):
        self.owner_team = owner_team
        self.owner_user = owner_user
        self.consumers = consumers or []
        self.freshness = freshness
        self.volume = volume
        self.compatibility_mode = compatibility_mode


def extract_tessera_meta(node: dict[str, Any]) -> TesseraMetaConfig:
    """Extract tessera configuration from dbt model meta.

    Looks for meta.tessera in the node and parses ownership, consumers, and SLAs.

    Example dbt YAML:
    ```yaml
    models:
      - name: orders
        meta:
          tessera:
            owner_team: data-platform
            owner_user: alice@corp.com
            consumers:
              - team: marketing
                purpose: Campaign attribution
              - team: finance
            freshness:
              max_staleness_minutes: 60
            volume:
              min_rows: 1000
            compatibility_mode: backward
    ```
    """
    meta = node.get("meta", {})
    tessera_config = meta.get("tessera", {})

    if not tessera_config:
        return TesseraMetaConfig()

    return TesseraMetaConfig(
        owner_team=tessera_config.get("owner_team"),
        owner_user=tessera_config.get("owner_user"),
        consumers=tessera_config.get("consumers", []),
        freshness=tessera_config.get("freshness"),
        volume=tessera_config.get("volume"),
        compatibility_mode=tessera_config.get("compatibility_mode"),
    )


async def resolve_team_by_name(
    session: AsyncSession,
    team_name: str,
) -> TeamDB | None:
    """Look up a team by name (case-insensitive)."""
    result = await session.execute(
        select(TeamDB).where(TeamDB.name.ilike(team_name)).where(TeamDB.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def resolve_user_by_email(
    session: AsyncSession,
    email: str,
) -> UserDB | None:
    """Look up a user by email (case-insensitive)."""
    result = await session.execute(
        select(UserDB).where(UserDB.email.ilike(email)).where(UserDB.deactivated_at.is_(None))
    )
    return result.scalar_one_or_none()


def _require_git_sync_path() -> Path:
    """Require git_sync_path to be configured, raise 400 if not."""
    if settings.git_sync_path is None:
        raise BadRequestError(
            "GIT_SYNC_PATH not configured. Set the GIT_SYNC_PATH environment variable.",
            code=ErrorCode.BAD_REQUEST,
        )
    return settings.git_sync_path


def extract_guarantees_from_tests(
    node_id: str, node: dict[str, Any], all_nodes: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract guarantees from dbt tests attached to a model/source.

    Parses dbt test nodes and converts them to Tessera guarantees format:
    - not_null tests -> nullability: {column: "never"}
    - accepted_values tests -> accepted_values: {column: [values]}
    - unique tests -> custom: {type: "unique", column, config}
    - relationships tests -> custom: {type: "relationships", column, config}
    - dbt_expectations/dbt_utils tests -> custom: {type: test_name, column, config}
    - singular tests (SQL files) -> custom: {type: "singular", name, description, sql}

    Singular tests are SQL files in the tests/ directory that express custom
    business logic assertions (e.g., "market_value must equal shares * price").
    These become contract guarantees - removing them is a breaking change.

    Args:
        node_id: The dbt node ID (e.g., "model.project.users")
        node: The node data from manifest
        all_nodes: All nodes from the manifest to find related tests

    Returns:
        Guarantees dict if any tests found, None otherwise
    """
    nullability: dict[str, str] = {}
    accepted_values: dict[str, list[str]] = {}
    custom_tests: list[dict[str, Any]] = []

    # dbt tests reference their model via depends_on.nodes or attached via refs
    # Test nodes have patterns like: test.project.not_null_users_id
    # They contain test_metadata with test name and kwargs
    for test_id, test_node in all_nodes.items():
        if test_node.get("resource_type") != "test":
            continue

        # Check if test depends on this node
        depends_on = test_node.get("depends_on", {}).get("nodes", [])
        if node_id not in depends_on:
            continue

        # Extract test metadata
        test_metadata = test_node.get("test_metadata", {})
        test_name = test_metadata.get("name", "")
        kwargs = test_metadata.get("kwargs", {})

        # Get column name from kwargs or test config
        column_name = kwargs.get("column_name") or test_node.get("column_name")

        # Map standard dbt tests to guarantees
        if test_name == "not_null" and column_name:
            nullability[column_name] = "never"
        elif test_name == "accepted_values" and column_name:
            values = kwargs.get("values", [])
            if values:
                accepted_values[column_name] = values
        elif test_name in ("unique", "relationships"):
            # Store as custom test for reference
            custom_tests.append(
                {
                    "type": test_name,
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif test_name.startswith(("dbt_expectations.", "dbt_utils.")):
            # dbt-expectations and dbt-utils tests
            custom_tests.append(
                {
                    "type": test_name,
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif test_metadata.get("namespace"):
            # Other namespaced tests (custom packages)
            custom_tests.append(
                {
                    "type": f"{test_metadata['namespace']}.{test_name}",
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif not test_metadata:
            # Singular test (SQL file in tests/ directory) - no test_metadata
            # These express custom business logic assertions
            # e.g., "assert_market_value_consistency" checks market_value = shares * price
            test_name_from_id = test_id.split(".")[-1] if "." in test_id else test_id
            custom_tests.append(
                {
                    "type": "singular",
                    "name": test_name_from_id,
                    "description": test_node.get("description", ""),
                    # Store compiled SQL so consumers can see the assertion logic
                    "sql": test_node.get("compiled_code") or test_node.get("raw_code"),
                }
            )

    # Build guarantees dict only if we have something
    if not (nullability or accepted_values or custom_tests):
        return None

    guarantees: dict[str, Any] = {}
    if nullability:
        guarantees["nullability"] = nullability
    if accepted_values:
        guarantees["accepted_values"] = accepted_values
    if custom_tests:
        guarantees["custom"] = custom_tests

    return guarantees


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


class DbtManifestUploadRequest(BaseModel):
    """Request body for uploading a dbt manifest with conflict handling."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    owner_team_id: UUID | None = Field(
        None,
        description="Default team ID. Overridden by meta.tessera.owner_team.",
    )
    conflict_mode: str = Field(
        default="ignore",
        description="'overwrite', 'ignore', or 'fail' on conflict",
    )
    auto_publish_contracts: bool = Field(
        default=False,
        description="Automatically publish initial contracts for new assets with column schemas",
    )
    auto_create_proposals: bool = Field(
        default=False,
        description="Auto-create proposals for breaking schema changes on existing contracts",
    )
    auto_register_consumers: bool = Field(
        default=False,
        description="Register consumers from meta.tessera.consumers and refs",
    )
    infer_consumers_from_refs: bool = Field(
        default=True,
        description="Infer consumer relationships from dbt ref() dependencies (depends_on)",
    )


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


class DbtDiffItem(BaseModel):
    """A single change detected in dbt manifest."""

    fqn: str
    node_id: str
    change_type: str  # 'new', 'modified', 'deleted', 'unchanged'
    owner_team: str | None = None
    consumers_declared: int = 0
    consumers_from_refs: int = 0
    has_schema: bool = False
    schema_change_type: str | None = None  # 'none', 'compatible', 'breaking'
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class DbtDiffResponse(BaseModel):
    """Response from dbt manifest diff (CI preview)."""

    status: str  # 'clean', 'changes_detected', 'breaking_changes_detected'
    summary: dict[str, int]  # {'new': N, 'modified': M, 'deleted': D, 'breaking': B}
    blocking: bool  # True if CI should fail
    models: list[DbtDiffItem]
    warnings: list[str] = Field(default_factory=list)
    meta_errors: list[str] = Field(default_factory=list)  # Missing teams, etc.


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
    tests_extracted = 0
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

        # Extract guarantees from dbt tests
        guarantees = extract_guarantees_from_tests(node_id, node, nodes)
        if guarantees:
            tests_extracted += 1

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
        # Store extracted guarantees in metadata for use when publishing contracts
        if guarantees:
            metadata["guarantees"] = guarantees

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

        # Extract guarantees from tests for sources (they're in nodes too)
        guarantees = extract_guarantees_from_tests(source_id, source, nodes)
        if guarantees:
            tests_extracted += 1

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
        # Store extracted guarantees in metadata for use when publishing contracts
        if guarantees:
            metadata["guarantees"] = guarantees

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
        "guarantees_extracted": tests_extracted,
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


@router.post("/dbt/upload")
@limit_admin
async def upload_dbt_manifest(
    request: Request,
    upload_req: DbtManifestUploadRequest,
    auth: Auth,
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
        raise HTTPException(
            status_code=400,
            detail=f"Invalid conflict_mode: {conflict_mode}. Use 'overwrite', 'ignore', or 'fail'",
        )

    assets_created = 0
    assets_updated = 0
    assets_skipped = 0
    contracts_published = 0
    proposals_created = 0
    registrations_created = 0
    conflicts: list[str] = []
    ownership_warnings: list[str] = []
    contract_warnings: list[str] = []
    registration_warnings: list[str] = []
    proposals_info: list[dict[str, Any]] = []

    # Track existing assets with breaking changes for proposal creation
    assets_for_proposals: list[
        tuple[AssetDB, dict[str, Any], dict[str, Any] | None, ContractDB, UUID, UUID | None]
    ] = []  # (asset, columns, guarantees, existing_contract, team_id, user_id)

    # Track newly created assets for auto-publish
    new_assets_for_contracts: list[
        tuple[AssetDB, dict[str, Any], dict[str, Any] | None, str | None]
    ] = []

    # Track existing assets for auto-publish (compatible changes or no contract yet)
    existing_assets_for_contracts: list[
        tuple[AssetDB, dict[str, Any], dict[str, Any] | None, str | None, ContractDB | None]
    ] = []  # (asset, columns, guarantees, compat_mode, existing_contract or None)

    # Track consumer relationships for auto-registration
    # Maps FQN -> (asset, team_id, depends_on_node_ids, meta_consumers)
    asset_consumer_map: dict[str, tuple[AssetDB, UUID, list[str], list[dict[str, Any]]]] = {}

    # Build node_id -> FQN mapping for dependency resolution
    node_id_to_fqn: dict[str, str] = {}

    # Cache team/user lookups to avoid repeated queries
    team_cache: dict[str, TeamDB | None] = {}
    user_cache: dict[str, UserDB | None] = {}

    async def get_team_by_name(name: str) -> TeamDB | None:
        if name not in team_cache:
            team_cache[name] = await resolve_team_by_name(session, name)
        return team_cache[name]

    async def get_user_by_email(email: str) -> UserDB | None:
        if email not in user_cache:
            user_cache[email] = await resolve_user_by_email(session, email)
        return user_cache[email]

    # Process nodes (models, seeds, snapshots)
    nodes = manifest.get("nodes", {})
    all_nodes = nodes  # For test extraction
    tests_extracted = 0

    # First pass: build node_id -> FQN mapping
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        node_id_to_fqn[node_id] = fqn

    # Also build mapping for sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        node_id_to_fqn[source_id] = fqn

    # Second pass: process nodes
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

        if existing:
            if conflict_mode == "fail":
                conflicts.append(fqn)
                continue
            elif conflict_mode == "ignore":
                assets_skipped += 1
                continue
            # else overwrite - continue to update

        # Extract tessera meta for ownership
        tessera_meta = extract_tessera_meta(node)
        resolved_team_id = owner_team_id
        resolved_user_id: UUID | None = None

        # Resolve owner_team from meta.tessera.owner_team
        if tessera_meta.owner_team:
            team = await get_team_by_name(tessera_meta.owner_team)
            if team:
                resolved_team_id = team.id
            else:
                ownership_warnings.append(
                    f"{fqn}: owner_team '{tessera_meta.owner_team}' not found, using default"
                )

        # Resolve owner_user from meta.tessera.owner_user
        if tessera_meta.owner_user:
            user = await get_user_by_email(tessera_meta.owner_user)
            if user:
                resolved_user_id = user.id
            else:
                ownership_warnings.append(
                    f"{fqn}: owner_user '{tessera_meta.owner_user}' not found"
                )

        # Require at least a team ID
        if resolved_team_id is None:
            ownership_warnings.append(
                f"{fqn}: No owner_team_id provided and no meta.tessera.owner_team set, skipping"
            )
            assets_skipped += 1
            continue

        # Extract guarantees from dbt tests
        guarantees = extract_guarantees_from_tests(node_id, node, all_nodes)
        if guarantees:
            tests_extracted += 1

        # Merge guarantees from meta.tessera (freshness, volume)
        if tessera_meta.freshness or tessera_meta.volume:
            if guarantees is None:
                guarantees = {}
            if tessera_meta.freshness:
                guarantees["freshness"] = tessera_meta.freshness
            if tessera_meta.volume:
                guarantees["volume"] = tessera_meta.volume

        # Build metadata from dbt
        # Convert depends_on node IDs to FQNs for UI lookup
        depends_on_node_ids = node.get("depends_on", {}).get("nodes", [])
        depends_on_fqns = [
            node_id_to_fqn[dep_id] for dep_id in depends_on_node_ids if dep_id in node_id_to_fqn
        ]
        metadata = {
            "dbt_node_id": node_id,
            "resource_type": resource_type,
            "description": node.get("description", ""),
            "tags": node.get("tags", []),
            "dbt_fqn": node.get("fqn", []),
            "path": node.get("path", ""),
            "depends_on": depends_on_fqns,
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in node.get("columns", {}).items()
            },
        }
        if guarantees:
            metadata["guarantees"] = guarantees
        # Store tessera meta for reference
        if tessera_meta.consumers:
            metadata["tessera_consumers"] = tessera_meta.consumers

        columns = node.get("columns", {})
        if existing:
            existing.metadata_ = metadata
            existing.owner_team_id = resolved_team_id
            if resolved_user_id:
                existing.owner_user_id = resolved_user_id
            assets_updated += 1

            # Check for breaking changes if auto_create_proposals is enabled
            if upload_req.auto_create_proposals and columns:
                # Get active contract for this asset
                contract_result = await session.execute(
                    select(ContractDB)
                    .where(ContractDB.asset_id == existing.id)
                    .where(ContractDB.status == ContractStatus.ACTIVE)
                )
                active_contract = contract_result.scalar_one_or_none()
                if active_contract:
                    # Track for proposal creation (checked after all assets are processed)
                    assets_for_proposals.append(
                        (
                            existing,
                            columns,
                            guarantees,
                            active_contract,
                            resolved_team_id,
                            resolved_user_id,
                        )
                    )

            # Track existing assets for consumer registration too
            if upload_req.auto_register_consumers:
                asset_consumer_map[fqn] = (
                    existing,
                    resolved_team_id,
                    depends_on_node_ids if upload_req.infer_consumers_from_refs else [],
                    tessera_meta.consumers,
                )

            # Track existing assets for auto-publish (compatible changes or first contract)
            if upload_req.auto_publish_contracts and columns:
                # Get active contract for this asset
                contract_result = await session.execute(
                    select(ContractDB)
                    .where(ContractDB.asset_id == existing.id)
                    .where(ContractDB.status == ContractStatus.ACTIVE)
                )
                active_contract = contract_result.scalar_one_or_none()
                existing_assets_for_contracts.append(
                    (
                        existing,
                        columns,
                        guarantees,
                        tessera_meta.compatibility_mode,
                        active_contract,
                    )  # noqa: E501
                )
        else:
            new_asset = AssetDB(
                fqn=fqn,
                owner_team_id=resolved_team_id,
                owner_user_id=resolved_user_id,
                metadata_=metadata,
            )
            session.add(new_asset)
            assets_created += 1

            # Track for auto-publish if it has columns
            if upload_req.auto_publish_contracts and columns:
                new_assets_for_contracts.append(
                    (new_asset, columns, guarantees, tessera_meta.compatibility_mode)
                )

            # Track for consumer registration
            if upload_req.auto_register_consumers:
                asset_consumer_map[fqn] = (
                    new_asset,
                    resolved_team_id,
                    depends_on_node_ids if upload_req.infer_consumers_from_refs else [],
                    tessera_meta.consumers,
                )

    # Process sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()

        result = await session.execute(select(AssetDB).where(AssetDB.fqn == fqn))
        existing = result.scalar_one_or_none()

        if existing:
            if conflict_mode == "fail":
                conflicts.append(fqn)
                continue
            elif conflict_mode == "ignore":
                assets_skipped += 1
                continue

        # Extract tessera meta for ownership (sources support meta too)
        tessera_meta = extract_tessera_meta(source)
        resolved_team_id = owner_team_id
        resolved_user_id = None

        if tessera_meta.owner_team:
            team = await get_team_by_name(tessera_meta.owner_team)
            if team:
                resolved_team_id = team.id
            else:
                ownership_warnings.append(
                    f"{fqn}: owner_team '{tessera_meta.owner_team}' not found, using default"
                )

        if tessera_meta.owner_user:
            user = await get_user_by_email(tessera_meta.owner_user)
            if user:
                resolved_user_id = user.id
            else:
                ownership_warnings.append(
                    f"{fqn}: owner_user '{tessera_meta.owner_user}' not found"
                )

        if resolved_team_id is None:
            ownership_warnings.append(
                f"{fqn}: No owner_team_id provided and no meta.tessera.owner_team set, skipping"
            )
            assets_skipped += 1
            continue

        guarantees = extract_guarantees_from_tests(source_id, source, all_nodes)
        if guarantees:
            tests_extracted += 1

        # Merge guarantees from meta.tessera
        if tessera_meta.freshness or tessera_meta.volume:
            if guarantees is None:
                guarantees = {}
            if tessera_meta.freshness:
                guarantees["freshness"] = tessera_meta.freshness
            if tessera_meta.volume:
                guarantees["volume"] = tessera_meta.volume

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
        if guarantees:
            metadata["guarantees"] = guarantees
        if tessera_meta.consumers:
            metadata["tessera_consumers"] = tessera_meta.consumers

        columns = source.get("columns", {})
        if existing:
            existing.metadata_ = metadata
            existing.owner_team_id = resolved_team_id
            if resolved_user_id:
                existing.owner_user_id = resolved_user_id
            assets_updated += 1

            # Check for breaking changes if auto_create_proposals is enabled
            if upload_req.auto_create_proposals and columns:
                # Get active contract for this asset
                contract_result = await session.execute(
                    select(ContractDB)
                    .where(ContractDB.asset_id == existing.id)
                    .where(ContractDB.status == ContractStatus.ACTIVE)
                )
                active_contract = contract_result.scalar_one_or_none()
                if active_contract:
                    # Track for proposal creation
                    assets_for_proposals.append(
                        (
                            existing,
                            columns,
                            guarantees,
                            active_contract,
                            resolved_team_id,
                            resolved_user_id,
                        )
                    )

            # Track existing sources for consumer registration
            if upload_req.auto_register_consumers:
                asset_consumer_map[fqn] = (
                    existing,
                    resolved_team_id,
                    [],  # Sources don't have depends_on
                    tessera_meta.consumers,
                )

            # Track existing sources for auto-publish (compatible changes or first contract)
            if upload_req.auto_publish_contracts and columns:
                # Get active contract for this source
                contract_result = await session.execute(
                    select(ContractDB)
                    .where(ContractDB.asset_id == existing.id)
                    .where(ContractDB.status == ContractStatus.ACTIVE)
                )
                active_contract = contract_result.scalar_one_or_none()
                existing_assets_for_contracts.append(
                    (
                        existing,
                        columns,
                        guarantees,
                        tessera_meta.compatibility_mode,
                        active_contract,
                    )  # noqa: E501
                )
        else:
            new_asset = AssetDB(
                fqn=fqn,
                owner_team_id=resolved_team_id,
                owner_user_id=resolved_user_id,
                metadata_=metadata,
            )
            session.add(new_asset)
            assets_created += 1

            # Track for auto-publish if it has columns
            if upload_req.auto_publish_contracts and columns:
                new_assets_for_contracts.append(
                    (new_asset, columns, guarantees, tessera_meta.compatibility_mode)
                )

    # If fail mode and conflicts found, raise error
    if conflict_mode == "fail" and conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Found {len(conflicts)} existing assets",
                "conflicts": conflicts[:20],  # Limit to first 20
            },
        )

    # Auto-publish contracts for new assets with column schemas
    if upload_req.auto_publish_contracts and new_assets_for_contracts:
        # Flush to get asset IDs
        await session.flush()

        for asset, columns, asset_guarantees, compat_mode_str in new_assets_for_contracts:
            try:
                # Convert columns to JSON Schema
                schema_def = dbt_columns_to_json_schema(columns)

                # Validate schema
                is_valid, errors = validate_json_schema(schema_def)
                if not is_valid:
                    contract_warnings.append(
                        f"{asset.fqn}: Invalid schema generated from columns: {errors}"
                    )
                    continue

                # Determine compatibility mode
                if compat_mode_str:
                    try:
                        compat_mode = CompatibilityMode(compat_mode_str.lower())
                    except ValueError:
                        compat_mode = CompatibilityMode.BACKWARD
                        msg = f"{asset.fqn}: Unknown compatibility_mode, defaulting to backward"
                        contract_warnings.append(msg)
                else:
                    compat_mode = CompatibilityMode.BACKWARD

                # Create contract
                new_contract = ContractDB(
                    asset_id=asset.id,
                    version="1.0.0",
                    schema_def=schema_def,
                    compatibility_mode=compat_mode,
                    guarantees=asset_guarantees,
                    status=ContractStatus.ACTIVE,
                    published_by=asset.owner_team_id,
                    published_by_user_id=asset.owner_user_id,
                )
                session.add(new_contract)
                contracts_published += 1

            except Exception as e:
                contract_warnings.append(
                    f"{asset.fqn}: Failed to publish contract ({type(e).__name__}): {str(e)}"
                )

    # Auto-publish contracts for existing assets (first contract or compatible changes)
    if upload_req.auto_publish_contracts and existing_assets_for_contracts:
        for item in existing_assets_for_contracts:
            asset, columns, asset_guarantees, compat_mode_str, existing_contract = item
            try:
                # Convert columns to JSON Schema
                schema_def = dbt_columns_to_json_schema(columns)

                # Validate schema
                is_valid, errors = validate_json_schema(schema_def)
                if not is_valid:
                    contract_warnings.append(
                        f"{asset.fqn}: Invalid schema generated from columns: {errors}"
                    )
                    continue

                # Determine compatibility mode
                if compat_mode_str:
                    try:
                        compat_mode = CompatibilityMode(compat_mode_str.lower())
                    except ValueError:
                        compat_mode = CompatibilityMode.BACKWARD
                else:
                    if existing_contract:
                        compat_mode = existing_contract.compatibility_mode
                    else:
                        compat_mode = CompatibilityMode.BACKWARD

                if existing_contract is None:
                    # No existing contract - publish v1.0.0
                    new_contract = ContractDB(
                        asset_id=asset.id,
                        version="1.0.0",
                        schema_def=schema_def,
                        compatibility_mode=compat_mode,
                        guarantees=asset_guarantees,
                        status=ContractStatus.ACTIVE,
                        published_by=asset.owner_team_id,
                        published_by_user_id=asset.owner_user_id,
                    )
                    session.add(new_contract)
                    contracts_published += 1
                else:
                    # Check compatibility with existing contract
                    is_compatible, breaking_changes_list = check_compatibility(
                        existing_contract.schema_def,
                        schema_def,
                        existing_contract.compatibility_mode,
                    )

                    if is_compatible:
                        # Compatible change - bump minor version and publish
                        current_version = existing_contract.version
                        parts = current_version.split(".")
                        if len(parts) == 3:
                            new_version = f"{parts[0]}.{int(parts[1]) + 1}.0"
                        else:
                            new_version = "1.1.0"

                        # Deprecate old contract
                        existing_contract.status = ContractStatus.DEPRECATED

                        # Create new contract
                        new_contract = ContractDB(
                            asset_id=asset.id,
                            version=new_version,
                            schema_def=schema_def,
                            compatibility_mode=compat_mode,
                            guarantees=asset_guarantees,
                            status=ContractStatus.ACTIVE,
                            published_by=asset.owner_team_id,
                            published_by_user_id=asset.owner_user_id,
                        )
                        session.add(new_contract)
                        contracts_published += 1
                    # else: breaking change - skip, handled by auto_create_proposals

            except Exception as e:
                contract_warnings.append(
                    f"{asset.fqn}: Failed to publish contract ({type(e).__name__}): {str(e)}"
                )

    # Auto-register consumers from refs and meta.tessera.consumers
    if upload_req.auto_register_consumers and asset_consumer_map:
        # Build FQN -> asset lookup for the entire manifest
        fqn_to_asset: dict[str, AssetDB] = {}

        # Get all assets by FQN that we know about
        all_fqns = list(node_id_to_fqn.values())
        if all_fqns:
            existing_assets_result = await session.execute(
                select(AssetDB).where(AssetDB.fqn.in_(all_fqns))
            )
            for asset in existing_assets_result.scalars().all():
                fqn_to_asset[asset.fqn] = asset

        # Also include newly created assets that may not be flushed yet
        for fqn, (asset, team_id, depends_on, meta_consumers) in asset_consumer_map.items():
            fqn_to_asset[fqn] = asset

        # Process each model's consumer relationships
        for consumer_fqn, (
            consumer_asset,
            consumer_team_id,
            depends_on_node_ids,
            meta_consumers,
        ) in asset_consumer_map.items():
            # From refs (depends_on)
            if upload_req.infer_consumers_from_refs:
                for dep_node_id in depends_on_node_ids:
                    upstream_fqn = node_id_to_fqn.get(dep_node_id)
                    if not upstream_fqn:
                        continue

                    upstream_asset = fqn_to_asset.get(upstream_fqn)
                    if not upstream_asset:
                        continue

                    # Get active contract for upstream asset
                    contract_result = await session.execute(
                        select(ContractDB)
                        .where(ContractDB.asset_id == upstream_asset.id)
                        .where(ContractDB.status == ContractStatus.ACTIVE)
                    )
                    contract = contract_result.scalar_one_or_none()
                    if not contract:
                        continue

                    # Check if registration already exists
                    existing_reg_result = await session.execute(
                        select(RegistrationDB)
                        .where(RegistrationDB.contract_id == contract.id)
                        .where(RegistrationDB.consumer_team_id == consumer_team_id)
                    )
                    if existing_reg_result.scalar_one_or_none():
                        continue

                    # Create registration
                    new_reg = RegistrationDB(
                        contract_id=contract.id,
                        consumer_team_id=consumer_team_id,
                        status=RegistrationStatus.ACTIVE,
                    )
                    session.add(new_reg)
                    registrations_created += 1

            # From meta.tessera.consumers
            for consumer_entry in meta_consumers:
                consumer_team_name = consumer_entry.get("team")
                if not consumer_team_name:
                    continue

                team = await get_team_by_name(consumer_team_name)
                if not team:
                    registration_warnings.append(
                        f"{consumer_fqn}: consumer team '{consumer_team_name}' not found"
                    )
                    continue

                # Get active contract for this asset
                contract_result = await session.execute(
                    select(ContractDB)
                    .where(ContractDB.asset_id == consumer_asset.id)
                    .where(ContractDB.status == ContractStatus.ACTIVE)
                )
                contract = contract_result.scalar_one_or_none()
                if not contract:
                    msg = f"{consumer_fqn}: no active contract for '{consumer_team_name}'"
                    registration_warnings.append(msg)
                    continue

                # Check if registration already exists
                existing_reg_result = await session.execute(
                    select(RegistrationDB)
                    .where(RegistrationDB.contract_id == contract.id)
                    .where(RegistrationDB.consumer_team_id == team.id)
                )
                if existing_reg_result.scalar_one_or_none():
                    continue

                # Create registration
                new_reg = RegistrationDB(
                    contract_id=contract.id,
                    consumer_team_id=team.id,
                    status=RegistrationStatus.ACTIVE,
                )
                session.add(new_reg)
                registrations_created += 1

    # Auto-create proposals for breaking schema changes
    if upload_req.auto_create_proposals and assets_for_proposals:
        # Flush to ensure asset IDs are available
        await session.flush()

        for (
            asset,
            columns,
            asset_guarantees,
            existing_contract,
            team_id,
            user_id,
        ) in assets_for_proposals:
            # Convert columns to proposed schema
            proposed_schema = dbt_columns_to_json_schema(columns)
            existing_schema = existing_contract.schema_def

            # Check compatibility
            diff_result = diff_schemas(existing_schema, proposed_schema)
            is_compatible, breaking_changes_list = check_compatibility(
                existing_schema,
                proposed_schema,
                existing_contract.compatibility_mode,
            )

            # Only create proposal if there are breaking changes
            if not is_compatible and breaking_changes_list:
                db_proposal = ProposalDB(
                    asset_id=asset.id,
                    proposed_schema=proposed_schema,
                    proposed_guarantees=asset_guarantees,
                    change_type=diff_result.change_type,
                    breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
                    proposed_by=team_id,
                    proposed_by_user_id=user_id,
                )
                session.add(db_proposal)
                await session.flush()  # Get proposal ID

                # Log audit event
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

    return {
        "status": "success",
        "conflict_mode": conflict_mode,
        "assets": {
            "created": assets_created,
            "updated": assets_updated,
            "skipped": assets_skipped,
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
        "ownership_warnings": ownership_warnings[:20] if ownership_warnings else [],
        "contract_warnings": contract_warnings[:20] if contract_warnings else [],
        "registration_warnings": registration_warnings[:20] if registration_warnings else [],
    }


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


class DbtDiffRequest(BaseModel):
    """Request body for dbt manifest diff (CI preview)."""

    manifest: dict[str, Any] = Field(..., description="Full dbt manifest.json contents")
    fail_on_breaking: bool = Field(
        default=True,
        description="Return blocking=true if any breaking changes are detected",
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
            if metadata.get("dbt_node_id") or metadata.get("dbt_source_id"):
                warnings.append(f"{fqn}: Asset in Tessera but missing from manifest (deleted?)")

    # Calculate summary
    summary = {
        "new": sum(1 for m in models if m.change_type == "new"),
        "modified": sum(1 for m in models if m.change_type == "modified"),
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
