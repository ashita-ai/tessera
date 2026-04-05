"""Tests for bulk endpoint error handling: IntegrityError vs DBAPIError behaviour."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.asyncio


async def _setup_team_and_contract(client: AsyncClient) -> tuple[str, str, str]:
    """Create a team, asset, and active contract. Returns (team_id, asset_id, contract_id)."""
    team_resp = await client.post("/api/v1/teams", json={"name": "err-team"})
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets", json={"fqn": "err.handling.table", "owner_team_id": team_id}
    )
    asset_id = asset_resp.json()["id"]

    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
        json={
            "version": "1.0.0",
            "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            "compatibility_mode": "backward",
        },
    )
    contract_id = contract_resp.json()["contract"]["id"]
    return team_id, asset_id, contract_id


def _make_integrity_error() -> IntegrityError:
    """Build a realistic IntegrityError (subclass of DBAPIError)."""
    return IntegrityError(
        statement="INSERT INTO ...",
        params={},
        orig=Exception("UNIQUE constraint failed"),
    )


def _make_dbapi_error() -> DBAPIError:
    """Build a connection-level DBAPIError (OperationalError is a subclass)."""
    return DBAPIError(
        statement="INSERT INTO ...",
        params={},
        orig=Exception("connection reset by peer"),
    )


class TestBulkRegistrationErrorHandling:
    """IntegrityError should fail one item; DBAPIError should abort the batch."""

    async def test_integrity_error_fails_single_item(self, client: AsyncClient) -> None:
        """An IntegrityError on one registration should not abort subsequent items."""
        team_id, _, contract_id = await _setup_team_and_contract(client)
        consumer_resp = await client.post("/api/v1/teams", json={"name": "ie-consumer"})
        consumer_id = consumer_resp.json()["id"]

        original_flush = None

        async def _flush_bomb(*args, **kwargs):
            """Raise IntegrityError on the first flush only, then behave normally."""
            nonlocal original_flush
            _flush_bomb.call_count += 1
            if _flush_bomb.call_count == 1:
                raise _make_integrity_error()
            return await original_flush(*args, **kwargs)

        _flush_bomb.call_count = 0

        # We need a second contract for the second registration
        asset2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "err.handling.table2", "owner_team_id": team_id}
        )
        asset2_id = asset2_resp.json()["id"]
        contract2_resp = await client.post(
            f"/api/v1/assets/{asset2_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract2_id = contract2_resp.json()["contract"]["id"]

        # Patch session.flush via the begin_nested context to trigger on the
        # savepoint flush inside the bulk loop.
        with patch(
            "tessera.api.bulk.AsyncSession.flush",
            side_effect=_flush_bomb,
            autospec=True,
        ):
            original_flush = AsyncMock()
            resp = await client.post(
                "/api/v1/bulk/registrations",
                json={
                    "registrations": [
                        {"contract_id": contract_id, "consumer_team_id": consumer_id},
                        {"contract_id": contract2_id, "consumer_team_id": consumer_id},
                    ]
                },
            )

        data = resp.json()
        assert resp.status_code == 207
        # First item should fail with constraint error
        assert data["results"][0]["success"] is False
        assert "constraint" in data["results"][0]["error"].lower()
        # Second item should NOT be "skipped — database connection lost"
        # (it should either succeed or fail independently, not be aborted)
        assert data["total"] == 2
        if data["results"][1]["success"] is False:
            assert "connection lost" not in data["results"][1]["error"].lower()

    async def test_dbapi_error_aborts_remaining_items(self, client: AsyncClient) -> None:
        """A DBAPIError should abort the batch and mark remaining items as skipped."""
        team_id, _, contract_id = await _setup_team_and_contract(client)
        consumer_resp = await client.post("/api/v1/teams", json={"name": "db-consumer"})
        consumer_id = consumer_resp.json()["id"]

        asset2_resp = await client.post(
            "/api/v1/assets", json={"fqn": "err.dbapi.table2", "owner_team_id": team_id}
        )
        asset2_id = asset2_resp.json()["id"]
        contract2_resp = await client.post(
            f"/api/v1/assets/{asset2_id}/contracts?published_by={team_id}",
            json={
                "version": "1.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        contract2_id = contract2_resp.json()["contract"]["id"]

        with patch(
            "tessera.api.bulk.AsyncSession.flush",
            side_effect=_make_dbapi_error(),
            autospec=True,
        ):
            resp = await client.post(
                "/api/v1/bulk/registrations",
                json={
                    "registrations": [
                        {"contract_id": contract_id, "consumer_team_id": consumer_id},
                        {"contract_id": contract2_id, "consumer_team_id": consumer_id},
                    ]
                },
            )

        data = resp.json()
        assert resp.status_code == 207
        assert data["failed"] == 2
        # First item gets the DBAPIError
        assert data["results"][0]["success"] is False
        assert "remaining items skipped" in data["results"][0]["error"].lower()
        # Second item is marked as skipped
        assert data["results"][1]["success"] is False
        assert "skipped" in data["results"][1]["error"].lower()


class TestBulkAssetErrorHandling:
    """IntegrityError vs DBAPIError handling in bulk asset creation."""

    async def test_dbapi_error_aborts_remaining_assets(self, client: AsyncClient) -> None:
        """A connection-level error should abort the remaining asset batch."""
        team_resp = await client.post("/api/v1/teams", json={"name": "dbapi-asset-team"})
        team_id = team_resp.json()["id"]

        with patch(
            "tessera.api.bulk.AsyncSession.flush",
            side_effect=_make_dbapi_error(),
            autospec=True,
        ):
            resp = await client.post(
                "/api/v1/bulk/assets",
                json={
                    "assets": [
                        {"fqn": "dbapi.asset.one", "owner_team_id": team_id},
                        {"fqn": "dbapi.asset.two", "owner_team_id": team_id},
                        {"fqn": "dbapi.asset.three", "owner_team_id": team_id},
                    ]
                },
            )

        data = resp.json()
        assert resp.status_code == 207
        assert data["failed"] == 3
        assert "remaining items skipped" in data["results"][0]["error"].lower()
        assert "skipped" in data["results"][1]["error"].lower()
        assert "skipped" in data["results"][2]["error"].lower()


class TestBulkAcknowledgmentErrorHandling:
    """IntegrityError vs DBAPIError handling in bulk acknowledgments."""

    async def test_dbapi_error_aborts_remaining_acknowledgments(self, client: AsyncClient) -> None:
        """A connection-level error should abort the remaining ack batch."""
        producer_resp = await client.post("/api/v1/teams", json={"name": "dbapi-ack-producer"})
        consumer_resp = await client.post("/api/v1/teams", json={"name": "dbapi-ack-consumer"})
        producer_id = producer_resp.json()["id"]
        consumer_id = consumer_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets", json={"fqn": "dbapi.ack.table", "owner_team_id": producer_id}
        )
        asset_id = asset_resp.json()["id"]

        # Create contract + registration to enable proposals
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                },
                "compatibility_mode": "backward",
            },
        )
        contract_id = contract_resp.json()["contract"]["id"]

        await client.post(
            f"/api/v1/registrations?contract_id={contract_id}",
            json={"consumer_team_id": consumer_id},
        )

        # Breaking change to create a proposal
        proposal_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={producer_id}",
            json={
                "version": "2.0.0",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "compatibility_mode": "backward",
            },
        )
        proposal_id = proposal_resp.json()["proposal"]["id"]

        with patch(
            "tessera.api.bulk.AsyncSession.flush",
            side_effect=_make_dbapi_error(),
            autospec=True,
        ):
            resp = await client.post(
                "/api/v1/bulk/acknowledgments",
                json={
                    "acknowledgments": [
                        {
                            "proposal_id": proposal_id,
                            "consumer_team_id": consumer_id,
                            "response": "approved",
                        },
                    ]
                },
            )

        data = resp.json()
        assert resp.status_code == 207
        assert data["failed"] == 1
        assert data["results"][0]["success"] is False
        assert "remaining items skipped" in data["results"][0]["error"].lower()
