"""Tests for webhook HTTP delivery with mocking."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tessera.models.webhook import (
    ContractPublishedPayload,
    ProposalCreatedPayload,
    WebhookEvent,
    WebhookEventType,
)
from tessera.services.webhooks import (
    _deliver_webhook,
    _fire_and_forget,
    _sign_payload,
)

pytestmark = pytest.mark.asyncio


class TestWebhookDelivery:
    """Tests for _deliver_webhook function."""

    async def test_deliver_no_url_configured(self):
        """Returns True (success) when no webhook URL configured."""
        with patch("tessera.services.webhooks.settings") as mock_settings:
            mock_settings.webhook_url = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event)
            assert result is True

    async def test_deliver_success(self):
        """Successfully delivers webhook."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            event = WebhookEvent(
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
            result = await _deliver_webhook(event)
            assert result is True
            mock_client.post.assert_called_once()

    async def test_deliver_with_signature(self):
        """Adds signature header when secret is configured."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = "my-secret-key"

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            event = WebhookEvent(
                event=WebhookEventType.PROPOSAL_CREATED,
                timestamp=datetime.now(UTC),
                payload=ProposalCreatedPayload(
                    proposal_id=uuid4(),
                    asset_id=uuid4(),
                    asset_fqn="test.asset",
                    producer_team_id=uuid4(),
                    producer_team_name="test-team",
                    proposed_version="2.0.0",
                    breaking_changes=[],
                    impacted_consumers=[],
                ),
            )
            result = await _deliver_webhook(event)
            assert result is True

            # Check that signature header was added
            call_args = mock_client.post.call_args
            headers = call_args.kwargs["headers"]
            assert "X-Tessera-Signature" in headers
            assert headers["X-Tessera-Signature"].startswith("sha256=")

    async def test_deliver_retries_on_failure(self):
        """Retries on non-2xx response."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            # Fail first two attempts, succeed on third
            mock_response_fail = AsyncMock()
            mock_response_fail.status_code = 500
            mock_response_fail.text = "Internal Server Error"

            mock_response_success = AsyncMock()
            mock_response_success.status_code = 200
            mock_response_success.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[
                    mock_response_fail,
                    mock_response_fail,
                    mock_response_success,
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event)
            assert result is True
            assert mock_client.post.call_count == 3

    async def test_deliver_fails_after_max_retries(self):
        """Returns False after exhausting retries."""
        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            # All attempts fail
            mock_response = AsyncMock()
            mock_response.status_code = 503
            mock_response.text = "Service Unavailable"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event)
            assert result is False


class TestFireAndForget:
    """Tests for _fire_and_forget function."""

    def test_fire_and_forget_no_loop(self):
        """Does not raise when no event loop is running."""
        # This should not raise
        event = WebhookEvent(
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
        # In a non-async context, this should just log and return
        _fire_and_forget(event)

    async def test_fire_and_forget_with_loop(self):
        """Schedules delivery task when loop is running."""
        with (
            patch("tessera.services.webhooks._deliver_with_tracking"),
            patch("tessera.services.webhooks.asyncio.get_running_loop") as mock_loop,
        ):
            mock_task = MagicMock()
            mock_loop_obj = MagicMock()
            mock_loop_obj.create_task = MagicMock(return_value=mock_task)
            mock_loop.return_value = mock_loop_obj

            event = WebhookEvent(
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
            _fire_and_forget(event)
            mock_loop_obj.create_task.assert_called_once()


class TestSignPayload:
    """Tests for _sign_payload function."""

    def test_sign_returns_hex(self):
        """Signature is a hex string."""
        sig = _sign_payload('{"test": true}', "secret")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_consistent(self):
        """Same input produces same signature."""
        payload = '{"data": "test"}'
        secret = "my-secret"
        sig1 = _sign_payload(payload, secret)
        sig2 = _sign_payload(payload, secret)
        assert sig1 == sig2

    def test_sign_different_secrets(self):
        """Different secrets produce different signatures."""
        payload = '{"data": "test"}'
        sig1 = _sign_payload(payload, "secret1")
        sig2 = _sign_payload(payload, "secret2")
        assert sig1 != sig2

    def test_sign_different_payloads(self):
        """Different payloads produce different signatures."""
        secret = "my-secret"
        sig1 = _sign_payload('{"a": 1}', secret)
        sig2 = _sign_payload('{"b": 2}', secret)
        assert sig1 != sig2


class TestSendWebhookFunctions:
    """Tests for send_* webhook functions."""

    async def test_send_proposal_created(self):
        """send_proposal_created creates event and fires."""
        from tessera.services.webhooks import send_proposal_created

        with patch("tessera.services.webhooks._fire_and_forget") as mock_fire:
            await send_proposal_created(
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="db.schema.table",
                producer_team_id=uuid4(),
                producer_team_name="data-team",
                proposed_version="2.0.0",
                breaking_changes=[
                    {"change_type": "removed", "path": "$.email", "message": "Field removed"}
                ],
                impacted_consumers=[
                    {"team_id": uuid4(), "team_name": "marketing", "pinned_version": "1.0.0"}
                ],
            )
            mock_fire.assert_called_once()
            event = mock_fire.call_args[0][0]
            assert event.event == WebhookEventType.PROPOSAL_CREATED
            assert event.payload.proposed_version == "2.0.0"
            assert len(event.payload.breaking_changes) == 1
            assert len(event.payload.impacted_consumers) == 1

    async def test_send_proposal_acknowledged(self):
        """send_proposal_acknowledged creates event and fires."""
        from tessera.services.webhooks import send_proposal_acknowledged

        with patch("tessera.services.webhooks._fire_and_forget") as mock_fire:
            await send_proposal_acknowledged(
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="db.schema.table",
                consumer_team_id=uuid4(),
                consumer_team_name="finance-team",
                response="approved",
                migration_deadline=None,
                notes="Looks good to me",
                pending_count=2,
                acknowledged_count=3,
            )
            mock_fire.assert_called_once()
            event = mock_fire.call_args[0][0]
            assert event.event == WebhookEventType.PROPOSAL_ACKNOWLEDGED
            assert event.payload.response == "approved"
            assert event.payload.pending_count == 2

    async def test_send_proposal_status_change(self):
        """send_proposal_status_change creates event and fires."""
        from tessera.services.webhooks import send_proposal_status_change

        with patch("tessera.services.webhooks._fire_and_forget") as mock_fire:
            await send_proposal_status_change(
                event_type=WebhookEventType.PROPOSAL_APPROVED,
                proposal_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="db.schema.table",
                status="approved",
                actor_team_id=uuid4(),
                actor_team_name="data-team",
            )
            mock_fire.assert_called_once()
            event = mock_fire.call_args[0][0]
            assert event.event == WebhookEventType.PROPOSAL_APPROVED
            assert event.payload.status == "approved"

    async def test_send_contract_published(self):
        """send_contract_published creates event and fires."""
        from tessera.services.webhooks import send_contract_published

        with patch("tessera.services.webhooks._fire_and_forget") as mock_fire:
            await send_contract_published(
                contract_id=uuid4(),
                asset_id=uuid4(),
                asset_fqn="db.schema.table",
                version="2.0.0",
                producer_team_id=uuid4(),
                producer_team_name="data-team",
                from_proposal_id=uuid4(),
            )
            mock_fire.assert_called_once()
            event = mock_fire.call_args[0][0]
            assert event.event == WebhookEventType.CONTRACT_PUBLISHED
            assert event.payload.version == "2.0.0"


class TestDeliverWithTracking:
    """Tests for _deliver_with_tracking function."""

    async def test_deliver_with_tracking_success(self):
        """Creates delivery record and delivers webhook."""
        from tessera.services.webhooks import _deliver_with_tracking

        event = WebhookEvent(
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

        with (
            patch("tessera.services.webhooks._create_delivery_record") as mock_create,
            patch("tessera.services.webhooks._deliver_webhook") as mock_deliver,
        ):
            mock_create.return_value = uuid4()
            mock_deliver.return_value = True

            result = await _deliver_with_tracking(event)
            assert result is True
            mock_create.assert_called_once_with(event)
            mock_deliver.assert_called_once()


class TestCreateDeliveryRecord:
    """Tests for _create_delivery_record function."""

    async def test_create_delivery_record_no_url(self):
        """Returns None when no webhook URL configured."""
        from tessera.services.webhooks import _create_delivery_record

        event = WebhookEvent(
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

        with patch("tessera.services.webhooks.settings") as mock_settings:
            mock_settings.webhook_url = None
            result = await _create_delivery_record(event)
            assert result is None


class TestUpdateDeliveryStatus:
    """Tests for _update_delivery_status function."""

    async def test_update_delivery_status_exception(self):
        """Logs error when update fails."""
        from tessera.services.webhooks import WebhookDeliveryStatus, _update_delivery_status

        with patch("tessera.services.webhooks.get_async_session_maker") as mock_session:
            mock_session.side_effect = Exception("DB error")
            # Should not raise
            await _update_delivery_status(
                uuid4(),
                status=WebhookDeliveryStatus.FAILED,
                attempts=3,
                last_error="Error",
            )

    async def test_update_delivery_status_success(self):
        """Successfully updates delivery status."""
        from tessera.services.webhooks import WebhookDeliveryStatus, _update_delivery_status

        delivery_id = uuid4()
        mock_delivery = MagicMock()
        mock_delivery.status = WebhookDeliveryStatus.PENDING
        mock_delivery.attempts = 0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_delivery

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_maker = MagicMock()
        mock_session_maker.return_value = mock_session

        with patch(
            "tessera.services.webhooks.get_async_session_maker",
            return_value=mock_session_maker,
        ):
            await _update_delivery_status(
                delivery_id,
                status=WebhookDeliveryStatus.DELIVERED,
                attempts=1,
                last_status_code=200,
            )
            mock_session.commit.assert_called_once()
            assert mock_delivery.status == WebhookDeliveryStatus.DELIVERED
            assert mock_delivery.attempts == 1

    async def test_update_delivery_status_failed(self):
        """Updates delivery status to failed with error info."""
        from tessera.services.webhooks import WebhookDeliveryStatus, _update_delivery_status

        delivery_id = uuid4()
        mock_delivery = MagicMock()
        mock_delivery.status = WebhookDeliveryStatus.PENDING

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_delivery

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_maker = MagicMock()
        mock_session_maker.return_value = mock_session

        with patch(
            "tessera.services.webhooks.get_async_session_maker",
            return_value=mock_session_maker,
        ):
            await _update_delivery_status(
                delivery_id,
                status=WebhookDeliveryStatus.FAILED,
                attempts=3,
                last_error="Service unavailable",
                last_status_code=503,
            )
            assert mock_delivery.status == WebhookDeliveryStatus.FAILED
            assert mock_delivery.last_error == "Service unavailable"
            assert mock_delivery.last_status_code == 503

    async def test_update_delivery_status_not_found(self):
        """Handles case when delivery record not found."""
        from tessera.services.webhooks import WebhookDeliveryStatus, _update_delivery_status

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_maker = MagicMock()
        mock_session_maker.return_value = mock_session

        with patch(
            "tessera.services.webhooks.get_async_session_maker",
            return_value=mock_session_maker,
        ):
            # Should not raise
            await _update_delivery_status(
                uuid4(),
                status=WebhookDeliveryStatus.DELIVERED,
                attempts=1,
            )


class TestCreateDeliveryRecordWithDB:
    """Tests for _create_delivery_record with mocked database."""

    async def test_create_delivery_record_success(self):
        """Successfully creates delivery record."""
        from tessera.services.webhooks import _create_delivery_record

        event = WebhookEvent(
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

        delivery_id = uuid4()
        mock_delivery = MagicMock()
        mock_delivery.id = delivery_id

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        def set_id_on_refresh(obj):
            obj.id = delivery_id

        mock_session.refresh.side_effect = set_id_on_refresh

        mock_session_maker = MagicMock()
        mock_session_maker.return_value = mock_session

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch(
                "tessera.services.webhooks.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch("tessera.services.webhooks.WebhookDeliveryDB") as mock_db_cls,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_db_instance = MagicMock()
            mock_db_instance.id = delivery_id
            mock_db_cls.return_value = mock_db_instance

            result = await _create_delivery_record(event)
            assert result == delivery_id
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    async def test_create_delivery_record_exception(self):
        """Returns None when database error occurs."""
        from tessera.services.webhooks import _create_delivery_record

        event = WebhookEvent(
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

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.get_async_session_maker") as mock_maker,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_maker.side_effect = Exception("DB error")

            result = await _create_delivery_record(event)
            assert result is None


class TestDeliverWebhookWithDeliveryId:
    """Tests for _deliver_webhook with delivery tracking."""

    async def test_deliver_success_with_delivery_id(self):
        """Updates delivery status on success when delivery_id provided."""

        delivery_id = uuid4()

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks._update_delivery_status") as mock_update,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "ok"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            event = WebhookEvent(
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
            result = await _deliver_webhook(event, delivery_id=delivery_id)
            assert result is True
            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args.kwargs
            assert call_kwargs["status"].value == "delivered"
            assert call_kwargs["attempts"] == 1

    async def test_deliver_failure_with_delivery_id(self):
        """Updates delivery status on failure when delivery_id provided."""
        delivery_id = uuid4()

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
            patch("tessera.services.webhooks._update_delivery_status") as mock_update,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "Error"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event, delivery_id=delivery_id)
            assert result is False
            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args.kwargs
            assert call_kwargs["status"].value == "failed"
            assert call_kwargs["attempts"] == 3

    async def test_deliver_request_error(self):
        """Handles httpx.RequestError during delivery."""
        import httpx

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event)
            assert result is False
            assert mock_client.post.call_count == 3

    async def test_deliver_request_error_with_delivery_id(self):
        """Updates status on RequestError when delivery_id provided."""
        import httpx

        delivery_id = uuid4()

        with (
            patch("tessera.services.webhooks.settings") as mock_settings,
            patch("tessera.services.webhooks.httpx.AsyncClient") as mock_client_cls,
            patch("tessera.services.webhooks.asyncio.sleep") as mock_sleep,
            patch("tessera.services.webhooks._update_delivery_status") as mock_update,
        ):
            mock_settings.webhook_url = "https://example.com/webhook"
            mock_settings.webhook_secret = None

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            mock_sleep.return_value = None

            event = WebhookEvent(
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
            result = await _deliver_webhook(event, delivery_id=delivery_id)
            assert result is False
            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args.kwargs
            assert "Connection refused" in call_kwargs["last_error"]
