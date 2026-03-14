"""Contract read endpoints: list, history, diff, and version suggestion preview."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_expensive, limit_read
from tessera.api.types import (
    ContractHistoryEntry,
    ContractHistoryResponse,
    ContractWithPublisherInfo,
    PaginatedResponse,
    SchemaDiffResponse,
)
from tessera.config import settings
from tessera.db import AssetDB, ContractDB, TeamDB, UserDB, get_session
from tessera.models import Contract, VersionSuggestion, VersionSuggestionRequest
from tessera.models.enums import ChangeType, ContractStatus, SchemaFormat
from tessera.services import check_compatibility, diff_schemas, validate_json_schema
from tessera.services.avro import (
    AvroConversionError,
    avro_to_json_schema,
    validate_avro_schema,
)
from tessera.services.cache import (
    cache_asset_contracts_list,
    cache_schema_diff,
    get_cached_asset_contracts_list,
    get_cached_schema_diff,
)
from tessera.services.versioning import compute_version_suggestion

from .helpers import _E

router = APIRouter()


@router.get("/{asset_id}/contracts", responses={k: _E[k] for k in (401, 403)})
@limit_read
async def list_asset_contracts(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[ContractWithPublisherInfo]:
    """List all contracts for an asset.

    Requires read scope. Returns contracts with publisher team and user names.
    """
    # Try cache first (only for default pagination to keep cache simple)
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        cached = await get_cached_asset_contracts_list(str(asset_id))
        if cached:
            return cached  # type: ignore[return-value]

    # Query with join to get publisher team and user names
    query = (
        select(
            ContractDB,
            TeamDB.name.label("publisher_team_name"),
            UserDB.name.label("publisher_user_name"),
        )
        .outerjoin(TeamDB, ContractDB.published_by == TeamDB.id)
        .outerjoin(UserDB, ContractDB.published_by_user_id == UserDB.id)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )

    # Get total count
    count_query = select(func.count()).select_from(
        select(ContractDB).where(ContractDB.asset_id == asset_id).subquery()
    )
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    paginated_query = query.limit(params.limit).offset(params.offset)
    result = await session.execute(paginated_query)
    rows = result.all()

    results: list[ContractWithPublisherInfo] = []
    for contract_db, publisher_team_name, publisher_user_name in rows:
        contract_dict: ContractWithPublisherInfo = Contract.model_validate(contract_db).model_dump()  # type: ignore[assignment]
        contract_dict["published_by_team_name"] = publisher_team_name
        contract_dict["published_by_user_name"] = publisher_user_name
        results.append(contract_dict)

    response: PaginatedResponse[ContractWithPublisherInfo] = {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }

    # Cache result if default pagination
    if params.limit == settings.pagination_limit_default and params.offset == 0:
        await cache_asset_contracts_list(str(asset_id), response)  # type: ignore[arg-type]

    return response


@router.get(
    "/{asset_id}/contracts/history",
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_contract_history(
    request: Request,
    asset_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ContractHistoryResponse:
    """Get the complete contract history for an asset with change summaries.

    Returns all versions ordered by publication date with change type annotations.
    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Get all contracts ordered by published_at
    contracts_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .order_by(ContractDB.published_at.desc())
    )
    contracts = list(contracts_result.scalars().all())

    # Build history with change analysis
    history: list[ContractHistoryEntry] = []
    for i, contract_item in enumerate(contracts):
        entry: ContractHistoryEntry = {
            "id": str(contract_item.id),
            "version": contract_item.version,
            "status": str(contract_item.status.value),
            "published_at": contract_item.published_at.isoformat(),
            "published_by": str(contract_item.published_by),
            "compatibility_mode": str(contract_item.compatibility_mode.value),
        }

        # Compare with next (older) contract if exists
        if i < len(contracts) - 1:
            older_contract = contracts[i + 1]
            diff_result = diff_schemas(older_contract.schema_def, contract_item.schema_def)
            breaking = diff_result.breaking_for_mode(older_contract.compatibility_mode)
            entry["change_type"] = str(diff_result.change_type.value)
            entry["breaking_changes_count"] = len(breaking)
        else:
            # First contract
            entry["change_type"] = "initial"
            entry["breaking_changes_count"] = 0

        history.append(entry)

    return ContractHistoryResponse(
        asset_id=str(asset_id),
        asset_fqn=asset.fqn,
        contracts=history,
    )


@router.get(
    "/{asset_id}/contracts/diff",
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_read
@limit_expensive  # Per-team rate limit for expensive schema diff operation
async def diff_contract_versions(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    from_version: str = Query(..., description="Source version to compare from"),
    to_version: str = Query(..., description="Target version to compare to"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> SchemaDiffResponse:
    """Compare two contract versions for an asset.

    Returns the diff between from_version and to_version.
    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(select(AssetDB).where(AssetDB.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Get the from_version contract
    from_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == from_version)
    )
    from_contract = from_result.scalar_one_or_none()
    if not from_contract:
        raise NotFoundError(
            ErrorCode.CONTRACT_NOT_FOUND,
            f"Contract version '{from_version}' not found for this asset",
        )

    # Get the to_version contract
    to_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.version == to_version)
    )
    to_contract = to_result.scalar_one_or_none()
    if not to_contract:
        raise NotFoundError(
            ErrorCode.CONTRACT_NOT_FOUND,
            f"Contract version '{to_version}' not found for this asset",
        )

    # Perform diff
    # Try cache
    cached = await get_cached_schema_diff(from_contract.schema_def, to_contract.schema_def)
    if cached:
        diff_result_data = cached
    else:
        diff_result = diff_schemas(from_contract.schema_def, to_contract.schema_def)
        diff_result_data = {
            "change_type": str(diff_result.change_type.value),
            "all_changes": [c.to_dict() for c in diff_result.changes],
        }
        await cache_schema_diff(from_contract.schema_def, to_contract.schema_def, diff_result_data)

    # Re-calculate breaking based on compatibility mode of from_contract
    # We need to re-check compatibility because it depends on the mode
    # re-diff for breaking (fast)
    diff_obj = diff_schemas(from_contract.schema_def, to_contract.schema_def)
    breaking = diff_obj.breaking_for_mode(from_contract.compatibility_mode)

    return SchemaDiffResponse(
        asset_id=str(asset_id),
        asset_fqn=asset.fqn,
        from_version=from_version,
        to_version=to_version,
        change_type=diff_result_data["change_type"],
        is_compatible=len(breaking) == 0,
        breaking_changes=[bc.to_dict() for bc in breaking],
        all_changes=diff_result_data["all_changes"],
        compatibility_mode=str(from_contract.compatibility_mode.value),
    )


@router.post(
    "/{asset_id}/version-suggestion",
    response_model=VersionSuggestion,
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_read
async def preview_version_suggestion(
    request: Request,
    asset_id: UUID,
    body: VersionSuggestionRequest,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> VersionSuggestion:
    """Preview version suggestion for a schema change without publishing.

    This endpoint analyzes a proposed schema against the current active contract
    and returns what version would be suggested, along with any breaking changes.
    No side effects - no contracts or proposals are created.

    Useful for:
    - CI/CD pipelines that want to show impact before PR merge
    - UIs that want to preview "this will be version 2.0.0" before confirmation

    Requires read scope.
    """
    # Verify asset exists
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Validate and normalize schema based on format
    schema_to_check = body.schema_def

    if body.schema_format == SchemaFormat.AVRO:
        is_valid, avro_errors = validate_avro_schema(body.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid Avro schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": avro_errors, "schema_format": "avro"},
            )
        try:
            schema_to_check = avro_to_json_schema(body.schema_def)
        except AvroConversionError as e:
            raise BadRequestError(
                f"Failed to convert Avro schema: {e.message}",
                code=ErrorCode.INVALID_SCHEMA,
                details={"path": e.path, "schema_format": "avro"},
            )
    else:
        is_valid, errors = validate_json_schema(body.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid JSON Schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": errors},
            )

    # Get current active contract
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    current_contract = contract_result.scalar_one_or_none()

    # Compute version suggestion
    if current_contract:
        diff_result = diff_schemas(current_contract.schema_def, schema_to_check)
        is_compatible, breaking_changes = check_compatibility(
            current_contract.schema_def,
            schema_to_check,
            current_contract.compatibility_mode,
        )
        return compute_version_suggestion(
            current_contract.version,
            diff_result.change_type,
            is_compatible,
            breaking_changes=[bc.to_dict() for bc in breaking_changes],
        )
    else:
        # First contract for this asset
        return compute_version_suggestion(None, ChangeType.PATCH, True)
