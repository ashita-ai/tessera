"""Contract publishing endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
)
from tessera.api.rate_limit import limit_write
from tessera.api.types import ContractPublishResponse
from tessera.db import AssetDB, ContractDB, TeamDB, get_session
from tessera.models import ContractCreate
from tessera.models.enums import (
    APIKeyScope,
    AuditRunStatus,
    ChangeType,
    ContractStatus,
    SchemaFormat,
    SemverMode,
)
from tessera.services import check_compatibility, diff_schemas, validate_json_schema
from tessera.services.avro import (
    AvroConversionError,
    avro_to_json_schema,
    validate_avro_schema,
)
from tessera.services.contract_publisher import (
    ContractPublishingWorkflow,
    PublishAction,
)
from tessera.services.versioning import compute_version_suggestion

from .helpers import (
    _E,
    _build_publish_response,
    _get_last_audit_status,
    _get_team_name,
    validate_version_for_change_type,
)

router = APIRouter()


@router.post(
    "/{asset_id}/contracts",
    status_code=201,
    response_model=None,
    responses={k: _E[k] for k in (400, 401, 403, 404, 409, 412)},
)
@limit_write
async def create_contract(
    request: Request,
    auth: Auth,
    asset_id: UUID,
    contract: ContractCreate,
    published_by: UUID = Query(..., description="Team ID of the publisher"),
    published_by_user_id: UUID | None = Query(None, description="User ID who published"),
    force: bool = Query(False, description="Force publish even if breaking (creates audit trail)"),
    force_reason: str | None = Query(
        None,
        description="Required when force=True. Explains why the breaking change is being forced.",
        min_length=10,
        max_length=500,
    ),
    require_audit_pass: bool = Query(
        False, description="Require most recent audit to pass before publishing"
    ),
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> ContractPublishResponse | JSONResponse:
    """Publish a new contract for an asset.

    Requires write scope. Delegates to ContractPublishingWorkflow for the actual
    publishing logic, which uses FOR UPDATE locking to prevent concurrent publish
    races.

    Behavior:
    - If no active contract exists: auto-publish (first contract)
    - If change is compatible: auto-publish, deprecate old contract
    - If change is breaking: create a Proposal for consumer acknowledgment
    - If force=True: publish anyway but log the override
    - If require_audit_pass=True: reject if most recent audit failed

    WAP (Write-Audit-Publish) enforcement:
    - Set require_audit_pass=True to gate publishing on passing audits
    - Returns 412 Precondition Failed if no audits exist or last audit failed
    - Without this flag, audit failures add a warning to the response

    Returns either a Contract (if published) or a Proposal (if breaking).
    """
    # Require a reason when force-publishing
    if force and not force_reason:
        raise BadRequestError(
            "force_reason is required when force=True. "
            "Explain why this breaking change must bypass consumer acknowledgment.",
            code=ErrorCode.INVALID_INPUT,
        )

    # Verify asset exists and is not soft-deleted
    asset_result = await session.execute(
        select(AssetDB).where(AssetDB.id == asset_id).where(AssetDB.deleted_at.is_(None))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundError(ErrorCode.ASSET_NOT_FOUND, "Asset not found")

    # Check audit status for WAP enforcement
    audit_status, audit_failed, audit_run_at = await _get_last_audit_status(session, asset_id)
    audit_warning: str | None = None

    if require_audit_pass:
        if audit_status is None:
            raise PreconditionFailedError(
                ErrorCode.AUDIT_REQUIRED,
                "No audit runs found. Run audits before publishing with require_audit_pass=True.",
            )
        if audit_status != AuditRunStatus.PASSED:
            raise PreconditionFailedError(
                ErrorCode.AUDIT_FAILED,
                f"Most recent audit {audit_status.value}. "
                "Cannot publish with require_audit_pass=True.",
                details={
                    "audit_status": audit_status.value,
                    "guarantees_failed": audit_failed,
                    "audit_run_at": audit_run_at.isoformat() if audit_run_at else None,
                },
            )
    elif audit_status and audit_status != AuditRunStatus.PASSED:
        # Not enforcing, but add a warning to the response
        audit_warning = (
            f"Warning: Most recent audit {audit_status.value} "
            f"with {audit_failed} guarantee(s) failing"
        )

    # Resource-level auth: must own the asset's team or be admin
    if asset.owner_team_id != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        asset_team_name = await _get_team_name(session, asset.owner_team_id)
        raise ForbiddenError(
            f"Cannot publish contract for asset '{asset.fqn}' owned by '{asset_team_name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to publish contracts for other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Verify publisher team exists
    team_result = await session.execute(select(TeamDB).where(TeamDB.id == published_by))
    publisher_team = team_result.scalar_one_or_none()
    if not publisher_team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Publisher team not found")

    # Resource-level auth: published_by must match auth.team_id or be admin
    if published_by != auth.team_id and not auth.has_scope(APIKeyScope.ADMIN):
        user_team_name = await _get_team_name(session, auth.team_id)
        raise ForbiddenError(
            f"Cannot publish contract on behalf of team '{publisher_team.name}'. "
            f"Your team is '{user_team_name}'. "
            "Use an admin API key to publish on behalf of other teams.",
            code=ErrorCode.UNAUTHORIZED_TEAM,
        )

    # Validate and normalize schema based on format
    schema_to_store = contract.schema_def
    original_format = contract.schema_format

    if contract.schema_format == SchemaFormat.AVRO:
        is_valid, avro_errors = validate_avro_schema(contract.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid Avro schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": avro_errors, "schema_format": "avro"},
            )
        try:
            schema_to_store = avro_to_json_schema(contract.schema_def)
        except AvroConversionError as e:
            raise BadRequestError(
                f"Failed to convert Avro schema: {e.message}",
                code=ErrorCode.INVALID_SCHEMA,
                details={"path": e.path, "schema_format": "avro"},
            )
    else:
        is_valid, errors = validate_json_schema(contract.schema_def)
        if not is_valid:
            raise BadRequestError(
                "Invalid JSON Schema",
                code=ErrorCode.INVALID_SCHEMA,
                details={"errors": errors},
            )

    # --- Pre-workflow validation (without FOR UPDATE lock) ---
    # Compute version suggestion for SUGGEST/ENFORCE mode validation.
    # The workflow will re-compute under lock for the actual publish decision.
    pre_contract_result = await session.execute(
        select(ContractDB)
        .where(ContractDB.asset_id == asset_id)
        .where(ContractDB.status == ContractStatus.ACTIVE)
        .order_by(ContractDB.published_at.desc())
        .limit(1)
    )
    pre_current_contract = pre_contract_result.scalar_one_or_none()

    if pre_current_contract:
        pre_diff = diff_schemas(pre_current_contract.schema_def, schema_to_store)
        pre_is_compatible, pre_breaks = check_compatibility(
            pre_current_contract.schema_def,
            schema_to_store,
            pre_current_contract.compatibility_mode,
        )
        version_suggestion = compute_version_suggestion(
            pre_current_contract.version,
            pre_diff.change_type,
            pre_is_compatible,
            breaking_changes=[bc.to_dict() for bc in pre_breaks],
        )
    else:
        version_suggestion = compute_version_suggestion(None, ChangeType.PATCH, True)

    # Handle version based on semver_mode
    semver_mode = asset.semver_mode
    version_for_workflow: str | None = None

    if contract.version is None:
        # No version provided by user
        if semver_mode == SemverMode.SUGGEST:
            # Return suggestion without publishing (200 since nothing created).
            # This is handled before the workflow to avoid acquiring a FOR UPDATE
            # lock for a read-only operation.
            msg = (
                "Version not provided. Please review the suggested version "
                "and re-submit with an explicit version."
            )
            return JSONResponse(
                status_code=200,
                content={
                    "action": "version_required",
                    "message": msg,
                    "version_suggestion": version_suggestion.model_dump(),
                },
            )
        # AUTO mode: pass None to workflow, which will auto-generate under lock
        version_for_workflow = None
    else:
        # User provided a version
        version_for_workflow = contract.version

        # In ENFORCE mode, validate the user's version matches the change type
        if semver_mode == SemverMode.ENFORCE and pre_current_contract:
            is_valid_version, error_msg = validate_version_for_change_type(
                version_for_workflow,
                pre_current_contract.version,
                version_suggestion.change_type,
            )
            if not is_valid_version:
                raise BadRequestError(
                    error_msg or "Invalid version for change type",
                    code=ErrorCode.INVALID_VERSION,
                    details={
                        "provided_version": version_for_workflow,
                        "version_suggestion": version_suggestion.model_dump(),
                    },
                )

        # Check if version already exists (fast failure before acquiring lock)
        existing_version_result = await session.execute(
            select(ContractDB)
            .where(ContractDB.asset_id == asset_id)
            .where(ContractDB.version == version_for_workflow)
        )
        existing_version = existing_version_result.scalar_one_or_none()
        if existing_version:
            raise DuplicateError(
                ErrorCode.VERSION_EXISTS,
                f"Contract version {version_for_workflow} already exists for this asset",
                details={"existing_contract_id": str(existing_version.id)},
            )

    # --- Delegate to ContractPublishingWorkflow ---
    # The workflow handles: FOR UPDATE locking, version computation (for AUTO mode),
    # schema diffing, compatibility checking, contract creation, deprecation of old
    # contracts, guarantee change logging, proposal creation, and notifications.
    workflow = ContractPublishingWorkflow(
        session=session,
        asset=asset,
        publisher_team=publisher_team,
        schema_def=schema_to_store,
        schema_format=original_format,
        compatibility_mode=contract.compatibility_mode,
        version=version_for_workflow,
        published_by=published_by,
        published_by_user_id=published_by_user_id,
        guarantees=contract.guarantees.model_dump() if contract.guarantees else None,
        force=force,
        force_reason=force_reason,
        audit_warning=audit_warning,
        field_descriptions=contract.field_descriptions,
        field_tags=contract.field_tags,
    )
    try:
        result = await workflow.execute()
    except IntegrityError as exc:
        # Concurrent version conflict caught by DB unique constraint on
        # (asset_id, version). Convert to a clean 409 instead of 500.
        raise DuplicateError(
            ErrorCode.VERSION_EXISTS,
            f"Contract version {version_for_workflow} already exists for this asset. "
            "A concurrent publish may have created it.",
        ) from exc

    # Handle duplicate proposal: the workflow returns PROPOSAL_CREATED with the
    # existing proposal when one already exists. Convert to the expected HTTP error.
    if (
        result.action == PublishAction.PROPOSAL_CREATED
        and result.proposal is not None
        and result.message
        and "already has pending proposal" in result.message
    ):
        raise DuplicateError(
            ErrorCode.DUPLICATE_PROPOSAL,
            f"Asset already has a pending proposal (ID: {result.proposal.id}). "
            "Resolve the existing proposal before creating a new one.",
        )

    return _build_publish_response(result, original_format)
