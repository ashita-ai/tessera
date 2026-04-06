"""API compatibility check endpoint.

Accepts raw API spec content (OpenAPI, protobuf, or GraphQL), parses it,
and checks each extracted schema against the corresponding active contract
in Tessera.  This powers the MCP ``tessera_check_api_compat`` tool and
CI pre-commit checks.
"""

from enum import StrEnum
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, NotFoundError
from tessera.api.rate_limit import limit_expensive, limit_read
from tessera.db.database import get_session
from tessera.db.models import AssetDB, ContractDB
from tessera.models.enums import CompatibilityMode, ContractStatus
from tessera.services import diff_schemas

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SpecFormat(StrEnum):
    """Supported API specification formats."""

    OPENAPI = "openapi"
    PROTOBUF = "protobuf"
    GRAPHQL = "graphql"


class CompatCheckRequest(BaseModel):
    """Request body for the compatibility check endpoint."""

    spec_content: str = Field(
        ...,
        min_length=1,
        max_length=5_000_000,
        description=(
            "The raw API specification content.  For OpenAPI pass YAML or JSON; "
            "for protobuf pass the .proto file text; for GraphQL pass the SDL string."
        ),
    )
    spec_format: SpecFormat = Field(..., description="Specification format")
    asset_fqn: str | None = Field(
        None,
        description=(
            "Fully qualified name of the Tessera asset to check against.  "
            "When omitted, all parsed endpoints are matched by auto-generated FQN."
        ),
    )
    service_name: str | None = Field(
        None,
        description="Service name — used for FQN generation when asset_fqn is not set.",
    )
    environment: str = Field(
        "production",
        description="Environment to match assets in",
    )


class CompatCheckEndpointResult(BaseModel):
    """Compatibility result for a single endpoint/operation."""

    fqn: str
    is_breaking: bool
    change_type: str
    breaking_changes: list[dict[str, Any]]
    non_breaking_changes: list[dict[str, Any]]
    current_version: str | None = None
    compatibility_mode: str | None = None


class CompatCheckResponse(BaseModel):
    """Aggregated response from the compatibility check endpoint."""

    is_breaking: bool = Field(
        description="True if any endpoint has breaking changes",
    )
    spec_format: str
    total_endpoints: int
    checked: int
    new_endpoints: int
    results: list[CompatCheckEndpointResult]
    parse_errors: list[str]


# ---------------------------------------------------------------------------
# Spec parsers — thin wrappers that normalise to (fqn, schema) pairs
# ---------------------------------------------------------------------------


def _parse_openapi(
    raw: str,
    service_name: str | None,
    environment: str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Parse OpenAPI and return ``[(fqn, combined_schema), ...]``."""
    from tessera.services.openapi import parse_openapi

    try:
        spec_dict = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [], [f"YAML parse error: {exc}"]

    if not isinstance(spec_dict, dict):
        return [], ["Spec content must be a YAML/JSON object"]

    result = parse_openapi(spec_dict)
    if result.errors:
        return [], result.errors

    api_title = service_name or result.title or "api"
    pairs: list[tuple[str, dict[str, Any]]] = []
    for ep in result.endpoints:
        fqn = f"{environment}.{api_title}.{ep.method.upper()}_{ep.path}".replace("/", "_")
        pairs.append((fqn, ep.combined_schema))
    return pairs, []


def _parse_graphql(
    raw: str,
    service_name: str | None,
    environment: str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Parse GraphQL SDL/introspection and return ``[(fqn, schema), ...]``."""
    import json

    from tessera.services.graphql import parse_graphql_introspection

    # Accept SDL or JSON introspection
    try:
        spec_dict = json.loads(raw)
    except json.JSONDecodeError:
        return [], ["GraphQL spec must be a JSON introspection result"]

    result = parse_graphql_introspection(spec_dict)
    if result.errors:
        return [], result.errors

    schema_name = service_name or result.schema_name or "graphql"
    pairs: list[tuple[str, dict[str, Any]]] = []
    for op in result.operations:
        fqn = f"{environment}.{schema_name}.{op.operation_type}_{op.name}"
        pairs.append((fqn, op.combined_schema))
    return pairs, []


def _parse_protobuf(
    raw: str,
    service_name: str | None,
    environment: str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Parse a .proto file and return ``[(fqn, schema), ...]``."""
    from tessera.services.grpc import parse_proto

    result = parse_proto(raw)
    if result.errors:
        return [], result.errors

    pkg = service_name or result.package or "grpc"
    pairs: list[tuple[str, dict[str, Any]]] = []
    for rpc in result.rpc_methods:
        fqn = f"{environment}.{pkg}.{rpc.service_name}_{rpc.method_name}"
        pairs.append((fqn, rpc.combined_schema))
    return pairs, []


_PARSERS = {
    SpecFormat.OPENAPI: _parse_openapi,
    SpecFormat.GRAPHQL: _parse_graphql,
    SpecFormat.PROTOBUF: _parse_protobuf,
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/check-compat",
    response_model=CompatCheckResponse,
    tags=["compatibility"],
)
@limit_read
@limit_expensive
async def check_api_compat(
    request: Request,
    body: CompatCheckRequest,
    auth: Auth,
    compatibility_mode_override: CompatibilityMode | None = Query(
        None,
        description="Override the contract's compatibility mode for this check",
    ),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> CompatCheckResponse:
    """Check compatibility of a raw API spec against active Tessera contracts.

    Parses the spec, finds matching Tessera assets by FQN, and diffs each
    endpoint's schema against the active contract.  Returns per-endpoint
    results so the caller knows exactly which operations would break.

    This is a read-only operation — nothing is published or modified.
    """
    parser = _PARSERS.get(body.spec_format)
    if parser is None:
        raise BadRequestError(
            f"Unsupported spec format: {body.spec_format}",
            code=ErrorCode.INVALID_INPUT,
        )

    pairs, parse_errors = parser(body.spec_content, body.service_name, body.environment)
    if parse_errors and not pairs:
        raise BadRequestError(
            f"Failed to parse {body.spec_format} spec: {'; '.join(parse_errors)}",
            code=ErrorCode.INVALID_SCHEMA,
            details={"parse_errors": parse_errors},
        )

    # If caller specified a single asset_fqn, narrow to that
    if body.asset_fqn:
        asset_result = await session.execute(
            select(AssetDB)
            .where(AssetDB.fqn == body.asset_fqn)
            .where(AssetDB.environment == body.environment)
            .where(AssetDB.deleted_at.is_(None))
        )
        asset = asset_result.scalar_one_or_none()
        if not asset:
            raise NotFoundError(
                ErrorCode.ASSET_NOT_FOUND,
                f"Asset '{body.asset_fqn}' not found in environment '{body.environment}'",
            )
        # Use the first parsed schema against this specific asset
        if not pairs:
            raise BadRequestError(
                "No endpoints/operations found in spec",
                code=ErrorCode.INVALID_INPUT,
            )
        # Use the first parsed schema against this specific asset
        fqn_asset_map = {body.asset_fqn: asset}
        pairs = [(body.asset_fqn, pairs[0][1])]
    else:
        # Match each parsed FQN to an existing asset
        fqns = [fqn for fqn, _ in pairs]
        if fqns:
            asset_query = await session.execute(
                select(AssetDB)
                .where(AssetDB.fqn.in_(fqns))
                .where(AssetDB.environment == body.environment)
                .where(AssetDB.deleted_at.is_(None))
            )
            fqn_asset_map = {a.fqn: a for a in asset_query.scalars().all()}
        else:
            fqn_asset_map = {}

    # For each matched asset, load the active contract and diff
    results: list[CompatCheckEndpointResult] = []
    new_endpoints = 0

    for fqn, proposed_schema in pairs:
        asset = fqn_asset_map.get(fqn)
        if not asset:
            new_endpoints += 1
            results.append(
                CompatCheckEndpointResult(
                    fqn=fqn,
                    is_breaking=False,
                    change_type="new",
                    breaking_changes=[],
                    non_breaking_changes=[],
                )
            )
            continue

        contract_result = await session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == asset.id)
            .where(ContractDB.status == ContractStatus.ACTIVE)
            .order_by(ContractDB.published_at.desc())
            .limit(1)
        )
        contract = contract_result.scalar_one_or_none()
        if not contract:
            new_endpoints += 1
            results.append(
                CompatCheckEndpointResult(
                    fqn=fqn,
                    is_breaking=False,
                    change_type="new",
                    breaking_changes=[],
                    non_breaking_changes=[],
                )
            )
            continue

        mode = compatibility_mode_override or contract.compatibility_mode
        diff_result = diff_schemas(contract.schema_def, proposed_schema)
        breaking_changes = diff_result.breaking_for_mode(mode)

        results.append(
            CompatCheckEndpointResult(
                fqn=fqn,
                is_breaking=len(breaking_changes) > 0,
                change_type=str(diff_result.change_type),
                breaking_changes=[bc.to_dict() for bc in breaking_changes],
                non_breaking_changes=[
                    c.to_dict() for c in diff_result.changes if c not in breaking_changes
                ],
                current_version=contract.version,
                compatibility_mode=str(mode),
            )
        )

    any_breaking = any(r.is_breaking for r in results)

    return CompatCheckResponse(
        is_breaking=any_breaking,
        spec_format=body.spec_format,
        total_endpoints=len(pairs),
        checked=len(pairs) - new_endpoints,
        new_endpoints=new_endpoints,
        results=results,
        parse_errors=parse_errors,
    )
