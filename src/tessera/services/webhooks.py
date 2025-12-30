"""Webhook delivery service."""

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select

from tessera.config import settings
from tessera.db.database import get_async_session_maker
from tessera.db.models import WebhookDeliveryDB
from tessera.models.enums import WebhookDeliveryStatus
from tessera.models.webhook import (
    AcknowledgmentPayload,
    BreakingChange,
    ContractPublishedPayload,
    ImpactedConsumer,
    ProposalCreatedPayload,
    ProposalStatusPayload,
    WebhookEvent,
    WebhookEventType,
)

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [1, 5, 30]  # seconds between retries

# Backpressure: limit concurrent webhook deliveries to prevent resource exhaustion
MAX_CONCURRENT_WEBHOOKS = 10
_webhook_semaphore: asyncio.Semaphore | None = None


def _get_webhook_semaphore() -> asyncio.Semaphore:
    """Get or create the webhook semaphore for the current event loop."""
    global _webhook_semaphore
    if _webhook_semaphore is None:
        _webhook_semaphore = asyncio.Semaphore(MAX_CONCURRENT_WEBHOOKS)
    return _webhook_semaphore


def _is_blocked_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP should be blocked for SSRF protection."""
    return not ip_obj.is_global


async def validate_webhook_url(url: str) -> tuple[bool, str]:
    """Validate a webhook URL for SSRF protection.

    Uses async DNS resolution to avoid blocking the event loop.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    try:
        parsed = urlparse(url)

        # Require HTTPS in production
        if settings.environment == "production" and parsed.scheme != "https":
            return False, "Webhook URL must use HTTPS in production"

        # Must have a valid scheme
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme: {parsed.scheme}"

        # Must have a hostname
        if not parsed.hostname:
            return False, "Webhook URL must have a hostname"

        # Optional allowlist check (exact match or subdomain)
        allowed_domains = getattr(settings, "webhook_allowed_domains", [])
        if not isinstance(allowed_domains, list):
            allowed_domains = []
        if allowed_domains:
            hostname = parsed.hostname.lower().rstrip(".")
            allowed = [d.lower().rstrip(".") for d in allowed_domains]
            if not any(hostname == d or hostname.endswith(f".{d}") for d in allowed):
                return False, "Webhook URL hostname is not in allowlist"

        # Resolve hostname and check for blocked IPs (async to not block event loop)
        try:
            loop = asyncio.get_running_loop()
            # Use getaddrinfo which returns all addresses (IPv4 and IPv6)
            # Wrap in wait_for to prevent slow DNS from stalling webhook delivery
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    family=socket.AF_UNSPEC,
                ),
                timeout=5.0,  # 5 second DNS timeout
            )

            for family, _, _, _, sockaddr in addrinfo:
                ip_str = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    if _is_blocked_ip(ip_obj):
                        logger.warning(
                            "Webhook URL %s resolves to non-global IP %s",
                            url,
                            ip_obj,
                        )
                        return False, "Webhook URL resolves to blocked IP range"
                except ValueError:
                    # Skip if not a valid IP (shouldn't happen)
                    continue
        except TimeoutError:
            # DNS resolution timed out
            logger.warning("DNS resolution timed out for webhook hostname: %s", parsed.hostname)
            return False, "DNS resolution timed out"
        except socket.gaierror:
            # DNS resolution failed - allow the request but log it
            # The actual delivery will fail with a clearer error
            logger.warning("Could not resolve webhook hostname: %s", parsed.hostname)

        return True, ""
    except Exception as e:
        return False, f"Invalid URL: {e}"


def _sign_payload(payload: str, secret: str) -> str:
    """Sign a payload with HMAC-SHA256."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_webhook_headers(event: WebhookEvent, payload: str) -> dict[str, str]:
    """Build webhook delivery headers, including signature if configured."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Tessera-Event": event.event.value,
        "X-Tessera-Timestamp": event.timestamp.isoformat(),
    }

    if settings.webhook_secret:
        signature = _sign_payload(payload, settings.webhook_secret)
        headers["X-Tessera-Signature"] = f"sha256={signature}"

    return headers


async def _deliver_webhook(event: WebhookEvent, delivery_id: UUID | None = None) -> bool:
    """Deliver a webhook event to the configured URL.

    Returns True if delivery succeeded, False otherwise.

    Uses a semaphore to limit concurrent deliveries (backpressure) and
    validates URLs to prevent SSRF attacks.
    """
    if not settings.webhook_url:
        logger.debug("No webhook URL configured, skipping delivery")
        return True

    # SSRF protection: validate the webhook URL
    is_valid, error_msg = await validate_webhook_url(settings.webhook_url)
    if not is_valid:
        logger.error("Webhook URL validation failed: %s", error_msg)
        if delivery_id:
            await _update_delivery_status(
                delivery_id,
                status=WebhookDeliveryStatus.FAILED,
                attempts=0,
                last_error=f"URL validation failed: {error_msg}",
            )
        return False

    payload = event.model_dump_json()
    headers = _build_webhook_headers(event, payload)

    last_error: str | None = None
    last_status_code: int | None = None

    # Backpressure: limit concurrent webhook deliveries
    semaphore = _get_webhook_semaphore()
    async with semaphore:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            for attempt, delay in enumerate(RETRY_DELAYS):
                try:
                    is_valid, error_msg = await validate_webhook_url(settings.webhook_url)
                    if not is_valid:
                        last_error = f"URL validation failed: {error_msg}"
                        logger.error("Webhook URL validation failed: %s", error_msg)
                        break
                    response = await client.post(
                        settings.webhook_url,
                        content=payload,
                        headers=headers,
                    )
                    last_status_code = response.status_code
                    if response.status_code < 300:
                        logger.info(
                            "Webhook delivered: %s to %s",
                            event.event.value,
                            settings.webhook_url,
                        )
                        # Update delivery record on success
                        if delivery_id:
                            await _update_delivery_status(
                                delivery_id,
                                status=WebhookDeliveryStatus.DELIVERED,
                                attempts=attempt + 1,
                                last_status_code=response.status_code,
                            )
                        return True
                    last_error = response.text[:500]
                    logger.warning(
                        "Webhook delivery failed (attempt %d): %s %s",
                        attempt + 1,
                        response.status_code,
                        response.text[:200],
                    )
                except httpx.RequestError as e:
                    last_error = str(e)[:500]
                    logger.warning(
                        "Webhook delivery error (attempt %d): %s",
                        attempt + 1,
                        str(e),
                    )

                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)

    logger.error(
        "Webhook delivery failed after %d attempts: %s",
        MAX_RETRIES,
        event.event.value,
    )

    # Update delivery record on final failure
    if delivery_id:
        await _update_delivery_status(
            delivery_id,
            status=WebhookDeliveryStatus.FAILED,
            attempts=MAX_RETRIES,
            last_error=last_error,
            last_status_code=last_status_code,
        )
    return False


async def _update_delivery_status(
    delivery_id: UUID,
    status: WebhookDeliveryStatus,
    attempts: int,
    last_error: str | None = None,
    last_status_code: int | None = None,
) -> None:
    """Update webhook delivery status in database."""
    try:
        async_session = get_async_session_maker()
        async with async_session() as session:
            result = await session.execute(
                select(WebhookDeliveryDB).where(WebhookDeliveryDB.id == delivery_id)
            )
            delivery = result.scalar_one_or_none()
            if delivery:
                delivery.status = status
                delivery.attempts = attempts
                delivery.last_attempt_at = datetime.now(UTC)
                delivery.last_error = last_error
                delivery.last_status_code = last_status_code
                if status == WebhookDeliveryStatus.DELIVERED:
                    delivery.delivered_at = datetime.now(UTC)
                await session.commit()
    except Exception as e:
        logger.error("Failed to update webhook delivery status: %s", e)


async def _create_delivery_record(event: WebhookEvent) -> UUID | None:
    """Create a webhook delivery record in the database."""
    if not settings.webhook_url:
        return None
    try:
        async_session = get_async_session_maker()
        async with async_session() as session:
            delivery = WebhookDeliveryDB(
                event_type=event.event.value,
                payload=event.model_dump(),
                url=settings.webhook_url,
                status=WebhookDeliveryStatus.PENDING,
            )
            session.add(delivery)
            await session.commit()
            await session.refresh(delivery)
            return delivery.id
    except Exception as e:
        logger.error("Failed to create webhook delivery record: %s", e)
        return None


def _fire_and_forget(event: WebhookEvent) -> None:
    """Schedule webhook delivery without blocking."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver_with_tracking(event))
    except RuntimeError:
        # No running loop - skip webhook (happens in tests without async context)
        logger.debug("No event loop, skipping webhook: %s", event.event.value)


async def _deliver_with_tracking(event: WebhookEvent) -> bool:
    """Create delivery record and deliver webhook."""
    delivery_id = await _create_delivery_record(event)
    return await _deliver_webhook(event, delivery_id)


async def send_proposal_created(
    proposal_id: UUID,
    asset_id: UUID,
    asset_fqn: str,
    producer_team_id: UUID,
    producer_team_name: str,
    proposed_version: str,
    breaking_changes: list[dict[str, Any]],
    impacted_consumers: list[dict[str, Any]],
) -> None:
    """Send webhook when a breaking change proposal is created."""
    event = WebhookEvent(
        event=WebhookEventType.PROPOSAL_CREATED,
        timestamp=datetime.now(UTC),
        payload=ProposalCreatedPayload(
            proposal_id=proposal_id,
            asset_id=asset_id,
            asset_fqn=asset_fqn,
            producer_team_id=producer_team_id,
            producer_team_name=producer_team_name,
            proposed_version=proposed_version,
            breaking_changes=[
                BreakingChange(
                    change_type=c.get("change_type", "unknown"),
                    path=c.get("path", ""),
                    message=c.get("message", ""),
                    details=c.get("details"),
                )
                for c in breaking_changes
            ],
            impacted_consumers=[
                ImpactedConsumer(
                    team_id=c["team_id"],
                    team_name=c["team_name"],
                    pinned_version=c.get("pinned_version"),
                )
                for c in impacted_consumers
            ],
        ),
    )
    _fire_and_forget(event)


async def send_proposal_acknowledged(
    proposal_id: UUID,
    asset_id: UUID,
    asset_fqn: str,
    consumer_team_id: UUID,
    consumer_team_name: str,
    response: str,
    migration_deadline: datetime | None,
    notes: str | None,
    pending_count: int,
    acknowledged_count: int,
) -> None:
    """Send webhook when a consumer acknowledges a proposal."""
    event = WebhookEvent(
        event=WebhookEventType.PROPOSAL_ACKNOWLEDGED,
        timestamp=datetime.now(UTC),
        payload=AcknowledgmentPayload(
            proposal_id=proposal_id,
            asset_id=asset_id,
            asset_fqn=asset_fqn,
            consumer_team_id=consumer_team_id,
            consumer_team_name=consumer_team_name,
            response=response,
            migration_deadline=migration_deadline,
            notes=notes,
            pending_count=pending_count,
            acknowledged_count=acknowledged_count,
        ),
    )
    _fire_and_forget(event)


async def send_proposal_status_change(
    event_type: WebhookEventType,
    proposal_id: UUID,
    asset_id: UUID,
    asset_fqn: str,
    status: str,
    actor_team_id: UUID | None = None,
    actor_team_name: str | None = None,
) -> None:
    """Send webhook when proposal status changes (approved, rejected, etc.)."""
    event = WebhookEvent(
        event=event_type,
        timestamp=datetime.now(UTC),
        payload=ProposalStatusPayload(
            proposal_id=proposal_id,
            asset_id=asset_id,
            asset_fqn=asset_fqn,
            status=status,
            actor_team_id=actor_team_id,
            actor_team_name=actor_team_name,
        ),
    )
    _fire_and_forget(event)


async def send_contract_published(
    contract_id: UUID,
    asset_id: UUID,
    asset_fqn: str,
    version: str,
    producer_team_id: UUID,
    producer_team_name: str,
    from_proposal_id: UUID | None = None,
) -> None:
    """Send webhook when a contract is published."""
    event = WebhookEvent(
        event=WebhookEventType.CONTRACT_PUBLISHED,
        timestamp=datetime.now(UTC),
        payload=ContractPublishedPayload(
            contract_id=contract_id,
            asset_id=asset_id,
            asset_fqn=asset_fqn,
            version=version,
            producer_team_id=producer_team_id,
            producer_team_name=producer_team_name,
            from_proposal_id=from_proposal_id,
        ),
    )
    _fire_and_forget(event)
