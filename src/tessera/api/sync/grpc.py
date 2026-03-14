"""gRPC / Protocol Buffers sync endpoints.

Endpoints for synchronizing schemas from .proto file definitions.
"""

from typing import Any
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
from tessera.services.grpc import (
    GRPCRpcMethod,
    parse_proto,
    rpc_methods_to_assets,
)
from tessera.services.schema_diff import check_compatibility, diff_schemas
from tessera.services.versioning import INITIAL_VERSION

router = APIRouter()


# =============================================================================
# gRPC Import
# =============================================================================


class GRPCImportRequest(BaseModel):
    """Request body for gRPC proto import."""

    proto_content: str = Field(
        ...,
        min_length=1,
        description="Raw .proto file content (proto3 syntax)",
    )
    owner_team_id: UUID = Field(..., description="Team that will own the imported assets")
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment for assets"
    )
    auto_publish_contracts: bool = Field(
        default=True, description="Automatically publish contracts for new assets"
    )
    dry_run: bool = Field(default=False, description="Preview changes without creating assets")


class GRPCMethodResult(BaseModel):
    """Result for a single RPC method import."""

    fqn: str
    service: str
    method: str
    action: str  # "created", "updated", "skipped", "error"
    asset_id: str | None = None
    contract_id: str | None = None
    error: str | None = None


class GRPCImportResponse(BaseModel):
    """Response from gRPC proto import."""

    package: str
    syntax: str
    services_found: int
    methods_found: int
    assets_created: int
    assets_updated: int
    assets_skipped: int
    contracts_published: int
    methods: list[GRPCMethodResult]
    parse_errors: list[str]


@router.post("/grpc", response_model=GRPCImportResponse)
@limit_admin
async def import_grpc(
    request: Request,
    import_req: GRPCImportRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GRPCImportResponse:
    """Import assets and contracts from a Protocol Buffer (.proto) file.

    Parses a proto3 file and creates assets for each RPC method in every
    service definition. Each RPC method becomes an asset with
    resource_type=grpc_service. The request/response message types are
    converted to JSON Schema and combined into a contract.

    Requires admin scope.

    Behavior:
    - New RPC methods: Create asset and optionally publish contract
    - Existing RPC methods: Update metadata
    - dry_run=True: Preview changes without persisting

    Returns a summary of what was created/updated.
    """
    # Validate owner team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == import_req.owner_team_id))
    owner_team = team_result.scalar_one_or_none()
    if not owner_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Owner team not found")

    # Parse the proto file
    parse_result = parse_proto(import_req.proto_content)

    if not parse_result.rpc_methods and parse_result.errors:
        raise BadRequestError(
            "Failed to parse .proto file",
            code=ErrorCode.INVALID_PROTO_SPEC,
            details={"errors": parse_result.errors},
        )

    if not parse_result.rpc_methods and not parse_result.errors:
        raise BadRequestError(
            "No RPC methods found in .proto file",
            code=ErrorCode.INVALID_PROTO_SPEC,
            details={
                "services_found": len(parse_result.services),
                "messages_found": len(parse_result.messages),
            },
        )

    # Convert to asset definitions
    asset_defs = rpc_methods_to_assets(
        parse_result, import_req.owner_team_id, import_req.environment
    )

    # Track results
    method_results: list[GRPCMethodResult] = []
    assets_created = 0
    assets_updated = 0
    assets_skipped = 0
    contracts_published = 0

    for i, asset_def in enumerate(asset_defs):
        rpc = parse_result.rpc_methods[i]

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
                if existing_asset:
                    method_results.append(
                        GRPCMethodResult(
                            fqn=asset_def.fqn,
                            service=rpc.service_name,
                            method=rpc.method_name,
                            action="would_update",
                            asset_id=str(existing_asset.id),
                        )
                    )
                    assets_updated += 1
                else:
                    method_results.append(
                        GRPCMethodResult(
                            fqn=asset_def.fqn,
                            service=rpc.service_name,
                            method=rpc.method_name,
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
                existing_asset.resource_type = ResourceType.GRPC_SERVICE
                await session.flush()

                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=existing_asset.id,
                    action=AuditAction.ASSET_UPDATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_grpc"},
                )

                method_results.append(
                    GRPCMethodResult(
                        fqn=asset_def.fqn,
                        service=rpc.service_name,
                        method=rpc.method_name,
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
                    resource_type=ResourceType.GRPC_SERVICE,
                    metadata_=asset_def.metadata,
                )
                session.add(new_asset)
                await session.flush()
                await session.refresh(new_asset)

                await audit.log_event(
                    session=session,
                    entity_type="asset",
                    entity_id=new_asset.id,
                    action=AuditAction.ASSET_CREATED,
                    actor_id=import_req.owner_team_id,
                    payload={"fqn": asset_def.fqn, "triggered_by": "import_grpc"},
                )

                contract_id: str | None = None

                if import_req.auto_publish_contracts:
                    new_contract = ContractDB(
                        asset_id=new_asset.id,
                        version=INITIAL_VERSION,
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
                        version=INITIAL_VERSION,
                    )
                    contract_id = str(new_contract.id)
                    contracts_published += 1

                method_results.append(
                    GRPCMethodResult(
                        fqn=asset_def.fqn,
                        service=rpc.service_name,
                        method=rpc.method_name,
                        action="created",
                        asset_id=str(new_asset.id),
                        contract_id=contract_id,
                    )
                )
                assets_created += 1

        except Exception as e:
            method_results.append(
                GRPCMethodResult(
                    fqn=asset_def.fqn,
                    service=rpc.service_name,
                    method=rpc.method_name,
                    action="error",
                    error=str(e),
                )
            )
            assets_skipped += 1

    return GRPCImportResponse(
        package=parse_result.package,
        syntax=parse_result.syntax,
        services_found=len(parse_result.services),
        methods_found=len(parse_result.rpc_methods),
        assets_created=assets_created,
        assets_updated=assets_updated,
        assets_skipped=assets_skipped,
        contracts_published=contracts_published,
        methods=method_results,
        parse_errors=parse_result.errors,
    )


# =============================================================================
# gRPC Impact and Diff Endpoints
# =============================================================================


class GRPCImpactRequest(BaseModel):
    """Request body for gRPC proto impact analysis."""

    proto_content: str = Field(
        ...,
        min_length=1,
        description="Raw .proto file content (proto3 syntax)",
    )
    environment: str = Field(
        default="production",
        min_length=1,
        max_length=50,
        description="Environment to check against",
    )


class GRPCImpactResult(BaseModel):
    """Impact analysis result for a single RPC method."""

    fqn: str
    service: str
    method: str
    has_contract: bool
    safe_to_publish: bool
    change_type: str | None = None
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class GRPCImpactResponse(BaseModel):
    """Response from gRPC proto impact analysis."""

    status: str
    package: str
    total_methods: int
    methods_with_contracts: int
    breaking_changes_count: int
    results: list[GRPCImpactResult]
    parse_errors: list[str] = Field(default_factory=list)


async def _check_grpc_method_impact(
    rpc: GRPCRpcMethod,
    package: str,
    environment: str,
    session: AsyncSession,
) -> GRPCImpactResult:
    """Check impact of a single RPC method against its registered contract."""
    from tessera.services.grpc import generate_fqn as grpc_generate_fqn

    fqn = grpc_generate_fqn(package, rpc.service_name, rpc.method_name)

    asset_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == fqn)
        .where(AssetDB.environment == environment)
        .where(AssetDB.deleted_at.is_(None))
    )
    existing_asset = asset_result.scalar_one_or_none()

    if not existing_asset:
        return GRPCImpactResult(
            fqn=fqn,
            service=rpc.service_name,
            method=rpc.method_name,
            has_contract=False,
            safe_to_publish=True,
        )

    contract_result = await session.execute(
        select(ContractDB).where(
            ContractDB.asset_id == existing_asset.id,
            ContractDB.status == ContractStatus.ACTIVE,
        )
    )
    existing_contract = contract_result.scalar_one_or_none()

    if not existing_contract:
        return GRPCImpactResult(
            fqn=fqn,
            service=rpc.service_name,
            method=rpc.method_name,
            has_contract=False,
            safe_to_publish=True,
        )

    proposed_schema = rpc.combined_schema
    existing_schema = existing_contract.schema_def

    diff_result = diff_schemas(existing_schema, proposed_schema)
    is_compatible, breaking_changes_list = check_compatibility(
        existing_schema,
        proposed_schema,
        existing_contract.compatibility_mode,
    )

    return GRPCImpactResult(
        fqn=fqn,
        service=rpc.service_name,
        method=rpc.method_name,
        has_contract=True,
        safe_to_publish=is_compatible,
        change_type=diff_result.change_type.value,
        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
    )


@router.post("/grpc/impact", response_model=GRPCImpactResponse)
@limit_admin
async def check_grpc_impact(
    request: Request,
    impact_req: GRPCImpactRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GRPCImpactResponse:
    """Check impact of a .proto file against registered contracts.

    Parses a proto3 file and checks each RPC method's schema against existing
    contracts. Use this in CI/CD to detect breaking changes.

    Returns impact analysis for each RPC method.
    """
    parse_result = parse_proto(impact_req.proto_content)

    if not parse_result.rpc_methods and parse_result.errors:
        raise BadRequestError(
            "Failed to parse .proto file",
            code=ErrorCode.INVALID_PROTO_SPEC,
            details={"errors": parse_result.errors},
        )

    results: list[GRPCImpactResult] = []

    for rpc in parse_result.rpc_methods:
        result = await _check_grpc_method_impact(
            rpc,
            parse_result.package,
            impact_req.environment,
            session,
        )
        results.append(result)

    methods_with_contracts = sum(1 for r in results if r.has_contract)
    breaking_changes_count = sum(1 for r in results if not r.safe_to_publish)

    return GRPCImpactResponse(
        status="success" if breaking_changes_count == 0 else "breaking_changes_detected",
        package=parse_result.package,
        total_methods=len(results),
        methods_with_contracts=methods_with_contracts,
        breaking_changes_count=breaking_changes_count,
        results=results,
        parse_errors=parse_result.errors,
    )


class GRPCDiffRequest(BaseModel):
    """Request body for gRPC proto diff (CI preview)."""

    proto_content: str = Field(
        ...,
        min_length=1,
        description="Raw .proto file content (proto3 syntax)",
    )
    environment: str = Field(
        default="production", min_length=1, max_length=50, description="Environment to diff against"
    )
    fail_on_breaking: bool = Field(
        default=True,
        description="Return blocking=true if any breaking changes are detected",
    )


class GRPCDiffItem(BaseModel):
    """A single change detected in gRPC proto."""

    fqn: str
    service: str
    method: str
    change_type: str  # 'new', 'modified', 'unchanged'
    has_schema: bool = True
    schema_change_type: str | None = None  # 'none', 'compatible', 'breaking'
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class GRPCDiffResponse(BaseModel):
    """Response from gRPC proto diff (CI preview)."""

    status: str  # 'clean', 'changes_detected', 'breaking_changes_detected'
    package: str
    summary: dict[str, int]  # {'new': N, 'modified': M, 'unchanged': U, 'breaking': B}
    blocking: bool
    methods: list[GRPCDiffItem]
    parse_errors: list[str] = Field(default_factory=list)


@router.post("/grpc/diff", response_model=GRPCDiffResponse)
@limit_admin
async def diff_grpc_proto(
    request: Request,
    diff_req: GRPCDiffRequest,
    auth: Auth,
    _: None = RequireAdmin,
    session: AsyncSession = Depends(get_session),
) -> GRPCDiffResponse:
    """Preview what would change if this .proto file is applied (CI dry-run).

    Parses a proto3 file and compares each RPC method's schema against existing
    contracts. Use in PR checks to detect breaking changes before merging.

    Example CI usage:
    ```yaml
    - name: Check gRPC contract impact
      run: |
        curl -X POST $TESSERA_URL/api/v1/sync/grpc/diff \\
          -H "Authorization: Bearer $TESSERA_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"proto_content": "'$(cat service.proto | jq -Rs .)'", "fail_on_breaking": true}'
    ```
    """
    from tessera.services.grpc import generate_fqn as grpc_generate_fqn

    parse_result = parse_proto(diff_req.proto_content)

    if not parse_result.rpc_methods and parse_result.errors:
        raise BadRequestError(
            "Failed to parse .proto file",
            code=ErrorCode.INVALID_PROTO_SPEC,
            details={"errors": parse_result.errors},
        )

    methods: list[GRPCDiffItem] = []

    # Build FQN -> RPC mapping
    proto_fqns: dict[str, GRPCRpcMethod] = {}
    for rpc in parse_result.rpc_methods:
        fqn = grpc_generate_fqn(parse_result.package, rpc.service_name, rpc.method_name)
        proto_fqns[fqn] = rpc

    # Get all existing gRPC assets
    existing_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.environment == diff_req.environment)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.resource_type == ResourceType.GRPC_SERVICE)
    )
    existing_assets = {a.fqn: a for a in existing_result.scalars().all()}

    for fqn, rpc in proto_fqns.items():
        existing_asset = existing_assets.get(fqn)

        if not existing_asset:
            methods.append(
                GRPCDiffItem(
                    fqn=fqn,
                    service=rpc.service_name,
                    method=rpc.method_name,
                    change_type="new",
                    has_schema=True,
                    schema_change_type=None,
                    breaking_changes=[],
                )
            )
        else:
            contract_result = await session.execute(
                select(ContractDB)
                .where(ContractDB.asset_id == existing_asset.id)
                .where(ContractDB.status == ContractStatus.ACTIVE)
            )
            existing_contract = contract_result.scalar_one_or_none()

            if not existing_contract:
                methods.append(
                    GRPCDiffItem(
                        fqn=fqn,
                        service=rpc.service_name,
                        method=rpc.method_name,
                        change_type="modified",
                        has_schema=True,
                        schema_change_type=None,
                        breaking_changes=[],
                    )
                )
            else:
                proposed_schema = rpc.combined_schema
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

                methods.append(
                    GRPCDiffItem(
                        fqn=fqn,
                        service=rpc.service_name,
                        method=rpc.method_name,
                        change_type=change_type,
                        has_schema=True,
                        schema_change_type=schema_change_type,
                        breaking_changes=[bc.to_dict() for bc in breaking_changes_list],
                    )
                )

    summary = {
        "new": sum(1 for m in methods if m.change_type == "new"),
        "modified": sum(1 for m in methods if m.change_type == "modified"),
        "unchanged": sum(1 for m in methods if m.change_type == "unchanged"),
        "breaking": sum(1 for m in methods if m.schema_change_type == "breaking"),
    }

    has_breaking = summary["breaking"] > 0

    if has_breaking:
        status = "breaking_changes_detected"
    elif summary["new"] > 0 or summary["modified"] > 0:
        status = "changes_detected"
    else:
        status = "clean"

    blocking = has_breaking and diff_req.fail_on_breaking

    return GRPCDiffResponse(
        status=status,
        package=parse_result.package,
        summary=summary,
        blocking=blocking,
        methods=methods,
        parse_errors=parse_result.errors,
    )
