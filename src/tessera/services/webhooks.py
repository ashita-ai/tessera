"""Webhook delivery service.

The dead letter queue is backed by Redis when available, ensuring events
survive process restarts and are visible across workers.  When Redis is
unavailable the DLQ falls back to a bounded in-memory list (events lost
on restart).  Dead-lettered events are also persisted to the
``webhook_deliveries`` table with status ``DEAD_LETTERED`` as a durable
audit record regardless of DLQ backend.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import socket
import time
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
    ContractPublishedPayload,
    ImpactedConsumer,
    ProposalCreatedPayload,
    ProposalStatusPayload,
    WebhookBreakingChange,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.cache import get_redis_client

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [1, 5, 30]  # seconds between retries

# Backpressure: limit concurrent webhook deliveries to prevent resource exhaustion
MAX_CONCURRENT_WEBHOOKS = 10
_webhook_semaphore: asyncio.Semaphore | None = None

# Circuit breaker: stop hammering endpoints that are consistently down.
# After CIRCUIT_BREAKER_THRESHOLD consecutive failures, the circuit opens
# and all deliveries fail fast for CIRCUIT_BREAKER_COOLDOWN seconds.
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN = 60  # seconds


# Maximum events to retain in the dead letter queue. Once full, oldest events
# are dropped to bound memory usage. 100 events × ~2KB each ≈ 200KB worst case.
DEAD_LETTER_MAX_SIZE = 100

# Redis key for the durable dead letter queue. Events are serialized as JSON
# and stored in a Redis LIST (LPUSH/RPOP for FIFO ordering). A 48-hour TTL
# prevents unbounded growth if replay never runs.
_DLQ_REDIS_KEY = "tessera:dlq:webhooks"
_DLQ_TTL_SECONDS = 48 * 60 * 60  # 48 hours


class _CircuitBreaker:
    """Circuit breaker with Redis-backed dead letter queue for webhook delivery.

    Tracks consecutive failures per URL. When failures exceed the threshold,
    the circuit opens and deliveries fail fast until the cooldown expires.
    After cooldown, a single probe request is allowed through (half-open state).
    If it succeeds, the circuit closes and the dead letter queue is drained.

    Events that arrive while the circuit is open are stored in a Redis LIST
    for durability across process restarts. When Redis is unavailable, events
    fall back to a bounded in-memory list.
    """

    def __init__(
        self,
        threshold: int,
        cooldown: float,
        dead_letter_max: int = DEAD_LETTER_MAX_SIZE,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._consecutive_failures: int = 0
        self._opened_at: float | None = None
        self._dead_letter_max = dead_letter_max
        # In-memory fallback when Redis is unavailable
        self._dead_letters: list[WebhookEvent] = []

    def record_success(self) -> None:
        """Record a successful delivery. Resets the failure counter."""
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Record a failed delivery. Opens or re-opens the circuit if threshold is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            now = time.monotonic()
            if self._opened_at is None:
                logger.warning(
                    "Webhook circuit breaker opened after %d consecutive failures. "
                    "Deliveries will fail fast for %ds.",
                    self._consecutive_failures,
                    self._cooldown,
                )
            else:
                logger.warning(
                    "Webhook circuit breaker re-opened after probe failure. "
                    "Deliveries will fail fast for %ds.",
                    self._cooldown,
                )
            self._opened_at = now

    def is_open(self) -> bool:
        """Check if the circuit is open (should fail fast).

        Returns False if the circuit is closed or if the cooldown has elapsed
        (half-open state allows a single probe through).
        """
        if self._opened_at is None:
            return False
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._cooldown:
            return False
        return True

    async def enqueue_dead_letter(self, event: WebhookEvent) -> bool:
        """Add a failed event to the dead letter queue.

        Tries Redis first for cross-worker durability. Falls back to an
        in-memory list if Redis is unavailable.
        """
        serialized = event.model_dump_json()
        redis_client = await get_redis_client()
        if redis_client is not None:
            try:
                pipe = redis_client.pipeline()
                pipe.lpush(_DLQ_REDIS_KEY, serialized)
                pipe.ltrim(_DLQ_REDIS_KEY, 0, self._dead_letter_max - 1)
                pipe.expire(_DLQ_REDIS_KEY, _DLQ_TTL_SECONDS)
                await pipe.execute()
                return True
            except Exception:
                logger.warning("Redis DLQ push failed, falling back to in-memory")

        # In-memory fallback
        if len(self._dead_letters) >= self._dead_letter_max:
            dropped = self._dead_letters.pop(0)
            logger.warning(
                "Dead letter queue full (%d), dropped oldest event: %s",
                self._dead_letter_max,
                dropped.event.value,
            )
        self._dead_letters.append(event)
        return True

    async def drain_dead_letters(self) -> list[WebhookEvent]:
        """Remove and return all dead letter events for replay.

        Drains Redis first (durable, cross-worker), then any remaining
        in-memory events. Called after the circuit closes.
        """
        events: list[WebhookEvent] = []

        # Drain Redis DLQ atomically: read all, then delete the key
        redis_client = await get_redis_client()
        if redis_client is not None:
            try:
                pipe = redis_client.pipeline()
                pipe.lrange(_DLQ_REDIS_KEY, 0, -1)
                pipe.delete(_DLQ_REDIS_KEY)
                results = await pipe.execute()
                raw_events: list[bytes] = results[0] or []
                for raw in reversed(raw_events):  # LPUSH reverses order; reverse back to FIFO
                    try:
                        events.append(WebhookEvent.model_validate_json(raw))
                    except Exception:
                        logger.warning("Skipping malformed DLQ event from Redis")
            except Exception:
                logger.warning("Redis DLQ drain failed, falling back to in-memory only")

        # Also drain in-memory fallback events
        if self._dead_letters:
            events.extend(self._dead_letters)
            self._dead_letters = []

        if events:
            logger.info("Draining %d events from dead letter queue for replay", len(events))
        return events

    @property
    def dead_letter_count(self) -> int:
        """Number of events waiting in the in-memory dead letter queue.

        Does not include Redis-backed events (use for monitoring only).
        """
        return len(self._dead_letters)


# Global circuit breaker instance (one per process, keyed to the configured URL)
_circuit_breaker = _CircuitBreaker(CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_COOLDOWN)


def _get_webhook_semaphore() -> asyncio.Semaphore:
    """Get or create the webhook semaphore for the current event loop.

    Uses a global semaphore to limit concurrent webhook deliveries across all
    event handlers. This prevents resource exhaustion when many webhooks are
    triggered simultaneously (backpressure).

    Returns:
        asyncio.Semaphore: Semaphore limiting concurrent webhooks to MAX_CONCURRENT_WEBHOOKS.
    """
    global _webhook_semaphore
    if _webhook_semaphore is None:
        _webhook_semaphore = asyncio.Semaphore(MAX_CONCURRENT_WEBHOOKS)
    return _webhook_semaphore


def _is_blocked_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP should be blocked for SSRF protection.

    Blocks non-global IPs to prevent SSRF attacks targeting internal services.
    This includes private networks (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12),
    localhost (127.0.0.0/8), link-local (169.254.0.0/16), and multicast addresses.

    Args:
        ip_obj: IPv4 or IPv6 address object to check.

    Returns:
        bool: True if the IP should be blocked (is non-global), False otherwise.
    """
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
                timeout=settings.webhook_dns_timeout,
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
    """Sign a payload with HMAC-SHA256.

    Creates a cryptographic signature for webhook payloads to allow receivers
    to verify authenticity. Uses HMAC-SHA256 with the configured webhook secret.

    Args:
        payload: JSON string payload to sign.
        secret: Secret key used for HMAC signing.

    Returns:
        str: Hex-encoded HMAC-SHA256 signature.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_webhook_headers(event: WebhookEvent, payload: str) -> dict[str, str]:
    """Build webhook delivery headers, including signature if configured.

    Constructs HTTP headers for webhook delivery including:
    - Content-Type: application/json
    - X-Tessera-Event: Event type identifier
    - X-Tessera-Timestamp: ISO 8601 timestamp
    - X-Tessera-Signature: HMAC-SHA256 signature (if webhook_secret is configured)

    Args:
        event: Webhook event containing metadata.
        payload: JSON string payload (used for signature computation).

    Returns:
        dict[str, str]: HTTP headers for the webhook request.
    """
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

    Attempts delivery with exponential backoff retries (1s, 5s, 30s). Uses
    semaphore-based concurrency control to prevent resource exhaustion and
    validates URLs to prevent SSRF attacks.

    SSRF protection:
    - Validates URL scheme (HTTPS in production)
    - Checks hostname against optional allowlist
    - Resolves DNS and blocks non-global IPs (private networks, localhost, etc.)
    - Times out DNS resolution after 5 seconds

    Retry behavior:
    - Retries up to MAX_RETRIES times (3) with delays of [1, 5, 30] seconds
    - Updates delivery record status after each attempt
    - Returns True only if delivery succeeds (HTTP status < 300)

    Args:
        event: Webhook event to deliver.
        delivery_id: Optional delivery record ID for tracking.

    Returns:
        bool: True if delivery succeeded, False otherwise.
    """
    if not settings.webhook_url:
        logger.debug("No webhook URL configured, skipping delivery")
        return True

    # Circuit breaker: fail fast if the endpoint has been consistently failing.
    # Events are queued in the dead letter queue for replay when the endpoint recovers.
    if _circuit_breaker.is_open():
        logger.warning(
            "Webhook circuit breaker is open, queueing event for later: %s",
            event.event.value,
        )
        await _circuit_breaker.enqueue_dead_letter(event)
        if delivery_id:
            await _update_delivery_status(
                delivery_id,
                status=WebhookDeliveryStatus.DEAD_LETTERED,
                attempts=0,
                last_error=(
                    "Circuit breaker open: endpoint has been consistently failing. "
                    "Event queued for replay."
                ),
            )
        return False

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
                        _circuit_breaker.record_success()
                        # Replay dead letter queue if the circuit just closed
                        dead_letters = await _circuit_breaker.drain_dead_letters()
                        for dl_event in dead_letters:
                            _fire_and_forget(dl_event)
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

    _circuit_breaker.record_failure()
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
    except OSError:
        logger.error("Network error updating webhook delivery %s status", delivery_id)
    except Exception:
        logger.exception("Failed to update webhook delivery %s status", delivery_id)


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
    except OSError:
        logger.error("Network error creating webhook delivery record")
        return None
    except Exception:
        logger.exception("Failed to create webhook delivery record")
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
                WebhookBreakingChange(
                    change_type=c.get("type", c.get("change_type", "unknown")),
                    path=c.get("path", ""),
                    message=c.get("message", ""),
                    details={
                        k: v
                        for k, v in c.items()
                        if k not in ("type", "change_type", "path", "message")
                    }
                    or None,
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
