"""Webhook delivery API endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireAdmin, RequireRead
from tessera.api.rate_limit import limit_admin
from tessera.db.database import get_session
from tessera.db.models import WebhookDeliveryDB
from tessera.models.enums import WebhookDeliveryStatus

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookDeliveryResponse(BaseModel):
    """Response model for webhook delivery."""

    id: UUID
    event_type: str
    payload: dict[str, Any]
    url: str
    status: WebhookDeliveryStatus
    attempts: int
    last_attempt_at: datetime | None
    last_error: str | None
    last_status_code: int | None
    created_at: datetime
    delivered_at: datetime | None


class WebhookDeliveriesListResponse(BaseModel):
    """Response model for list of webhook deliveries."""

    results: list[WebhookDeliveryResponse]
    total: int


@router.get("/deliveries", response_model=WebhookDeliveriesListResponse)
@limit_admin
async def list_deliveries(
    request: Request,
    auth: Auth,
    status: WebhookDeliveryStatus | None = Query(None, description="Filter by status"),
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: None = RequireAdmin,
    __: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> WebhookDeliveriesListResponse:
    """List webhook deliveries with optional filtering.

    Requires admin and read scope.
    """
    query = select(WebhookDeliveryDB)

    if status:
        query = query.where(WebhookDeliveryDB.status == status)
    if event_type:
        query = query.where(WebhookDeliveryDB.event_type == event_type)

    # Get total count
    count_query = select(WebhookDeliveryDB.id)
    if status:
        count_query = count_query.where(WebhookDeliveryDB.status == status)
    if event_type:
        count_query = count_query.where(WebhookDeliveryDB.event_type == event_type)
    count_result = await session.execute(count_query)
    total = len(count_result.all())

    # Get paginated results
    query = query.order_by(WebhookDeliveryDB.created_at.desc())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    deliveries = result.scalars().all()

    return WebhookDeliveriesListResponse(
        results=[
            WebhookDeliveryResponse(
                id=d.id,
                event_type=d.event_type,
                payload=d.payload,
                url=d.url,
                status=d.status,
                attempts=d.attempts,
                last_attempt_at=d.last_attempt_at,
                last_error=d.last_error,
                last_status_code=d.last_status_code,
                created_at=d.created_at,
                delivered_at=d.delivered_at,
            )
            for d in deliveries
        ],
        total=total,
    )


@router.get("/deliveries/{delivery_id}", response_model=WebhookDeliveryResponse)
@limit_admin
async def get_delivery(
    request: Request,
    delivery_id: UUID,
    auth: Auth,
    _: None = RequireAdmin,
    __: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> WebhookDeliveryResponse:
    """Get a specific webhook delivery by ID.

    Requires admin and read scope.
    """
    result = await session.execute(
        select(WebhookDeliveryDB).where(WebhookDeliveryDB.id == delivery_id)
    )
    delivery = result.scalar_one_or_none()
    if not delivery:
        from tessera.api.errors import ErrorCode, NotFoundError

        raise NotFoundError(
            code=ErrorCode.NOT_FOUND,
            message=f"Webhook delivery with ID '{delivery_id}' not found",
        )

    return WebhookDeliveryResponse(
        id=delivery.id,
        event_type=delivery.event_type,
        payload=delivery.payload,
        url=delivery.url,
        status=delivery.status,
        attempts=delivery.attempts,
        last_attempt_at=delivery.last_attempt_at,
        last_error=delivery.last_error,
        last_status_code=delivery.last_status_code,
        created_at=delivery.created_at,
        delivered_at=delivery.delivered_at,
    )
