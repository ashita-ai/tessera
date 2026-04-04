"""Impact preview endpoint for pre-flight schema change analysis.

Provides a single API call for agents to answer: "what would break if I
made this change?" Returns breaking/non-breaking changes, affected
consumers, downstream lineage, version suggestion, and migration
suggestions.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.api.errors import BadRequestError, ErrorCode, ForbiddenError, NotFoundError
from tessera.api.rate_limit import limit_expensive, limit_read
from tessera.db.database import get_session
from tessera.db.models import AssetDB, ContractDB
from tessera.models.enums import APIKeyScope, CompatibilityMode, ContractStatus
from tessera.services.impact_preview import compute_impact_preview
from tessera.services.schema_validator import validate_json_schema

router = APIRouter()


class ImpactPreviewRequest(BaseModel):
    """Request body for the impact preview endpoint."""

    proposed_schema: dict[str, Any] = Field(..., description="The proposed new JSON Schema")
    proposed_guarantees: dict[str, Any] | None = Field(
        None, description="Optional proposed new guarantees"
    )
    compatibility_mode_override: CompatibilityMode | None = Field(
        None,
        description="Override the contract's compatibility mode for this preview",
    )


class ImpactPreviewResponse(BaseModel):
    """Response from the impact preview endpoint."""

    is_breaking: bool
    breaking_changes: list[dict[str, Any]]
    non_breaking_changes: list[dict[str, Any]]
    guarantee_changes: list[dict[str, Any]]
    affected_consumers: list[dict[str, Any]]
    affected_downstream: list[dict[str, Any]]
    unconfirmed_consumers: list[dict[str, Any]]
    suggested_version: str
    version_reason: str
    would_create_proposal: bool
    migration_suggestions: list[dict[str, Any]]
    current_version: str | None
    compatibility_mode: str


@router.post(
    "/{asset_id}/impact-preview",
    response_model=ImpactPreviewResponse,
)
@limit_read
@limit_expensive
async def impact_preview(
    request: Request,
    asset_id: UUID,
    body: ImpactPreviewRequest,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> ImpactPreviewResponse:
    """Preview the impact of a proposed schema change.

    Returns breaking/non-breaking changes, affected consumers and downstream
    assets, a suggested version bump, and migration suggestions for breaking
    changes. This is a read-only operation.
    """
    # Validate proposed schema
    is_valid, errors = validate_json_schema(body.proposed_schema)
    if not is_valid:
        raise BadRequestError(
            "Invalid proposed_schema: "
            f"{'; '.join(errors) if errors else 'Schema validation failed'}",
            code=ErrorCode.INVALID_SCHEMA,
        )

    # Load asset
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Authorization: must own the asset or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        raise ForbiddenError(
            "Cannot preview impact for assets owned by other teams",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Load current active contract
    contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        raise NotFoundError(
            ErrorCode.CONTRACT_NOT_FOUND,
            "Asset has no published contracts",
        )

    # Compute impact preview
    result = await compute_impact_preview(
        session=session,
        asset=asset,
        contract=contract,
        proposed_schema=body.proposed_schema,
        proposed_guarantees=body.proposed_guarantees,
        compatibility_mode_override=body.compatibility_mode_override,
    )

    return ImpactPreviewResponse(**result.to_dict())
