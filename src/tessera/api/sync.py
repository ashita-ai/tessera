"""Sync API endpoints.

Endpoints for synchronizing schemas from external sources:
- dbt manifest.json for auto-registering assets and contracts
- OpenAPI specifications for API endpoint contracts
- GraphQL introspection for GraphQL schema contracts
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_admin
from tessera.db import AssetDB, ContractDB, ProposalDB, RegistrationDB, TeamDB, UserDB, get_session
from tessera.models.enums import CompatibilityMode, ContractStatus, RegistrationStatus, ResourceType
from tessera.services import validate_json_schema
from tessera.services.audit import log_contract_published, log_proposal_created
from tessera.services.graphql import operations_to_assets as graphql_operations_to_assets
from tessera.services.graphql import parse_graphql_introspection
from tessera.services.openapi import endpoints_to_assets, parse_openapi
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


# =============================================================================
# OpenAPI Import
# =============================================================================


class OpenAPIImportRequest(BaseModel):
    """Request body for OpenAPI spec import."""

    spec: dict[str, Any] = Field(..., description="OpenAPI 3.x specification as JSON")
    owner_team_id: UUID = Field(..., description="Team that will own the imported assets")
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment for assets"
    )
    auto_publish_contracts: bool = Field(
        default=True, description="Automatically publish contracts for new assets"
    )
    dry_run: bool = Field(default=False, description="Preview changes without creating assets")


class OpenAPIEndpointResult(BaseModel):
    """Result for a single endpoint import."""

    fqn: str
    path: str
    method: str
    action: str  # "created", "updated", "skipped", "error"
    asset_id: str | None = None
    contract_id: str | None = None
    error: str | None = None


class OpenAPIImportResponse(BaseModel):
    """Response from OpenAPI spec import."""

    api_title: str
    api_version: str
    endpoints_found: int
    assets_created: int
    assets_updated: int
    assets_skipped: int
    contracts_published: int
    endpoints: list[OpenAPIEndpointResult]
    parse_errors: list[str]


@router.post("/openapi", response_model=OpenAPIImportResponse)
@limit_admin
async def import_openapi(
    request: Request,
    import_req: OpenAPIImportRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> OpenAPIImportResponse:
    """Import assets and contracts from an OpenAPI specification.

    Parses an OpenAPI 3.x spec and creates assets for each endpoint.
    Each endpoint becomes an asset with resource_type=api_endpoint.
    The request/response schemas are combined into a contract.

    Requires admin scope.

    Behavior:
    - New endpoints: Create asset and optionally publish contract
    - Existing endpoints: Update metadata, check for schema changes
    - dry_run=True: Preview changes without persisting

    Returns a summary of what was created/updated.
    """
    # Validate owner team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == import_req.owner_team_id))
    owner_team = team_result.scalar_one_or_none()
    if not owner_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

    # Parse the OpenAPI spec
    parse_result = parse_openapi(import_req.spec)

    if not parse_result.endpoints and parse_result.errors:
        raise BadRequestError(
            "Failed to parse OpenAPI spec",
            code=ErrorCode.INVALID_OPENAPI_SPEC,
            details={"errors": parse_result.errors},
        )

    # Convert endpoints to asset definitions
    asset_defs = endpoints_to_assets(parse_result, import_req.owner_team_id, import_req.environment)

    # Track results
    endpoints_results: list[OpenAPIEndpointResult] = []
    assets_created = 0
    assets_updated = 0
    assets_skipped = 0
    contracts_published = 0

    for i, asset_def in enumerate(asset_defs):
        endpoint = parse_result.endpoints[i]

        try:
            # Check if asset already exists
            existing_result = await session.execute(
                select(AssetDB)
                .where(AssetDB.fqn == asset_def.fqn)
                .where(AssetDB.environment == import_req.environment)
                .where(AssetDB.deleted_at.is_(None))
            )
            existing_asset = existing_result.scalar_one_or_none()

            if import_req.dry_run:
                # Dry run - just report what would happen
                if existing_asset:
                    endpoints_results.append(
                        OpenAPIEndpointResult(
                            fqn=asset_def.fqn,
                            path=endpoint.path,
                            method=endpoint.method,
                            action="would_update",
                            asset_id=str(existing_asset.id),
                        )
                    )
                    assets_updated += 1
                else:
                    endpoints_results.append(
                        OpenAPIEndpointResult(
                            fqn=asset_def.fqn,
                            path=endpoint.path,
                            method=endpoint.method,
                            action="would_create",
                        )
                    )
                    assets_created += 1
                    if import_req.auto_publish_contracts:
                        contracts_published += 1
                continue

            if existing_asset:
                # Update existing asset metadata
                existing_asset.metadata_ = {
                    **existing_asset.metadata_,
                    **asset_def.metadata,
                }
                existing_asset.resource_type = ResourceType.API_ENDPOINT
                await session.flush()

                endpoints_results.append(
                    OpenAPIEndpointResult(
                        fqn=asset_def.fqn,
                        path=endpoint.path,
                        method=endpoint.method,
                        action="updated",
                        asset_id=str(existing_asset.id),
                    )
                )
                assets_updated += 1
            else:
                # Create new asset
                new_asset = AssetDB(
                    fqn=asset_def.fqn,
                    owner_team_id=import_req.owner_team_id,
                    environment=import_req.environment,
                    resource_type=ResourceType.API_ENDPOINT,
                    metadata_=asset_def.metadata,
                )
                session.add(new_asset)
                await session.flush()
                await session.refresh(new_asset)

                contract_id: str | None = None

                # Auto-publish contract if enabled
                if import_req.auto_publish_contracts:
                    new_contract = ContractDB(
                        asset_id=new_asset.id,
                        version="1.0.0",
                        schema_def=asset_def.schema_def,
                        compatibility_mode=CompatibilityMode.BACKWARD,
                        published_by=import_req.owner_team_id,
                    )
                    session.add(new_contract)
                    await session.flush()
                    await session.refresh(new_contract)

                    await log_contract_published(
                        session=session,
                        contract_id=new_contract.id,
                        publisher_id=import_req.owner_team_id,
                        version="1.0.0",
                    )
                    contract_id = str(new_contract.id)
                    contracts_published += 1

                endpoints_results.append(
                    OpenAPIEndpointResult(
                        fqn=asset_def.fqn,
                        path=endpoint.path,
                        method=endpoint.method,
                        action="created",
                        asset_id=str(new_asset.id),
                        contract_id=contract_id,
                    )
                )
                assets_created += 1

        except Exception as e:
            endpoints_results.append(
                OpenAPIEndpointResult(
                    fqn=asset_def.fqn,
                    path=endpoint.path,
                    method=endpoint.method,
                    action="error",
                    error=str(e),
                )
            )
            assets_skipped += 1

    return OpenAPIImportResponse(
        api_title=parse_result.title,
        api_version=parse_result.version,
        endpoints_found=len(parse_result.endpoints),
        assets_created=assets_created,
        assets_updated=assets_updated,
        assets_skipped=assets_skipped,
        contracts_published=contracts_published,
        endpoints=endpoints_results,
        parse_errors=parse_result.errors,
    )


# =============================================================================
# GraphQL Import
# =============================================================================


class GraphQLImportRequest(BaseModel):
    """Request body for GraphQL schema import."""

    introspection: dict[str, Any] = Field(
        ..., description="GraphQL introspection response (__schema or data.__schema)"
    )
    schema_name: str = Field(
        default="GraphQL API",
        min_length=1,
        max_length=100,
        description="Name for the GraphQL schema (used in FQN generation)",
    )
    owner_team_id: UUID = Field(..., description="Team that will own the imported assets")
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment for assets"
    )
    auto_publish_contracts: bool = Field(
        default=True, description="Automatically publish contracts for new assets"
    )
    dry_run: bool = Field(default=False, description="Preview changes without creating assets")


class GraphQLOperationResult(BaseModel):
    """Result for a single GraphQL operation import."""

    fqn: str
    operation_name: str
    operation_type: str  # "query" or "mutation"
    action: str  # "created", "updated", "skipped", "error"
    asset_id: str | None = None
    contract_id: str | None = None
    error: str | None = None


class GraphQLImportResponse(BaseModel):
    """Response from GraphQL schema import."""

    schema_name: str
    operations_found: int
    assets_created: int
    assets_updated: int
    assets_skipped: int
    contracts_published: int
    operations: list[GraphQLOperationResult]
    parse_errors: list[str]


@router.post("/graphql", response_model=GraphQLImportResponse)
@limit_admin
async def import_graphql(
    request: Request,
    import_req: GraphQLImportRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GraphQLImportResponse:
    """Import assets and contracts from a GraphQL introspection response.

    Parses a GraphQL schema introspection and creates assets for each query/mutation.
    Each operation becomes an asset with resource_type=graphql_query.
    The argument and return types are combined into a contract.

    To get an introspection response, run the standard introspection query against
    your GraphQL endpoint:

    ```graphql
    query IntrospectionQuery {
      __schema {
        queryType { name }
        mutationType { name }
        types {
          kind name description
          fields { name description args { name type { ...TypeRef } } type { ...TypeRef } }
          inputFields { name type { ...TypeRef } }
          enumValues { name description }
          possibleTypes { name }
        }
      }
    }

    fragment TypeRef on __Type {
      kind name
      ofType { kind name ofType { kind name ofType { kind name } } }
    }
    ```

    Requires admin scope.

    Behavior:
    - New operations: Create asset and optionally publish contract
    - Existing operations: Update metadata, check for schema changes
    - dry_run=True: Preview changes without persisting

    Returns a summary of what was created/updated.
    """
    # Validate owner team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == import_req.owner_team_id))
    owner_team = team_result.scalar_one_or_none()
    if not owner_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

    # Parse the GraphQL introspection
    parse_result = parse_graphql_introspection(import_req.introspection)

    if not parse_result.operations and parse_result.errors:
        raise BadRequestError(
            "Failed to parse GraphQL introspection",
            code=ErrorCode.INVALID_OPENAPI_SPEC,  # Reuse error code
            details={"errors": parse_result.errors},
        )

    # Convert operations to asset definitions
    asset_defs = graphql_operations_to_assets(
        parse_result,
        import_req.owner_team_id,
        import_req.environment,
        schema_name_override=import_req.schema_name,
    )

    # Track results
    operations_results: list[GraphQLOperationResult] = []
    assets_created = 0
    assets_updated = 0
    assets_skipped = 0
    contracts_published = 0

    for i, asset_def in enumerate(asset_defs):
        operation = parse_result.operations[i]

        try:
            # Check if asset already exists
            existing_result = await session.execute(
                select(AssetDB)
                .where(AssetDB.fqn == asset_def.fqn)
                .where(AssetDB.environment == import_req.environment)
                .where(AssetDB.deleted_at.is_(None))
            )
            existing_asset = existing_result.scalar_one_or_none()

            if import_req.dry_run:
                # Dry run - just report what would happen
                if existing_asset:
                    operations_results.append(
                        GraphQLOperationResult(
                            fqn=asset_def.fqn,
                            operation_name=operation.name,
                            operation_type=operation.operation_type,
                            action="would_update",
                            asset_id=str(existing_asset.id),
                        )
                    )
                    assets_updated += 1
                else:
                    operations_results.append(
                        GraphQLOperationResult(
                            fqn=asset_def.fqn,
                            operation_name=operation.name,
                            operation_type=operation.operation_type,
                            action="would_create",
                        )
                    )
                    assets_created += 1
                    if import_req.auto_publish_contracts:
                        contracts_published += 1
                continue

            if existing_asset:
                # Update existing asset metadata
                existing_asset.metadata_ = {
                    **existing_asset.metadata_,
                    **asset_def.metadata,
                }
                existing_asset.resource_type = ResourceType.GRAPHQL_QUERY
                await session.flush()

                operations_results.append(
                    GraphQLOperationResult(
                        fqn=asset_def.fqn,
                        operation_name=operation.name,
                        operation_type=operation.operation_type,
                        action="updated",
                        asset_id=str(existing_asset.id),
                    )
                )
                assets_updated += 1
            else:
                # Create new asset
                new_asset = AssetDB(
                    fqn=asset_def.fqn,
                    owner_team_id=import_req.owner_team_id,
                    environment=import_req.environment,
                    resource_type=ResourceType.GRAPHQL_QUERY,
                    metadata_=asset_def.metadata,
                )
                session.add(new_asset)
                await session.flush()
                await session.refresh(new_asset)

                contract_id: str | None = None

                # Auto-publish contract if enabled
                if import_req.auto_publish_contracts:
                    new_contract = ContractDB(
                        asset_id=new_asset.id,
                        version="1.0.0",
                        schema_def=asset_def.schema_def,
                        compatibility_mode=CompatibilityMode.BACKWARD,
                        published_by=import_req.owner_team_id,
                    )
                    session.add(new_contract)
                    await session.flush()
                    await session.refresh(new_contract)

                    await log_contract_published(
                        session=session,
                        contract_id=new_contract.id,
                        publisher_id=import_req.owner_team_id,
                        version="1.0.0",
                    )
                    contract_id = str(new_contract.id)
                    contracts_published += 1

                operations_results.append(
                    GraphQLOperationResult(
                        fqn=asset_def.fqn,
                        operation_name=operation.name,
                        operation_type=operation.operation_type,
                        action="created",
                        asset_id=str(new_asset.id),
                        contract_id=contract_id,
                    )
                )
                assets_created += 1

        except Exception as e:
            operations_results.append(
                GraphQLOperationResult(
                    fqn=asset_def.fqn,
                    operation_name=operation.name,
                    operation_type=operation.operation_type,
                    action="error",
                    error=str(e),
                )
            )
            assets_skipped += 1

    return GraphQLImportResponse(
        schema_name=import_req.schema_name,
        operations_found=len(parse_result.operations),
        assets_created=assets_created,
        assets_updated=assets_updated,
        assets_skipped=assets_skipped,
        contracts_published=contracts_published,
        operations=operations_results,
        parse_errors=parse_result.errors,
    )
