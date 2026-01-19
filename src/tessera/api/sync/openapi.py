"""OpenAPI sync endpoints.

Endpoints for synchronizing schemas from OpenAPI specifications.
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
from tessera.services.openapi import (
    OpenAPIEndpoint,
    _merge_guarantees,
    endpoints_to_assets,
    parse_openapi,
)
from tessera.services.schema_diff import check_compatibility, diff_schemas

# Named constants for version handling
INITIAL_VERSION: Final[str] = "1.0.0"
"""Version assigned to the first contract published for an asset."""

router = APIRouter()


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
    default_guarantees: dict[str, Any] | None = Field(
        default=None,
        description="Default guarantees to apply to all endpoints",
    )


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

                # Log per-asset audit event
                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=existing_asset.id,
                    action=AuditAction.ASSET_UPDATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_openapi"},
                )

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

                # Log per-asset audit event
                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=new_asset.id,
                    action=AuditAction.ASSET_CREATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_openapi"},
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
# OpenAPI Impact and Diff Endpoints
# =============================================================================


class OpenAPIImpactRequest(BaseModel):
    """Request body for OpenAPI spec impact analysis."""

    spec: dict[str, Any] = Field(..., description="OpenAPI 3.x specification as JSON")
    environment: str = Field(
        default="production",
        min_length=1,
        max_length=50,
        description="Environment to check against",
    )


class OpenAPIImpactResult(BaseModel):
    """Impact analysis result for a single OpenAPI endpoint."""

    fqn: str
    path: str
    method: str
    has_contract: bool
    safe_to_publish: bool
    change_type: str | None = None
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class OpenAPIImpactResponse(BaseModel):
    """Response from OpenAPI spec impact analysis."""

    status: str
    api_title: str
    api_version: str
    total_endpoints: int
    endpoints_with_contracts: int
    breaking_changes_count: int
    results: list[OpenAPIImpactResult]
    parse_errors: list[str] = Field(default_factory=list)


async def _check_openapi_endpoint_impact(
    endpoint: "OpenAPIEndpoint",
    api_title: str,
    environment: str,
    session: AsyncSession,
) -> OpenAPIImpactResult:
    """Check impact of a single OpenAPI endpoint against its registered contract."""
    from tessera.services.openapi import generate_fqn as openapi_generate_fqn

    fqn = openapi_generate_fqn(api_title, endpoint.path, endpoint.method)

    # Look up existing asset and active contract
    asset_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == fqn)
        .where(AssetDB.environment == environment)
        .where(AssetDB.deleted_at.is_(None))
    )
    existing_asset = asset_result.scalar_one_or_none()

    if not existing_asset:
        return OpenAPIImpactResult(
            fqn=fqn,
            path=endpoint.path,
            method=endpoint.method,
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
        return OpenAPIImpactResult(
            fqn=fqn,
            path=endpoint.path,
            method=endpoint.method,
            has_contract=False,
            safe_to_publish=True,
            change_type=None,
            breaking_changes=[],
        )

    # Compare schemas
    proposed_schema = endpoint.combined_schema
    existing_schema = existing_contract.schema_def

    diff_result = diff_schemas(existing_schema, proposed_schema)
    is_compatible, breaking_changes_list = check_compatibility(
        existing_schema,
        proposed_schema,
        existing_contract.compatibility_mode,
    )

    return OpenAPIImpactResult(
        fqn=fqn,
        path=endpoint.path,
        method=endpoint.method,
        has_contract=True,
        safe_to_publish=is_compatible,
        change_type=diff_result.change_type.value,
        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
    )


@router.post("/openapi/impact", response_model=OpenAPIImpactResponse)
@limit_admin
async def check_openapi_impact(
    request: Request,
    impact_req: OpenAPIImpactRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> OpenAPIImpactResponse:
    """Check impact of an OpenAPI spec against registered contracts.

    Parses an OpenAPI 3.x spec and checks each endpoint's schema against
    existing contracts. This is the primary CI/CD integration point for API
    contract validation.

    Returns impact analysis for each endpoint, identifying breaking changes.
    """
    # Parse the OpenAPI spec
    parse_result = parse_openapi(impact_req.spec)

    if not parse_result.endpoints and parse_result.errors:
        raise BadRequestError(
            "Failed to parse OpenAPI spec",
            code=ErrorCode.INVALID_OPENAPI_SPEC,
            details={"errors": parse_result.errors},
        )

    results: list[OpenAPIImpactResult] = []

    for endpoint in parse_result.endpoints:
        result = await _check_openapi_endpoint_impact(
            endpoint,
            parse_result.title,
            impact_req.environment,
            session,
        )
        results.append(result)

    endpoints_with_contracts = sum(1 for r in results if r.has_contract)
    breaking_changes_count = sum(1 for r in results if not r.safe_to_publish)

    return OpenAPIImpactResponse(
        status="success" if breaking_changes_count == 0 else "breaking_changes_detected",
        api_title=parse_result.title,
        api_version=parse_result.version,
        total_endpoints=len(results),
        endpoints_with_contracts=endpoints_with_contracts,
        breaking_changes_count=breaking_changes_count,
        results=results,
        parse_errors=parse_result.errors,
    )


class OpenAPIDiffRequest(BaseModel):
    """Request body for OpenAPI spec diff (CI preview)."""

    spec: dict[str, Any] = Field(..., description="OpenAPI 3.x specification as JSON")
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment to diff against"
    )
    fail_on_breaking: bool = Field(
        default=True,
        description="Return blocking=true if any breaking changes are detected",
    )


class OpenAPIDiffItem(BaseModel):
    """A single change detected in OpenAPI spec."""

    fqn: str
    path: str
    method: str
    change_type: str  # 'new', 'modified', 'unchanged'
    has_schema: bool = True
    schema_change_type: str | None = None  # 'none', 'compatible', 'breaking'
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class OpenAPIDiffResponse(BaseModel):
    """Response from OpenAPI spec diff (CI preview)."""

    status: str  # 'clean', 'changes_detected', 'breaking_changes_detected'
    api_title: str
    api_version: str
    summary: dict[str, int]  # {'new': N, 'modified': M, 'unchanged': U, 'breaking': B}
    blocking: bool  # True if CI should fail
    endpoints: list[OpenAPIDiffItem]
    parse_errors: list[str] = Field(default_factory=list)


@router.post("/openapi/diff", response_model=OpenAPIDiffResponse)
@limit_admin
async def diff_openapi_spec(
    request: Request,
    diff_req: OpenAPIDiffRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> OpenAPIDiffResponse:
    """Preview what would change if this OpenAPI spec is applied (CI dry-run).

    This is the primary CI/CD integration point for API contract validation. Call this
    in your PR checks to:
    1. See what endpoints would be created/modified
    2. Detect breaking schema changes
    3. Fail the build if breaking changes aren't acknowledged

    Example CI usage:
    ```yaml
    - name: Check API contract impact
      run: |
        curl -X POST $TESSERA_URL/api/v1/sync/openapi/diff \\
          -H "Authorization: Bearer $TESSERA_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"spec": '$(cat openapi.json)', "fail_on_breaking": true}'
    ```
    """
    from tessera.services.openapi import generate_fqn as openapi_generate_fqn

    # Parse the OpenAPI spec
    parse_result = parse_openapi(diff_req.spec)

    if not parse_result.endpoints and parse_result.errors:
        raise BadRequestError(
            "Failed to parse OpenAPI spec",
            code=ErrorCode.INVALID_OPENAPI_SPEC,
            details={"errors": parse_result.errors},
        )

    endpoints: list[OpenAPIDiffItem] = []

    # Build FQN -> endpoint mapping from spec
    spec_fqns: dict[str, OpenAPIEndpoint] = {}
    for endpoint in parse_result.endpoints:
        fqn = openapi_generate_fqn(parse_result.title, endpoint.path, endpoint.method)
        spec_fqns[fqn] = endpoint

    # Get all existing assets for this environment
    existing_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.environment == diff_req.environment)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.resource_type == ResourceType.API_ENDPOINT)
    )
    existing_assets = {a.fqn: a for a in existing_result.scalars().all()}

    # Process each endpoint in the spec
    for fqn, endpoint in spec_fqns.items():
        existing_asset = existing_assets.get(fqn)

        if not existing_asset:
            # New endpoint
            endpoints.append(
                OpenAPIDiffItem(
                    fqn=fqn,
                    path=endpoint.path,
                    method=endpoint.method,
                    change_type="new",
                    has_schema=True,
                    schema_change_type=None,
                    breaking_changes=[],
                )
            )
        else:
            # Existing endpoint - check for schema changes
            contract_result = await session.execute(
                select(ContractDB)
                .where(ContractDB.asset_id == existing_asset.id)
                .where(ContractDB.status == ContractStatus.ACTIVE)
            )
            existing_contract = contract_result.scalar_one_or_none()

            if not existing_contract:
                # No contract to compare
                endpoints.append(
                    OpenAPIDiffItem(
                        fqn=fqn,
                        path=endpoint.path,
                        method=endpoint.method,
                        change_type="modified",
                        has_schema=True,
                        schema_change_type=None,
                        breaking_changes=[],
                    )
                )
            else:
                # Compare schemas
                proposed_schema = endpoint.combined_schema
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

                endpoints.append(
                    OpenAPIDiffItem(
                        fqn=fqn,
                        path=endpoint.path,
                        method=endpoint.method,
                        change_type=change_type,
                        has_schema=True,
                        schema_change_type=schema_change_type,
                        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
                    )
                )

    # Calculate summary
    summary = {
        "new": sum(1 for e in endpoints if e.change_type == "new"),
        "modified": sum(1 for e in endpoints if e.change_type == "modified"),
        "unchanged": sum(1 for e in endpoints if e.change_type == "unchanged"),
        "breaking": sum(1 for e in endpoints if e.schema_change_type == "breaking"),
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

    return OpenAPIDiffResponse(
        status=status,
        api_title=parse_result.title,
        api_version=parse_result.version,
        summary=summary,
        blocking=blocking,
        endpoints=endpoints,
        parse_errors=parse_result.errors,
    )
