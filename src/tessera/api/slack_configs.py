"""Slack configuration CRUD API endpoints."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead, RequireWrite
from tessera.api.errors import (
    BadRequestError,
    DuplicateError,
    ErrorCode,
    NotFoundError,
)
from tessera.api.pagination import PaginationParams, pagination_params
from tessera.api.rate_limit import limit_read, limit_write
from tessera.api.types import PaginatedResponse
from tessera.db import SlackConfigDB, TeamDB, get_session
from tessera.models.slack_config import (
    SlackConfigCreate,
    SlackConfigResponse,
    SlackConfigUpdate,
    TestMessageResult,
)
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.slack_delivery import deliver_slack_message
from tessera.services.slack_formatter import format_test_message
from tessera.services.webhooks import validate_webhook_url

router = APIRouter()

_E: dict[int, dict[str, str]] = {
    400: {"description": "Bad request — invalid input or parameters"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden — insufficient permissions or wrong team"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflict — duplicate resource"},
    422: {"description": "Validation error — invalid request body"},
}


@router.post(
    "",
    response_model=SlackConfigResponse,
    status_code=201,
    responses={k: _E[k] for k in (400, 401, 403, 404, 409)},
)
@limit_write
async def create_slack_config(
    request: Request,
    body: SlackConfigCreate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> SlackConfigResponse:
    """Configure Slack notifications for a team.

    Requires WRITE scope. Either ``webhook_url`` or ``bot_token`` must be
    provided (not both). The ``channel_id`` must follow Slack's format
    (``C`` followed by alphanumeric characters).
    """
    # Validate team exists
    team_result = await session.execute(
        select(TeamDB).where(TeamDB.id == body.team_id).where(TeamDB.deleted_at.is_(None))
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise NotFoundError(ErrorCode.TEAM_NOT_FOUND, "Team not found")

    # SSRF-validate webhook URL if provided
    if body.webhook_url:
        is_valid, error_msg = await validate_webhook_url(body.webhook_url)
        if not is_valid:
            raise BadRequestError(
                f"Invalid webhook URL: {error_msg}",
                code=ErrorCode.INVALID_SLACK_CONFIG,
            )

    db_config = SlackConfigDB(
        team_id=body.team_id,
        channel_id=body.channel_id,
        channel_name=body.channel_name,
        webhook_url=body.webhook_url,
        bot_token=body.bot_token,
        notify_on=body.notify_on,
        enabled=body.enabled,
    )
    session.add(db_config)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise DuplicateError(
            ErrorCode.DUPLICATE_SLACK_CONFIG,
            f"Slack config already exists for team and channel {body.channel_id}",
        )
    await session.refresh(db_config)

    await audit.log_event(
        session=session,
        entity_type="slack_config",
        entity_id=db_config.id,
        action=AuditAction.SLACK_CONFIG_CREATED,
        payload={
            "team_id": str(body.team_id),
            "channel_id": body.channel_id,
            "notify_on": body.notify_on,
        },
    )

    return SlackConfigResponse.from_db(db_config)


@router.get(
    "",
    responses={k: _E[k] for k in (401, 403)},
)
@limit_read
async def list_slack_configs(
    request: Request,
    auth: Auth,
    team_id: UUID | None = Query(None, description="Filter by team"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    params: PaginationParams = Depends(pagination_params),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[dict[str, object]]:
    """List Slack configs with optional team filter.

    Requires READ scope.
    """
    base_query = select(SlackConfigDB).where(SlackConfigDB.deleted_at.is_(None))

    if team_id is not None:
        base_query = base_query.where(SlackConfigDB.team_id == team_id)
    if enabled is not None:
        base_query = base_query.where(SlackConfigDB.enabled.is_(enabled))

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = (
        base_query.order_by(SlackConfigDB.created_at.desc())
        .limit(params.limit)
        .offset(params.offset)
    )
    result = await session.execute(query)
    configs = list(result.scalars().all())

    results: list[dict[str, object]] = [
        SlackConfigResponse.from_db(c).model_dump() for c in configs
    ]

    return {
        "results": results,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/{config_id}",
    response_model=SlackConfigResponse,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_read
async def get_slack_config(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> SlackConfigResponse:
    """Get a Slack config by ID.

    Requires READ scope.
    """
    result = await session.execute(
        select(SlackConfigDB)
        .where(SlackConfigDB.id == config_id)
        .where(SlackConfigDB.deleted_at.is_(None))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.SLACK_CONFIG_NOT_FOUND, "Slack config not found")

    return SlackConfigResponse.from_db(config)


@router.patch(
    "/{config_id}",
    response_model=SlackConfigResponse,
    responses={k: _E[k] for k in (400, 401, 403, 404)},
)
@limit_write
async def update_slack_config(
    request: Request,
    config_id: UUID,
    body: SlackConfigUpdate,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> SlackConfigResponse:
    """Update a Slack config's channel, notify_on, or enabled flag.

    Requires WRITE scope.
    """
    result = await session.execute(
        select(SlackConfigDB)
        .where(SlackConfigDB.id == config_id)
        .where(SlackConfigDB.deleted_at.is_(None))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.SLACK_CONFIG_NOT_FOUND, "Slack config not found")

    changes: dict[str, object] = {}

    if body.channel_id is not None:
        config.channel_id = body.channel_id
        changes["channel_id"] = body.channel_id
    if body.channel_name is not None:
        config.channel_name = body.channel_name
        changes["channel_name"] = body.channel_name
    if body.webhook_url is not None:
        # SSRF-validate new webhook URL
        is_valid, error_msg = await validate_webhook_url(body.webhook_url)
        if not is_valid:
            raise BadRequestError(
                f"Invalid webhook URL: {error_msg}",
                code=ErrorCode.INVALID_SLACK_CONFIG,
            )
        config.webhook_url = body.webhook_url
        config.bot_token = None  # Clear the other auth method
        changes["webhook_url"] = "updated"
    if body.bot_token is not None:
        config.bot_token = body.bot_token
        config.webhook_url = None  # Clear the other auth method
        changes["bot_token"] = "updated"
    if body.notify_on is not None:
        config.notify_on = body.notify_on
        changes["notify_on"] = body.notify_on
    if body.enabled is not None:
        config.enabled = body.enabled
        changes["enabled"] = body.enabled

    await session.flush()
    await session.refresh(config)

    await audit.log_event(
        session=session,
        entity_type="slack_config",
        entity_id=config_id,
        action=AuditAction.SLACK_CONFIG_UPDATED,
        payload=changes,
    )

    return SlackConfigResponse.from_db(config)


@router.delete(
    "/{config_id}",
    status_code=204,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def delete_slack_config(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete a Slack config.

    Requires WRITE scope. Sets deleted_at rather than removing the row
    so the record remains available for audit purposes.
    """
    result = await session.execute(
        select(SlackConfigDB)
        .where(SlackConfigDB.id == config_id)
        .where(SlackConfigDB.deleted_at.is_(None))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.SLACK_CONFIG_NOT_FOUND, "Slack config not found")

    config.deleted_at = datetime.now(UTC)
    await session.flush()

    await audit.log_event(
        session=session,
        entity_type="slack_config",
        entity_id=config_id,
        action=AuditAction.SLACK_CONFIG_DELETED,
        payload={
            "team_id": str(config.team_id),
            "channel_id": config.channel_id,
        },
    )


@router.post(
    "/{config_id}/test",
    response_model=TestMessageResult,
    responses={k: _E[k] for k in (401, 403, 404)},
)
@limit_write
async def test_slack_config(
    request: Request,
    config_id: UUID,
    auth: Auth,
    _: None = RequireWrite,
    session: AsyncSession = Depends(get_session),
) -> TestMessageResult:
    """Send a test message to verify the Slack configuration works.

    Requires WRITE scope.
    """
    result = await session.execute(
        select(SlackConfigDB)
        .where(SlackConfigDB.id == config_id)
        .where(SlackConfigDB.deleted_at.is_(None))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise NotFoundError(ErrorCode.SLACK_CONFIG_NOT_FOUND, "Slack config not found")

    payload = format_test_message()
    delivery_result = await deliver_slack_message(config, payload)

    await audit.log_event(
        session=session,
        entity_type="slack_config",
        entity_id=config_id,
        action=AuditAction.SLACK_CONFIG_TESTED,
        payload={
            "success": delivery_result.success,
            "error": delivery_result.error,
        },
    )

    return TestMessageResult(
        success=delivery_result.success,
        error=delivery_result.error,
    )
