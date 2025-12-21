"""Audit trail query API endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.errors import ErrorCode, NotFoundError
from tessera.db.database import get_session
from tessera.db.models import AuditEventDB

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventResponse(BaseModel):
    """Response model for audit event."""

    id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    actor_id: UUID | None
    payload: dict[str, Any]
    occurred_at: datetime


class AuditEventsListResponse(BaseModel):
    """Response model for list of audit events."""

    results: list[AuditEventResponse]
    total: int
    limit: int
    offset: int


def _to_response(event: AuditEventDB) -> AuditEventResponse:
    """Convert database model to response model."""
    return AuditEventResponse(
        id=event.id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        action=event.action,
        actor_id=event.actor_id,
        payload=event.payload,
        occurred_at=event.occurred_at,
    )


@router.get("/events", response_model=AuditEventsListResponse)
async def list_audit_events(
    entity_type: str | None = Query(None, description="Filter by entity type"),
    entity_id: UUID | None = Query(None, description="Filter by entity ID"),
    action: str | None = Query(None, description="Filter by action"),
    actor_id: UUID | None = Query(None, description="Filter by actor ID"),
    from_date: datetime | None = Query(None, alias="from", description="Start datetime"),
    to_date: datetime | None = Query(None, alias="to", description="End datetime"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AuditEventsListResponse:
    """List audit events with optional filtering."""
    query = select(AuditEventDB)
    count_query = select(func.count(AuditEventDB.id))

    # Apply filters
    if entity_type:
        query = query.where(AuditEventDB.entity_type == entity_type)
        count_query = count_query.where(AuditEventDB.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEventDB.entity_id == entity_id)
        count_query = count_query.where(AuditEventDB.entity_id == entity_id)
    if action:
        query = query.where(AuditEventDB.action == action)
        count_query = count_query.where(AuditEventDB.action == action)
    if actor_id:
        query = query.where(AuditEventDB.actor_id == actor_id)
        count_query = count_query.where(AuditEventDB.actor_id == actor_id)
    if from_date:
        query = query.where(AuditEventDB.occurred_at >= from_date)
        count_query = count_query.where(AuditEventDB.occurred_at >= from_date)
    if to_date:
        query = query.where(AuditEventDB.occurred_at <= to_date)
        count_query = count_query.where(AuditEventDB.occurred_at <= to_date)

    # Get total count
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Get paginated results
    query = query.order_by(AuditEventDB.occurred_at.desc())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    events = result.scalars().all()

    return AuditEventsListResponse(
        results=[_to_response(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/events/{event_id}", response_model=AuditEventResponse)
async def get_audit_event(
    event_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AuditEventResponse:
    """Get a specific audit event by ID."""
    result = await session.execute(
        select(AuditEventDB).where(AuditEventDB.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise NotFoundError(
            code=ErrorCode.NOT_FOUND,
            message=f"Audit event with ID '{event_id}' not found",
        )

    return _to_response(event)


@router.get(
    "/entities/{entity_type}/{entity_id}/history",
    response_model=AuditEventsListResponse,
)
async def get_entity_history(
    entity_type: str,
    entity_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AuditEventsListResponse:
    """Get audit history for a specific entity."""
    # Get total count for this entity
    count_query = select(func.count(AuditEventDB.id)).where(
        AuditEventDB.entity_type == entity_type,
        AuditEventDB.entity_id == entity_id,
    )
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Get paginated history
    query = (
        select(AuditEventDB)
        .where(
            AuditEventDB.entity_type == entity_type,
            AuditEventDB.entity_id == entity_id,
        )
        .order_by(AuditEventDB.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    events = result.scalars().all()

    return AuditEventsListResponse(
        results=[_to_response(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )
