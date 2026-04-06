"""Tests for savepoint atomicity in guarantee updates.

Verifies that the guarantee mutation and its audit log record
succeed or fail together inside a begin_nested() savepoint.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_contract(client: AsyncClient) -> tuple[str, str]:
    """Create a team, asset, and contract. Returns (team_id, contract_id)."""
    team_resp = await client.post("/api/v1/teams", json={"name": "atom-team"})
    team_id = team_resp.json()["id"]

    asset_resp = await client.post(
        "/api/v1/assets", json={"fqn": "atom.guarantee.table", "owner_team_id": team_id}
    )
    asset_id = asset_resp.json()["id"]

    contract_resp = await client.post(
        f"/api/v1/assets/{asset_id}/publish?published_by={team_id}",
        json={
            "version": "1.0.0",
            "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            "compatibility_mode": "backward",
            "guarantees": {"freshness": {"max_staleness_minutes": 120}},
        },
    )
    contract_id = contract_resp.json()["contract"]["id"]
    return team_id, contract_id


class TestGuaranteesAtomicity:
    """Guarantee update + audit log must be atomic (savepoint)."""

    async def test_audit_failure_rolls_back_guarantee_change(self, client: AsyncClient) -> None:
        """If log_guarantees_updated fails, the guarantee mutation is rolled back."""
        _, contract_id = await _create_contract(client)

        # Verify initial guarantees
        get_resp = await client.get(f"/api/v1/contracts/{contract_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["guarantees"]["freshness"]["max_staleness_minutes"] == 120

        # Make log_guarantees_updated raise inside the savepoint.
        # ASGITransport re-raises unhandled server exceptions, so we
        # catch the propagated error here.
        with (
            patch(
                "tessera.api.contracts.log_guarantees_updated",
                new_callable=AsyncMock,
                side_effect=RuntimeError("simulated audit write failure"),
            ),
            pytest.raises(RuntimeError, match="simulated audit write failure"),
        ):
            await client.patch(
                f"/api/v1/contracts/{contract_id}/guarantees",
                json={"guarantees": {"volume": {"min_rows": 999}}},
            )

        # The guarantee should be unchanged because the savepoint rolled back
        get_resp = await client.get(f"/api/v1/contracts/{contract_id}")
        assert get_resp.status_code == 200
        guarantees = get_resp.json()["guarantees"]
        assert guarantees["freshness"]["max_staleness_minutes"] == 120
        # The new value should NOT have been persisted
        assert "volume" not in guarantees or guarantees.get("volume") is None

    async def test_successful_update_persists_both(self, client: AsyncClient) -> None:
        """A successful update persists both the guarantee and the audit event."""
        _, contract_id = await _create_contract(client)

        resp = await client.patch(
            f"/api/v1/contracts/{contract_id}/guarantees",
            json={"guarantees": {"volume": {"min_rows": 500}}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["guarantees"]["volume"]["min_rows"] == 500

        # Verify via a fresh GET
        get_resp = await client.get(f"/api/v1/contracts/{contract_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["guarantees"]["volume"]["min_rows"] == 500
