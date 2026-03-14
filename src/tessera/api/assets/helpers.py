"""Shared utilities and constants for asset endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.types import ContractPublishResponse
from tessera.db import AssetDB, AuditRunDB, TeamDB
from tessera.models import Contract, Proposal
from tessera.models.enums import AuditRunStatus, ChangeType, SchemaFormat
from tessera.services.contract_publisher import SinglePublishResult
from tessera.services.versioning import parse_semver

# Standard error response descriptions shared across endpoints.
_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    412: {"description": "Precondition failed — passing audit run required"},
    422: {"description": "Validation error — invalid request body"},
}


def _apply_asset_search_filters(
    query: Select[Any],
    q: str,
    owner: UUID | None,
    environment: str | None,
) -> Select[Any]:
    """Apply common asset search filters to a query."""
    filtered = query.where(AssetDB.fqn.ilike(f"%{q}%")).where(AssetDB.deleted_at.is_(None))
    if owner:
        filtered = filtered.where(AssetDB.owner_team_id == owner)
    if environment:
        filtered = filtered.where(AssetDB.environment == environment)
    return filtered


def validate_version_for_change_type(
    user_version: str,
    current_version: str,
    suggested_change_type: ChangeType,
) -> tuple[bool, str | None]:
    """Validate that user-provided version matches the detected change type.

    Args:
        user_version: The version provided by the user
        current_version: The current contract version
        suggested_change_type: The change type detected from schema diff

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        user_major, user_minor, user_patch = parse_semver(user_version)
        curr_major, curr_minor, curr_patch = parse_semver(current_version)
    except ValueError as e:
        return False, str(e)

    # Version must be greater than current
    user_tuple = (user_major, user_minor, user_patch)
    curr_tuple = (curr_major, curr_minor, curr_patch)
    if user_tuple <= curr_tuple:
        return (
            False,
            f"Version {user_version} must be greater than current version {current_version}",
        )

    # For major changes, major version must increase
    if suggested_change_type == ChangeType.MAJOR:
        if user_major <= curr_major:
            return False, (
                f"Breaking change requires major version bump. "
                f"Expected {curr_major + 1}.0.0 or higher, got {user_version}"
            )

    # For minor changes, version must increase appropriately
    # (major bump is also acceptable for minor changes)
    if suggested_change_type == ChangeType.MINOR:
        if user_major == curr_major and user_minor <= curr_minor:
            return False, (
                f"Backward-compatible additions require at least a minor version bump. "
                f"Expected {curr_major}.{curr_minor + 1}.0 or higher, got {user_version}"
            )

    return True, None


async def _get_team_name(session: AsyncSession, team_id: UUID) -> str:
    """Get team name by ID, returns 'unknown' if not found."""
    result = await session.execute(select(TeamDB.name).where(TeamDB.id == team_id))
    name = result.scalar_one_or_none()
    return name if name else "unknown"


async def _get_last_audit_status(
    session: AsyncSession, asset_id: UUID
) -> tuple[AuditRunStatus | None, int, datetime | None]:
    """Get the most recent audit run status for an asset.

    Returns (status, failed_count, run_at) or (None, 0, None) if no audits exist.
    """
    from sqlalchemy import desc

    result = await session.execute(
        select(AuditRunDB)
        .where(AuditRunDB.asset_id == asset_id)
        .order_by(desc(AuditRunDB.run_at))
        .limit(1)
    )
    audit_run = result.scalar_one_or_none()
    if not audit_run:
        return None, 0, None
    return audit_run.status, audit_run.guarantees_failed, audit_run.run_at


def _build_publish_response(
    result: SinglePublishResult,
    original_format: SchemaFormat,
) -> ContractPublishResponse:
    """Convert a SinglePublishResult from the workflow into the API response format.

    Translates the workflow's dataclass result into the ContractPublishResponse
    TypedDict that the API endpoint returns. Only includes fields that have
    meaningful values to keep the response clean.
    """
    response: ContractPublishResponse = {"action": str(result.action)}

    if result.contract:
        response["contract"] = Contract.model_validate(result.contract).model_dump()

    if result.proposal:
        response["proposal"] = Proposal.model_validate(result.proposal).model_dump()

    if result.change_type is not None:
        response["change_type"] = str(result.change_type)

    if result.breaking_changes:
        response["breaking_changes"] = result.breaking_changes

    if result.message:
        response["message"] = result.message

    if result.warning:
        response["warning"] = result.warning

    if result.version_auto_generated:
        response["version_auto_generated"] = True

    if result.schema_converted_from:
        response["schema_converted_from"] = result.schema_converted_from
    elif original_format == SchemaFormat.AVRO:
        response["schema_converted_from"] = "avro"

    if result.audit_warning:
        response["audit_warning"] = result.audit_warning

    return response
