"""GraphQL sync endpoints.

Endpoints for synchronizing schemas from GraphQL introspection.
"""

from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_admin
from tessera.db import AssetDB, ContractDB, TeamDB, get_session
from tessera.models.enums import CompatibilityMode, ContractStatus, ResourceType
from tessera.services import audit
from tessera.services.audit import AuditAction, log_contract_published
from tessera.services.graphql import GraphQLOperation, parse_graphql_introspection
from tessera.services.graphql import operations_to_assets as graphql_operations_to_assets
from tessera.services.openapi import _merge_guarantees
from tessera.services.schema_diff import check_compatibility, diff_schemas

# Named constants for version handling
INITIAL_VERSION: Final[str] = "1.0.0"
"""Version assigned to the first contract published for an asset."""

router = APIRouter()


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
    default_guarantees: dict[str, Any] | None = Field(
        default=None,
        description="Default guarantees to apply to all operations",
    )


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

                # Log per-asset audit event
                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=existing_asset.id,
                    action=AuditAction.ASSET_UPDATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_graphql"},
                )

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

                # Log per-asset audit event
                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=new_asset.id,
                    action=AuditAction.ASSET_CREATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_graphql"},
                )

                contract_id: str | None = None

                # Auto-publish contract if enabled
                if import_req.auto_publish_contracts:
                    # Merge default_guarantees with per-operation guarantees
                    merged_guarantees = _merge_guarantees(
                        import_req.default_guarantees, asset_def.guarantees
                    )

                    new_contract = ContractDB(
                        asset_id=new_asset.id,
                        version=INITIAL_VERSION,
                        schema_def=asset_def.schema_def,
                        compatibility_mode=CompatibilityMode.BACKWARD,
                        guarantees=merged_guarantees,
                        published_by=import_req.owner_team_id,
                    )
                    session.add(new_contract)
                    await session.flush()
                    await session.refresh(new_contract)

                    await log_contract_published(
                        session=session,
                        contract_id=new_contract.id,
                        publisher_id=import_req.owner_team_id,
                        version=INITIAL_VERSION,
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


# =============================================================================
# GraphQL Impact and Diff Endpoints
# =============================================================================


class GraphQLImpactRequest(BaseModel):
    """Request body for GraphQL schema impact analysis."""

    introspection: dict[str, Any] = Field(
        ..., description="GraphQL introspection response (__schema or data.__schema)"
    )
    schema_name: str = Field(
        default="GraphQL API",
        min_length=1,
        max_length=100,
        description="Name for the GraphQL schema (used in FQN generation)",
    )
    environment: str = Field(
        default="production",
        min_length=1,
        max_length=50,
        description="Environment to check against",
    )


class GraphQLImpactResult(BaseModel):
    """Impact analysis result for a single GraphQL operation."""

    fqn: str
    operation_name: str
    operation_type: str  # "query" or "mutation"
    has_contract: bool
    safe_to_publish: bool
    change_type: str | None = None
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class GraphQLImpactResponse(BaseModel):
    """Response from GraphQL schema impact analysis."""

    status: str
    schema_name: str
    total_operations: int
    operations_with_contracts: int
    breaking_changes_count: int
    results: list[GraphQLImpactResult]
    parse_errors: list[str] = Field(default_factory=list)


async def _check_graphql_operation_impact(
    operation: "GraphQLOperation",
    schema_name: str,
    environment: str,
    session: AsyncSession,
) -> GraphQLImpactResult:
    """Check impact of a single GraphQL operation against its registered contract."""
    from tessera.services.graphql import generate_fqn as graphql_generate_fqn

    fqn = graphql_generate_fqn(schema_name, operation.name, operation.operation_type)

    # Look up existing asset and active contract
    asset_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == fqn)
        .where(AssetDB.environment == environment)
        .where(AssetDB.deleted_at.is_(None))
    )
    existing_asset = asset_result.scalar_one_or_none()

    if not existing_asset:
        return GraphQLImpactResult(
            fqn=fqn,
            operation_name=operation.name,
            operation_type=operation.operation_type,
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
        return GraphQLImpactResult(
            fqn=fqn,
            operation_name=operation.name,
            operation_type=operation.operation_type,
            has_contract=False,
            safe_to_publish=True,
            change_type=None,
            breaking_changes=[],
        )

    # Compare schemas
    proposed_schema = operation.combined_schema
    existing_schema = existing_contract.schema_def

    diff_result = diff_schemas(existing_schema, proposed_schema)
    is_compatible, breaking_changes_list = check_compatibility(
        existing_schema,
        proposed_schema,
        existing_contract.compatibility_mode,
    )

    return GraphQLImpactResult(
        fqn=fqn,
        operation_name=operation.name,
        operation_type=operation.operation_type,
        has_contract=True,
        safe_to_publish=is_compatible,
        change_type=diff_result.change_type.value,
        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
    )


@router.post("/graphql/impact", response_model=GraphQLImpactResponse)
@limit_admin
async def check_graphql_impact(
    request: Request,
    impact_req: GraphQLImpactRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GraphQLImpactResponse:
    """Check impact of a GraphQL schema against registered contracts.

    Parses a GraphQL introspection response and checks each operation's schema
    against existing contracts. This is the primary CI/CD integration point for
    GraphQL contract validation.

    Returns impact analysis for each operation, identifying breaking changes.
    """
    # Parse the GraphQL introspection
    parse_result = parse_graphql_introspection(impact_req.introspection)

    if not parse_result.operations and parse_result.errors:
        raise BadRequestError(
            "Failed to parse GraphQL introspection",
            code=ErrorCode.INVALID_OPENAPI_SPEC,  # Reuse error code
            details={"errors": parse_result.errors},
        )

    results: list[GraphQLImpactResult] = []

    for operation in parse_result.operations:
        result = await _check_graphql_operation_impact(
            operation,
            impact_req.schema_name,
            impact_req.environment,
            session,
        )
        results.append(result)

    operations_with_contracts = sum(1 for r in results if r.has_contract)
    breaking_changes_count = sum(1 for r in results if not r.safe_to_publish)

    return GraphQLImpactResponse(
        status="success" if breaking_changes_count == 0 else "breaking_changes_detected",
        schema_name=impact_req.schema_name,
        total_operations=len(results),
        operations_with_contracts=operations_with_contracts,
        breaking_changes_count=breaking_changes_count,
        results=results,
        parse_errors=parse_result.errors,
    )


class GraphQLDiffRequest(BaseModel):
    """Request body for GraphQL schema diff (CI preview)."""

    introspection: dict[str, Any] = Field(
        ..., description="GraphQL introspection response (__schema or data.__schema)"
    )
    schema_name: str = Field(
        default="GraphQL API",
        min_length=1,
        max_length=100,
        description="Name for the GraphQL schema (used in FQN generation)",
    )
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment to diff against"
    )
    fail_on_breaking: bool = Field(
        default=True,
        description="Return blocking=true if any breaking changes are detected",
    )


class GraphQLDiffItem(BaseModel):
    """A single change detected in GraphQL schema."""

    fqn: str
    operation_name: str
    operation_type: str  # "query" or "mutation"
    change_type: str  # 'new', 'modified', 'unchanged'
    has_schema: bool = True
    schema_change_type: str | None = None  # 'none', 'compatible', 'breaking'
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class GraphQLDiffResponse(BaseModel):
    """Response from GraphQL schema diff (CI preview)."""

    status: str  # 'clean', 'changes_detected', 'breaking_changes_detected'
    schema_name: str
    summary: dict[str, int]  # {'new': N, 'modified': M, 'unchanged': U, 'breaking': B}
    blocking: bool  # True if CI should fail
    operations: list[GraphQLDiffItem]
    parse_errors: list[str] = Field(default_factory=list)


@router.post("/graphql/diff", response_model=GraphQLDiffResponse)
@limit_admin
async def diff_graphql_schema(
    request: Request,
    diff_req: GraphQLDiffRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GraphQLDiffResponse:
    """Preview what would change if this GraphQL schema is applied (CI dry-run).

    This is the primary CI/CD integration point for GraphQL contract validation. Call
    this in your PR checks to:
    1. See what operations would be created/modified
    2. Detect breaking schema changes
    3. Fail the build if breaking changes aren't acknowledged

    Example CI usage:
    ```yaml
    - name: Check GraphQL contract impact
      run: |
        # Get introspection
        INTROSPECTION=$(curl -s $GRAPHQL_URL -H "Content-Type: application/json" \\
          -d '{"query": "{ __schema { ... } }"}')
        # Check for breaking changes
        curl -X POST $TESSERA_URL/api/v1/sync/graphql/diff \\
          -H "Authorization: Bearer $TESSERA_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d "{\"introspection\": $INTROSPECTION, \"fail_on_breaking\": true}"
    ```
    """
    from tessera.services.graphql import generate_fqn as graphql_generate_fqn

    # Parse the GraphQL introspection
    parse_result = parse_graphql_introspection(diff_req.introspection)

    if not parse_result.operations and parse_result.errors:
        raise BadRequestError(
            "Failed to parse GraphQL introspection",
            code=ErrorCode.INVALID_OPENAPI_SPEC,  # Reuse error code
            details={"errors": parse_result.errors},
        )

    operations: list[GraphQLDiffItem] = []

    # Build FQN -> operation mapping from introspection
    schema_fqns: dict[str, GraphQLOperation] = {}
    for operation in parse_result.operations:
        fqn = graphql_generate_fqn(diff_req.schema_name, operation.name, operation.operation_type)
        schema_fqns[fqn] = operation

    # Get all existing GraphQL assets for this environment
    existing_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.environment == diff_req.environment)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.resource_type == ResourceType.GRAPHQL_QUERY)
    )
    existing_assets = {a.fqn: a for a in existing_result.scalars().all()}

    # Process each operation in the schema
    for fqn, operation in schema_fqns.items():
        existing_asset = existing_assets.get(fqn)

        if not existing_asset:
            # New operation
            operations.append(
                GraphQLDiffItem(
                    fqn=fqn,
                    operation_name=operation.name,
                    operation_type=operation.operation_type,
                    change_type="new",
                    has_schema=True,
                    schema_change_type=None,
                    breaking_changes=[],
                )
            )
        else:
            # Existing operation - check for schema changes
            contract_result = await session.execute(
                select(ContractDB)
                .where(ContractDB.asset_id == existing_asset.id)
                .where(ContractDB.status == ContractStatus.ACTIVE)
            )
            existing_contract = contract_result.scalar_one_or_none()

            if not existing_contract:
                # No contract to compare
                operations.append(
                    GraphQLDiffItem(
                        fqn=fqn,
                        operation_name=operation.name,
                        operation_type=operation.operation_type,
                        change_type="modified",
                        has_schema=True,
                        schema_change_type=None,
                        breaking_changes=[],
                    )
                )
            else:
                # Compare schemas
                proposed_schema = operation.combined_schema
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

                operations.append(
                    GraphQLDiffItem(
                        fqn=fqn,
                        operation_name=operation.name,
                        operation_type=operation.operation_type,
                        change_type=change_type,
                        has_schema=True,
                        schema_change_type=schema_change_type,
                        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
                    )
                )

    # Calculate summary
    summary = {
        "new": sum(1 for o in operations if o.change_type == "new"),
        "modified": sum(1 for o in operations if o.change_type == "modified"),
        "unchanged": sum(1 for o in operations if o.change_type == "unchanged"),
        "breaking": sum(1 for o in operations if o.schema_change_type == "breaking"),
    }

    # Determine status and blocking
    has_breaking = summary["breaking"] > 0

    if has_breaking:
        status = "breaking_changes_detected"
    elif summary["new"] > 0 or summary["modified"] > 0:
        status = "changes_detected"
    else:
        status = "clean"

    blocking = has_breaking and diff_req.fail_on_breaking

    return GraphQLDiffResponse(
        status=status,
        schema_name=diff_req.schema_name,
        summary=summary,
        blocking=blocking,
        operations=operations,
        parse_errors=parse_result.errors,
    )
