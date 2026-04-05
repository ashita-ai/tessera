"""Tests for preflight consumption audit events.

Covers:
- Preflight endpoint returns correct contract metadata
- Consumption events are logged automatically on preflight calls
- Events include consumer identity from auth context
- Events are queryable via GET /api/v1/audit/events with event_type filter
- Consumption events appear in entity history
- Edge cases: asset not found, no active contract, freshness evaluation
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AuditEventDB,
    AuditRunDB,
    ContractDB,
    TeamDB,
)
from tessera.models.enums import AuditRunStatus, CompatibilityMode, ContractStatus, SchemaFormat


@pytest.fixture
async def team(session: AsyncSession) -> TeamDB:
    team = TeamDB(name="test-team", metadata_={})
    session.add(team)
    await session.flush()
    return team


@pytest.fixture
async def asset_with_contract(session: AsyncSession, team: TeamDB) -> tuple[AssetDB, ContractDB]:
    """Create an asset with an active contract for testing."""
    asset = AssetDB(
        fqn="warehouse.analytics.customer_transactions",
        owner_team_id=team.id,
        metadata_={},
    )
    session.add(asset)
    await session.flush()

    contract = ContractDB(
        asset_id=asset.id,
        version="2.1.0",
        schema_def={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "transaction_amount": {"type": "integer"},
                "status": {"type": "string", "enum": ["completed", "refunded", "pending"]},
            },
            "required": ["customer_id", "transaction_amount"],
        },
        schema_format=SchemaFormat.JSON_SCHEMA,
        compatibility_mode=CompatibilityMode.BACKWARD,
        guarantees={
            "not_null": ["customer_id", "transaction_amount"],
            "unique": ["transaction_id"],
            "accepted_values": {"status": ["completed", "refunded", "pending"]},
            "freshness": {"max_staleness_minutes": 60},
        },
        status=ContractStatus.ACTIVE,
        published_by=team.id,
    )
    session.add(contract)
    await session.flush()
    return asset, contract


class TestPreflightEndpoint:
    """Tests for GET /api/v1/assets/{fqn}/preflight."""

    @pytest.mark.asyncio
    async def test_preflight_returns_contract_metadata(
        self,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        asset, contract = asset_with_contract
        response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
        assert response.status_code == 200
        data = response.json()

        assert data["asset_fqn"] == "warehouse.analytics.customer_transactions"
        assert data["asset_id"] == str(asset.id)
        assert data["contract_version"] == "2.1.0"
        assert data["compatibility_mode"] == "backward"
        assert data["schema_format"] == "json_schema"
        assert data["guarantees"] is not None
        assert "not_null" in data["guarantees"]
        assert "unique" in data["guarantees"]

    @pytest.mark.asyncio
    async def test_preflight_asset_not_found(self, client: AsyncClient):
        response = await client.get("/api/v1/assets/nonexistent.asset.fqn/preflight")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_preflight_no_active_contract(
        self,
        session: AsyncSession,
        client: AsyncClient,
        team: TeamDB,
    ):
        """Asset exists but has no active contract."""
        asset = AssetDB(
            fqn="warehouse.empty.no_contract",
            owner_team_id=team.id,
            metadata_={},
        )
        session.add(asset)
        await session.flush()

        response = await client.get("/api/v1/assets/warehouse.empty.no_contract/preflight")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_preflight_with_consumer_type(
        self,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        asset, _ = asset_with_contract
        response = await client.get(
            f"/api/v1/assets/{asset.fqn}/preflight",
            params={"consumer_type": "agent"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_preflight_freshness_fresh(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Data is fresh when last audit is within SLA window."""
        asset, contract = asset_with_contract
        audit_run = AuditRunDB(
            asset_id=asset.id,
            contract_id=contract.id,
            status=AuditRunStatus.PASSED,
            guarantees_checked=3,
            guarantees_passed=3,
            guarantees_failed=0,
            triggered_by="dbt_test",
            run_at=datetime.now(UTC) - timedelta(minutes=30),  # 30 min ago, SLA is 60
        )
        session.add(audit_run)
        await session.flush()

        response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
        assert response.status_code == 200
        data = response.json()
        assert data["fresh"] is True
        assert data["freshness_sla"]["max_staleness_minutes"] == 60
        assert data["last_audit_status"] == "passed"

    @pytest.mark.asyncio
    async def test_preflight_freshness_stale(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Data is stale when last audit exceeds SLA window."""
        asset, contract = asset_with_contract
        audit_run = AuditRunDB(
            asset_id=asset.id,
            contract_id=contract.id,
            status=AuditRunStatus.PASSED,
            guarantees_checked=3,
            guarantees_passed=3,
            guarantees_failed=0,
            triggered_by="dbt_test",
            run_at=datetime.now(UTC) - timedelta(minutes=120),  # 2 hours ago, SLA is 60
        )
        session.add(audit_run)
        await session.flush()

        response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
        assert response.status_code == 200
        data = response.json()
        assert data["fresh"] is False
        assert "Data does not meet the freshness SLA." in data["caveats"]

    @pytest.mark.asyncio
    async def test_preflight_failed_audit_caveat(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Caveats include warning when last audit failed."""
        asset, contract = asset_with_contract
        audit_run = AuditRunDB(
            asset_id=asset.id,
            contract_id=contract.id,
            status=AuditRunStatus.FAILED,
            guarantees_checked=3,
            guarantees_passed=1,
            guarantees_failed=2,
            triggered_by="dbt_test",
            run_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(audit_run)
        await session.flush()

        response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
        assert response.status_code == 200
        data = response.json()
        assert any("audit run failed" in c for c in data["caveats"])
        assert data["last_audit_status"] == "failed"


class TestPreflightAuditEvents:
    """Tests for consumption event logging on preflight calls."""

    @pytest.mark.asyncio
    async def test_preflight_logs_audit_event(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Every preflight call creates a preflight.checked audit event."""
        asset, _ = asset_with_contract

        response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
        assert response.status_code == 200

        # Verify audit event was created
        from sqlalchemy import select

        result = await session.execute(
            select(AuditEventDB).where(AuditEventDB.action == "preflight.checked")
        )
        events = result.scalars().all()
        assert len(events) == 1

        event = events[0]
        assert event.entity_type == "asset"
        assert event.entity_id == asset.id
        assert event.payload["asset_fqn"] == asset.fqn
        assert event.payload["contract_version"] == "2.1.0"
        assert event.payload["guarantees_checked"] is True

    @pytest.mark.asyncio
    async def test_preflight_logs_consumer_type(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Consumer type is recorded in the audit event payload."""
        asset, _ = asset_with_contract

        await client.get(
            f"/api/v1/assets/{asset.fqn}/preflight",
            params={"consumer_type": "agent"},
        )

        from sqlalchemy import select

        result = await session.execute(
            select(AuditEventDB).where(AuditEventDB.action == "preflight.checked")
        )
        event = result.scalars().first()
        assert event is not None
        assert event.payload["consumer_type"] == "agent"

    @pytest.mark.asyncio
    async def test_preflight_events_queryable_via_audit_api(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Consumption events are queryable via GET /api/v1/audit/events."""
        asset, _ = asset_with_contract

        # Make a preflight call to generate the event
        await client.get(f"/api/v1/assets/{asset.fqn}/preflight")

        # Query via audit API with action filter
        response = await client.get(
            "/api/v1/audit/events",
            params={"action": "preflight.checked"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(r["action"] == "preflight.checked" for r in data["results"])

    @pytest.mark.asyncio
    async def test_preflight_events_in_entity_history(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Consumption events appear in entity history."""
        asset, _ = asset_with_contract

        # Make a preflight call
        await client.get(f"/api/v1/assets/{asset.fqn}/preflight")

        # Check entity history
        response = await client.get(f"/api/v1/audit/entities/asset/{asset.id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        actions = [r["action"] for r in data["results"]]
        assert "preflight.checked" in actions

    @pytest.mark.asyncio
    async def test_multiple_preflight_calls_log_multiple_events(
        self,
        session: AsyncSession,
        client: AsyncClient,
        asset_with_contract: tuple[AssetDB, ContractDB],
    ):
        """Each preflight call creates a separate audit event."""
        asset, _ = asset_with_contract

        # Make 3 preflight calls
        for _ in range(3):
            response = await client.get(f"/api/v1/assets/{asset.fqn}/preflight")
            assert response.status_code == 200

        from sqlalchemy import select

        result = await session.execute(
            select(AuditEventDB).where(AuditEventDB.action == "preflight.checked")
        )
        events = result.scalars().all()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_preflight_no_event_on_not_found(
        self,
        session: AsyncSession,
        client: AsyncClient,
    ):
        """No audit event is logged when the asset is not found."""
        response = await client.get("/api/v1/assets/nonexistent.fqn/preflight")
        assert response.status_code == 404

        from sqlalchemy import select

        result = await session.execute(
            select(AuditEventDB).where(AuditEventDB.action == "preflight.checked")
        )
        events = result.scalars().all()
        assert len(events) == 0


class TestPreflightDeprecatedFallback:
    """Tests for preflight fallback to deprecated contracts."""

    @pytest.mark.asyncio
    async def test_preflight_returns_deprecated_contract_with_caveat(
        self,
        session: AsyncSession,
        client: AsyncClient,
        team: TeamDB,
    ):
        """When only a deprecated contract exists, return it with a deprecation caveat."""
        asset = AssetDB(
            fqn="warehouse.legacy.old_table",
            owner_team_id=team.id,
            metadata_={},
        )
        session.add(asset)
        await session.flush()

        contract = ContractDB(
            asset_id=asset.id,
            version="1.0.0",
            schema_def={"type": "object", "properties": {"id": {"type": "string"}}},
            schema_format=SchemaFormat.JSON_SCHEMA,
            compatibility_mode=CompatibilityMode.BACKWARD,
            guarantees=None,
            status=ContractStatus.DEPRECATED,
            published_by=team.id,
        )
        session.add(contract)
        await session.flush()

        response = await client.get("/api/v1/assets/warehouse.legacy.old_table/preflight")
        assert response.status_code == 200
        data = response.json()
        assert data["contract_version"] == "1.0.0"
        assert any("deprecated" in c.lower() for c in data["caveats"])

    @pytest.mark.asyncio
    async def test_preflight_prefers_active_over_deprecated(
        self,
        session: AsyncSession,
        client: AsyncClient,
        team: TeamDB,
    ):
        """When both active and deprecated contracts exist, return the active one."""
        asset = AssetDB(
            fqn="warehouse.mixed.both_statuses",
            owner_team_id=team.id,
            metadata_={},
        )
        session.add(asset)
        await session.flush()

        deprecated = ContractDB(
            asset_id=asset.id,
            version="1.0.0",
            schema_def={"type": "object", "properties": {"id": {"type": "string"}}},
            schema_format=SchemaFormat.JSON_SCHEMA,
            compatibility_mode=CompatibilityMode.BACKWARD,
            guarantees=None,
            status=ContractStatus.DEPRECATED,
            published_by=team.id,
        )
        active = ContractDB(
            asset_id=asset.id,
            version="2.0.0",
            schema_def={"type": "object", "properties": {"id": {"type": "string"}}},
            schema_format=SchemaFormat.JSON_SCHEMA,
            compatibility_mode=CompatibilityMode.BACKWARD,
            guarantees=None,
            status=ContractStatus.ACTIVE,
            published_by=team.id,
        )
        session.add_all([deprecated, active])
        await session.flush()

        response = await client.get("/api/v1/assets/warehouse.mixed.both_statuses/preflight")
        assert response.status_code == 200
        data = response.json()
        assert data["contract_version"] == "2.0.0"
        assert not any("deprecated" in c.lower() for c in data["caveats"])


class TestPreflightNoGuarantees:
    """Tests for preflight when contract has no guarantees or freshness SLA."""

    @pytest.mark.asyncio
    async def test_preflight_no_guarantees(
        self,
        session: AsyncSession,
        client: AsyncClient,
        team: TeamDB,
    ):
        """Contract with no guarantees returns null guarantees and unknown freshness."""
        asset = AssetDB(
            fqn="warehouse.raw.events",
            owner_team_id=team.id,
            metadata_={},
        )
        session.add(asset)
        await session.flush()

        contract = ContractDB(
            asset_id=asset.id,
            version="1.0.0",
            schema_def={"type": "object", "properties": {"id": {"type": "string"}}},
            schema_format=SchemaFormat.JSON_SCHEMA,
            compatibility_mode=CompatibilityMode.NONE,
            guarantees=None,
            status=ContractStatus.ACTIVE,
            published_by=team.id,
        )
        session.add(contract)
        await session.flush()

        response = await client.get("/api/v1/assets/warehouse.raw.events/preflight")
        assert response.status_code == 200
        data = response.json()
        assert data["guarantees"] is None
        assert data["fresh"] is None
        assert data["freshness_sla"] is None
        assert data["compatibility_mode"] == "none"
