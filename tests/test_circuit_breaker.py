"""Tests for webhook circuit breaker pattern."""

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from tessera.models.webhook import (
    ContractPublishedPayload,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.webhooks import (
    CIRCUIT_BREAKER_THRESHOLD,
    _circuit_breaker,
    _CircuitBreaker,
    _deliver_webhook,
)


def _make_event() -> WebhookEvent:
    """Create a test webhook event."""
    return WebhookEvent(
        event=WebhookEventType.CONTRACT_PUBLISHED,
        timestamp=datetime.now(UTC),
        payload=ContractPublishedPayload(
            contract_id=uuid4(),
            asset_id=uuid4(),
            asset_fqn="test.asset",
            version="1.0.0",
            producer_team_id=uuid4(),
            producer_team_name="test-team",
        ),
    )


class TestCircuitBreakerUnit:
    """Unit tests for _CircuitBreaker class."""

    def test_starts_closed(self):
        """New circuit breaker is closed."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        assert cb.is_open() is False

    def test_stays_closed_below_threshold(self):
        """Circuit stays closed when failures are below threshold."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is False

    def test_opens_at_threshold(self):
        """Circuit opens when failures reach threshold."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True

    def test_success_resets_failures(self):
        """A success resets the failure counter."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Only 2 failures since last success, should still be closed
        assert cb.is_open() is False

    def test_success_closes_open_circuit(self):
        """A success closes an open circuit."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True
        cb.record_success()
        assert cb.is_open() is False

    def test_half_open_after_cooldown(self):
        """Circuit allows a probe after cooldown expires (half-open)."""
        cb = _CircuitBreaker(threshold=3, cooldown=0.0)  # Instant cooldown
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        # With 0 cooldown, the circuit should immediately be half-open
        assert cb.is_open() is False  # Cooldown expired → half-open → allow probe

    def test_reopens_after_probe_failure(self):
        """Circuit re-opens if a probe request (half-open) fails."""
        cb = _CircuitBreaker(threshold=3, cooldown=0.0)  # Instant cooldown
        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open() is False  # Cooldown = 0, so immediately half-open

        # Probe fails — circuit should re-open
        cb.record_failure()
        # After re-opening, is_open should reflect the new opened_at timestamp.
        # With cooldown=0, it immediately goes half-open again.
        # But the key point is that _opened_at was re-set (not left stale).
        assert cb._opened_at is not None
        assert cb._consecutive_failures == 4

    def test_reopens_blocks_during_cooldown(self):
        """After probe failure re-opens circuit, requests are blocked during cooldown."""
        cb = _CircuitBreaker(threshold=3, cooldown=9999)  # Very long cooldown
        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open() is True  # Still in cooldown

        # Manually expire the cooldown to simulate half-open
        cb._opened_at = time.monotonic() - 99999  # Long ago
        assert cb.is_open() is False  # Half-open: probe allowed

        # Probe fails — circuit re-opens with fresh timestamp
        cb.record_failure()
        assert cb.is_open() is True  # Re-opened, back in cooldown


@pytest.mark.asyncio
class TestDeadLetterQueue:
    """Unit tests for the dead letter queue in the circuit breaker."""

    @patch("tessera.services.webhooks.get_redis_client", new_callable=AsyncMock, return_value=None)
    async def test_enqueue_and_drain(self, _mock_redis):
        """Events can be enqueued and drained (in-memory fallback)."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        event1 = _make_event()
        event2 = _make_event()

        await cb.enqueue_dead_letter(event1)
        await cb.enqueue_dead_letter(event2)

        assert cb.dead_letter_count == 2

        drained = await cb.drain_dead_letters()
        assert len(drained) == 2
        assert drained[0] is event1
        assert drained[1] is event2
        assert cb.dead_letter_count == 0

    @patch("tessera.services.webhooks.get_redis_client", new_callable=AsyncMock, return_value=None)
    async def test_drain_empty_queue(self, _mock_redis):
        """Draining an empty queue returns empty list."""
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        assert await cb.drain_dead_letters() == []

    @patch("tessera.services.webhooks.get_redis_client", new_callable=AsyncMock, return_value=None)
    async def test_bounded_queue_drops_oldest(self, _mock_redis):
        """Queue drops oldest events when full."""
        cb = _CircuitBreaker(threshold=3, cooldown=60, dead_letter_max=3)
        events = [_make_event() for _ in range(5)]

        for e in events:
            await cb.enqueue_dead_letter(e)

        assert cb.dead_letter_count == 3
        drained = await cb.drain_dead_letters()
        # Should have the last 3 events (oldest 2 dropped)
        assert len(drained) == 3
        assert drained[0] is events[2]
        assert drained[1] is events[3]
        assert drained[2] is events[4]

    @patch("tessera.services.webhooks.get_redis_client", new_callable=AsyncMock, return_value=None)
    async def test_success_does_not_clear_dead_letters(self, _mock_redis):
        """record_success resets failure state but does NOT drain dead letters.

        The drain happens in _deliver_webhook after record_success, not inside
        the circuit breaker itself.
        """
        cb = _CircuitBreaker(threshold=3, cooldown=60)
        await cb.enqueue_dead_letter(_make_event())
        cb.record_success()
        assert cb.dead_letter_count == 1  # Still there, caller must drain


@pytest.mark.asyncio
class TestDeadLetterQueueRedis:
    """Tests for the Redis-backed dead letter queue path."""

    async def test_enqueue_stores_in_redis(self):
        """When Redis is available, enqueue pushes to the Redis LIST."""
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True, True, True])

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60, dead_letter_max=5)
            event = _make_event()
            result = await cb.enqueue_dead_letter(event)

            assert result is True
            # Should NOT fall back to in-memory
            assert cb.dead_letter_count == 0
            # Redis pipeline should have received lpush, ltrim, expire
            mock_pipe.lpush.assert_called_once()
            mock_pipe.ltrim.assert_called_once_with("tessera:dlq:webhooks", 0, 4)
            mock_pipe.expire.assert_called_once_with("tessera:dlq:webhooks", 48 * 60 * 60)
            mock_pipe.execute.assert_awaited_once()

    async def test_drain_reads_from_redis_in_fifo_order(self):
        """drain_dead_letters reads all events from Redis and restores FIFO order."""
        event1 = _make_event()
        event2 = _make_event()
        # LPUSH reverses insertion order: Redis stores [event2_json, event1_json]
        raw_events = [event2.model_dump_json().encode(), event1.model_dump_json().encode()]

        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[raw_events, 1])

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60)
            drained = await cb.drain_dead_letters()

            assert len(drained) == 2
            # reversed() should restore FIFO: event1 first, event2 second
            assert drained[0].payload.contract_id == event1.payload.contract_id
            assert drained[1].payload.contract_id == event2.payload.contract_id
            mock_pipe.lrange.assert_called_once_with("tessera:dlq:webhooks", 0, -1)
            mock_pipe.delete.assert_called_once_with("tessera:dlq:webhooks")

    async def test_enqueue_falls_back_on_redis_error(self):
        """When Redis raises an exception, enqueue falls back to in-memory."""
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60)
            event = _make_event()
            result = await cb.enqueue_dead_letter(event)

            assert result is True
            assert cb.dead_letter_count == 1  # Fell back to in-memory

    async def test_drain_falls_back_on_redis_error(self):
        """When Redis drain fails, in-memory events are still returned."""
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60)
            cb._dead_letters = [_make_event()]
            drained = await cb.drain_dead_letters()

            assert len(drained) == 1
            assert cb.dead_letter_count == 0

    async def test_drain_skips_malformed_redis_events(self):
        """Malformed JSON in Redis is skipped without crashing."""
        valid_event = _make_event()
        raw_events = [b"not-valid-json", valid_event.model_dump_json().encode()]

        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[raw_events, 1])

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60)
            drained = await cb.drain_dead_letters()

            # Only the valid event should be returned (malformed skipped)
            assert len(drained) == 1
            assert drained[0].payload.contract_id == valid_event.payload.contract_id

    async def test_drain_merges_redis_and_in_memory(self):
        """drain_dead_letters returns both Redis and in-memory events."""
        redis_event = _make_event()
        memory_event = _make_event()

        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[[redis_event.model_dump_json().encode()], 1])

        mock_redis = AsyncMock()
        mock_redis.pipeline = Mock(return_value=mock_pipe)

        with patch(
            "tessera.services.webhooks.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ):
            cb = _CircuitBreaker(threshold=3, cooldown=60)
            cb._dead_letters = [memory_event]
            drained = await cb.drain_dead_letters()

            assert len(drained) == 2
            # Redis events come first, then in-memory
            assert drained[0].payload.contract_id == redis_event.payload.contract_id
            assert drained[1].payload.contract_id == memory_event.payload.contract_id
            assert cb.dead_letter_count == 0


@pytest.mark.asyncio
class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker in webhook delivery."""

    async def test_open_circuit_skips_delivery(self):
        """When circuit is open, delivery fails fast without HTTP request."""
        # Reset the global circuit breaker state
        _circuit_breaker._consecutive_failures = 0
        _circuit_breaker._opened_at = None

        try:
            with (
                patch("tessera.services.webhooks.settings") as mock_settings,
                patch("tessera.services.webhooks._update_delivery_status") as mock_update,
            ):
                mock_settings.webhook_url = "https://example.com/webhook"

                # Force the circuit open
                import time

                _circuit_breaker._consecutive_failures = CIRCUIT_BREAKER_THRESHOLD
                _circuit_breaker._opened_at = time.monotonic()

                delivery_id = uuid4()
                event = _make_event()
                result = await _deliver_webhook(event, delivery_id=delivery_id)

                assert result is False
                # Should record failure with circuit breaker message
                mock_update.assert_called_once()
                call_kwargs = mock_update.call_args.kwargs
                assert "Circuit breaker open" in call_kwargs["last_error"]
        finally:
            # Always reset global state
            _circuit_breaker._consecutive_failures = 0
            _circuit_breaker._opened_at = None

    async def test_successful_delivery_resets_circuit(self):
        """A successful delivery resets the circuit breaker."""
        _circuit_breaker._consecutive_failures = 0
        _circuit_breaker._opened_at = None

        try:
            with (
                patch("tessera.services.webhooks.settings") as mock_settings,
                patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            ):
                mock_settings.webhook_url = "https://example.com/webhook"
                mock_settings.webhook_secret = None
                mock_settings.webhook_dns_timeout = 5.0

                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.text = "ok"

                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                # Simulate some prior failures
                _circuit_breaker._consecutive_failures = 3

                event = _make_event()
                result = await _deliver_webhook(event)

                assert result is True
                assert _circuit_breaker._consecutive_failures == 0
                assert _circuit_breaker._opened_at is None
        finally:
            _circuit_breaker._consecutive_failures = 0
            _circuit_breaker._opened_at = None

    async def test_failed_delivery_increments_circuit(self):
        """A failed delivery (all retries exhausted) increments the circuit breaker."""
        _circuit_breaker._consecutive_failures = 0
        _circuit_breaker._opened_at = None

        try:
            with (
                patch("tessera.services.webhooks.settings") as mock_settings,
                patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
                patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
            ):
                mock_settings.webhook_url = "https://example.com/webhook"
                mock_settings.webhook_secret = None
                mock_settings.webhook_dns_timeout = 5.0

                mock_response = AsyncMock()
                mock_response.status_code = 500
                mock_response.text = "Internal Server Error"

                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                mock_sleep.return_value = None

                event = _make_event()
                result = await _deliver_webhook(event)

                assert result is False
                assert _circuit_breaker._consecutive_failures == 1
        finally:
            _circuit_breaker._consecutive_failures = 0
            _circuit_breaker._opened_at = None

    async def test_circuit_opens_after_threshold_failures(self):
        """Circuit opens after CIRCUIT_BREAKER_THRESHOLD consecutive failed deliveries."""
        _circuit_breaker._consecutive_failures = 0
        _circuit_breaker._opened_at = None

        try:
            with (
                patch("tessera.services.webhooks.settings") as mock_settings,
                patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
                patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
            ):
                mock_settings.webhook_url = "https://example.com/webhook"
                mock_settings.webhook_secret = None
                mock_settings.webhook_dns_timeout = 5.0

                mock_response = AsyncMock()
                mock_response.status_code = 503
                mock_response.text = "Service Unavailable"

                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                mock_sleep.return_value = None

                # Deliver enough times to open the circuit
                for _ in range(CIRCUIT_BREAKER_THRESHOLD):
                    event = _make_event()
                    await _deliver_webhook(event)

                assert _circuit_breaker._consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD
                assert _circuit_breaker.is_open() is True
        finally:
            _circuit_breaker._consecutive_failures = 0
            _circuit_breaker._opened_at = None
