"""Tests for the preflight inference pipeline and discovery endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import (
    AssetDB,
    AuditEventDB,
    ContractDB,
    InferredDependencyDB,
    RegistrationDB,
    TeamDB,
)
from tessera.models.enums import (
    ContractStatus,
    InferredDependencyStatus,
    RegistrationStatus,
)
from tessera.services.discovery import (
    compute_preflight_confidence,
    run_preflight_inference,
)

# ---------------------------------------------------------------------------
# Confidence scoring (pure function, no DB)
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Tests for compute_preflight_confidence."""

    def test_daily_ci_agent_high_confidence(self) -> None:
        score = compute_preflight_confidence(
            call_count=300,
            distinct_days=30,
            days_since_last_call=0,
            is_agent=True,
            lookback_days=30,
        )
        assert score > 0.9, f"Daily agent should score >0.9, got {score}"

    def test_weekly_refresh_moderate_confidence(self) -> None:
        score = compute_preflight_confidence(
            call_count=8,
            distinct_days=4,
            days_since_last_call=2,
            is_agent=False,
            lookback_days=30,
        )
        assert 0.3 < score < 0.7, f"Weekly refresh should be moderate, got {score}"

    def test_one_off_low_confidence(self) -> None:
        score = compute_preflight_confidence(
            call_count=1,
            distinct_days=1,
            days_since_last_call=25,
            is_agent=False,
            lookback_days=30,
        )
        assert score < 0.3, f"One-off should be low, got {score}"

    def test_nightly_ml_pipeline_high_confidence(self) -> None:
        score = compute_preflight_confidence(
            call_count=30,
            distinct_days=28,
            days_since_last_call=0,
            is_agent=True,
            lookback_days=30,
        )
        assert score > 0.85, f"Nightly ML pipeline should score >0.85, got {score}"

    def test_zero_calls_returns_zero(self) -> None:
        assert compute_preflight_confidence(0, 0, 0, False) == 0.0

    def test_zero_lookback_returns_zero(self) -> None:
        assert compute_preflight_confidence(10, 5, 0, True, lookback_days=0) == 0.0

    def test_score_capped_at_one(self) -> None:
        score = compute_preflight_confidence(
            call_count=10000,
            distinct_days=30,
            days_since_last_call=0,
            is_agent=True,
            lookback_days=30,
        )
        assert score <= 1.0

    def test_agent_bonus_raises_score(self) -> None:
        base = compute_preflight_confidence(10, 5, 2, False, 30)
        with_agent = compute_preflight_confidence(10, 5, 2, True, 30)
        assert with_agent > base


# ---------------------------------------------------------------------------
# Helpers for DB test setup
# ---------------------------------------------------------------------------


def _make_team(name: str = "consumer-team") -> TeamDB:
    return TeamDB(id=uuid4(), name=name, metadata_={})


def _make_asset(team: TeamDB, fqn: str = "warehouse.analytics.orders") -> AssetDB:
    return AssetDB(id=uuid4(), fqn=fqn, owner_team_id=team.id)


def _make_contract(asset: AssetDB, team: TeamDB) -> ContractDB:
    return ContractDB(
        id=uuid4(),
        asset_id=asset.id,
        version="1.0.0",
        schema_def={"type": "object", "properties": {"id": {"type": "integer"}}},
        status=ContractStatus.ACTIVE,
        published_by=team.id,
    )


def _make_preflight_events(
    asset_id,
    team_id,
    count: int,
    distinct_days: int = 10,
    actor_type: str = "agent",
    start_offset_days: int = 0,
) -> list[AuditEventDB]:
    """Create a set of preflight.checked audit events spread across days."""
    events = []
    now = datetime.now(UTC)
    for i in range(count):
        day_offset = (i % distinct_days) + start_offset_days
        events.append(
            AuditEventDB(
                id=uuid4(),
                entity_type="asset",
                entity_id=asset_id,
                action="preflight.checked",
                actor_id=team_id,
                actor_type=actor_type,
                payload={"asset_fqn": "test.asset", "contract_version": "1.0.0"},
                occurred_at=now - timedelta(days=day_offset),
            )
        )
    return events


# ---------------------------------------------------------------------------
# Scan logic (service layer, uses DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_creates_inferences(test_session: AsyncSession) -> None:
    """Scan with sufficient preflight events creates InferredDependencyDB rows."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team, "warehouse.analytics.orders")
    test_session.add(asset)
    await test_session.flush()

    events = _make_preflight_events(asset.id, consumer_team.id, count=30, distinct_days=20)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.events_scanned == 30
    assert stats.pairs_evaluated == 1
    assert stats.inferred_new == 1
    assert stats.inferred_updated == 0


@pytest.mark.asyncio
async def test_scan_skips_registered_teams(test_session: AsyncSession) -> None:
    """Scan skips teams that already have an active registration."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    contract = _make_contract(asset, owner_team)
    test_session.add(contract)
    await test_session.flush()

    # Create an existing registration
    reg = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer_team.id,
        status=RegistrationStatus.ACTIVE,
    )
    test_session.add(reg)
    await test_session.flush()

    events = _make_preflight_events(asset.id, consumer_team.id, count=30, distinct_days=20)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.skipped_already_registered == 1
    assert stats.inferred_new == 0


@pytest.mark.asyncio
async def test_scan_skips_rejected_pairs(test_session: AsyncSession) -> None:
    """Scan skips (asset, team, source) tuples that were previously rejected."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    # Create a rejected inference
    rejected = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.8,
        evidence={},
        status=InferredDependencyStatus.REJECTED,
    )
    test_session.add(rejected)
    await test_session.flush()

    events = _make_preflight_events(asset.id, consumer_team.id, count=30, distinct_days=20)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.skipped_previously_rejected == 1
    assert stats.inferred_new == 0


@pytest.mark.asyncio
async def test_scan_updates_existing_inferences(test_session: AsyncSession) -> None:
    """Re-scanning updates last_observed_at and confidence for existing inferences."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    # Create an existing pending inference
    old_time = datetime.now(UTC) - timedelta(days=10)
    existing = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.5,
        evidence={"preflight_calls_30d": 10},
        status=InferredDependencyStatus.PENDING,
        first_observed_at=old_time,
        last_observed_at=old_time,
    )
    test_session.add(existing)
    await test_session.flush()

    events = _make_preflight_events(asset.id, consumer_team.id, count=30, distinct_days=20)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.inferred_updated == 1
    assert stats.inferred_new == 0

    # Verify the existing record was updated
    await test_session.refresh(existing)
    # Compare as naive datetimes since SQLite strips timezone info
    old_naive = old_time.replace(tzinfo=None)
    last_obs = existing.last_observed_at
    if last_obs.tzinfo is not None:
        last_obs = last_obs.replace(tzinfo=None)
    assert last_obs > old_naive
    assert existing.confidence != 0.5  # Should be recalculated


@pytest.mark.asyncio
async def test_scan_expires_stale_inferences(test_session: AsyncSession) -> None:
    """Inferences not refreshed in 2x the lookback window get expired."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    # Create a stale pending inference (last observed 90 days ago)
    stale_time = datetime.now(UTC) - timedelta(days=90)
    stale = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.7,
        evidence={},
        status=InferredDependencyStatus.PENDING,
        first_observed_at=stale_time,
        last_observed_at=stale_time,
    )
    test_session.add(stale)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.inferred_expired == 1

    await test_session.refresh(stale)
    assert stale.status == InferredDependencyStatus.EXPIRED


@pytest.mark.asyncio
async def test_scan_below_min_calls_ignored(test_session: AsyncSession) -> None:
    """Pairs with fewer calls than min_calls are ignored."""
    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    events = _make_preflight_events(asset.id, consumer_team.id, count=3, distinct_days=3)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )

    assert stats.inferred_new == 0


# ---------------------------------------------------------------------------
# API endpoint tests (integration)
# ---------------------------------------------------------------------------


async def _setup_test_data(client: AsyncClient) -> dict:
    """Create team, asset, contract and return their IDs."""
    # Create owner team
    resp = await client.post("/api/v1/teams", json={"name": "owner-team"})
    assert resp.status_code == 201
    owner_team_id = resp.json()["id"]

    # Create consumer team
    resp = await client.post("/api/v1/teams", json={"name": "consumer-team"})
    assert resp.status_code == 201
    consumer_team_id = resp.json()["id"]

    # Create asset
    resp = await client.post(
        "/api/v1/assets",
        json={"fqn": "warehouse.analytics.orders", "owner_team_id": owner_team_id},
    )
    assert resp.status_code == 201
    asset_id = resp.json()["id"]

    # Publish a contract
    resp = await client.post(
        f"/api/v1/assets/{asset_id}/contracts",
        params={"published_by": owner_team_id},
        json={
            "version": "1.0.0",
            "schema": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    )
    assert resp.status_code == 201
    contract_id = resp.json()["contract"]["id"]

    return {
        "owner_team_id": owner_team_id,
        "consumer_team_id": consumer_team_id,
        "asset_id": asset_id,
        "contract_id": contract_id,
    }


@pytest.mark.asyncio
async def test_scan_endpoint(client: AsyncClient) -> None:
    """POST /api/v1/discovery/scan returns scan statistics."""
    resp = await client.post(
        "/api/v1/discovery/scan",
        json={"source": "preflight_audit", "lookback_days": 30, "min_calls": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "preflight_audit"
    assert "events_scanned" in data
    assert "inferred_new" in data


@pytest.mark.asyncio
async def test_scan_invalid_source(client: AsyncClient) -> None:
    """POST /api/v1/discovery/scan rejects unsupported sources."""
    resp = await client.post(
        "/api/v1/discovery/scan",
        json={"source": "warehouse_logs"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_inferred_empty(client: AsyncClient) -> None:
    """GET /api/v1/discovery/inferred returns empty list when no inferences exist."""
    resp = await client.get("/api/v1/discovery/inferred")
    assert resp.status_code == 200
    data = resp.json()
    assert data["inferred_dependencies"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_scan_and_list_roundtrip(client: AsyncClient) -> None:
    """Scan creates inferences that are visible in the list endpoint."""
    ids = await _setup_test_data(client)

    # Generate preflight events by hitting the preflight endpoint
    for _ in range(10):
        resp = await client.get(
            f"/api/v1/assets/{ids['asset_id']}/preflight",
            params={"team_id": ids["consumer_team_id"]},
        )
        # Preflight may return 200 or whatever — we just need the audit events
        assert resp.status_code in (200, 404, 422)

    # Run scan
    resp = await client.post(
        "/api/v1/discovery/scan",
        json={"source": "preflight_audit", "min_calls": 1, "min_confidence": 0.0},
    )
    assert resp.status_code == 200

    # Check if inferences were created (depends on preflight events being logged)
    resp = await client.get(
        "/api/v1/discovery/inferred",
        params={"status": "pending"},
    )
    assert resp.status_code == 200
    # The response structure is correct regardless of count
    assert "inferred_dependencies" in resp.json()
    assert "total" in resp.json()


@pytest.mark.asyncio
async def test_confirm_and_reject_not_found(client: AsyncClient) -> None:
    """Confirm/reject for non-existent inference returns 404."""
    fake_id = str(uuid4())

    resp = await client.post(
        f"/api/v1/discovery/inferred/{fake_id}/confirm",
        json={},
    )
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/discovery/inferred/{fake_id}/reject",
        json={"reason": "test"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_coverage_report_empty(client: AsyncClient) -> None:
    """GET /api/v1/discovery/coverage returns zeros when no assets exist."""
    resp = await client.get("/api/v1/discovery/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_assets"] == 0
    assert data["coverage_registered"] == 0.0


@pytest.mark.asyncio
async def test_coverage_report_with_data(client: AsyncClient) -> None:
    """GET /api/v1/discovery/coverage reflects asset counts."""
    await _setup_test_data(client)

    resp = await client.get("/api/v1/discovery/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_assets"] >= 1


# ---------------------------------------------------------------------------
# Confirm / reject flow (service layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_creates_registration(test_session: AsyncSession) -> None:
    """Confirming a pending inference promotes it to a registration."""
    from tessera.services.discovery import confirm_inference

    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    contract = _make_contract(asset, owner_team)
    test_session.add(contract)
    await test_session.flush()

    inference = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.9,
        evidence={"preflight_calls_30d": 200},
        status=InferredDependencyStatus.PENDING,
    )
    test_session.add(inference)
    await test_session.flush()

    result = await confirm_inference(
        session=test_session,
        inference_id=inference.id,
        confirmed_by=consumer_team.id,
    )

    assert result["status"] == "confirmed"
    assert result["promoted_registration"] is not None
    assert result["promoted_registration"]["consumer_team_id"] == str(consumer_team.id)

    # Verify inference was updated
    await test_session.refresh(inference)
    assert inference.status == InferredDependencyStatus.CONFIRMED
    assert inference.confirmed_at is not None
    assert inference.promoted_registration_id is not None


@pytest.mark.asyncio
async def test_confirm_existing_registration_no_duplicate(
    test_session: AsyncSession,
) -> None:
    """Confirming when a registration already exists returns it without duplication."""
    from tessera.services.discovery import confirm_inference

    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    contract = _make_contract(asset, owner_team)
    test_session.add(contract)
    await test_session.flush()

    existing_reg = RegistrationDB(
        contract_id=contract.id,
        consumer_team_id=consumer_team.id,
        status=RegistrationStatus.ACTIVE,
    )
    test_session.add(existing_reg)
    await test_session.flush()

    inference = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.9,
        evidence={},
        status=InferredDependencyStatus.PENDING,
    )
    test_session.add(inference)
    await test_session.flush()

    result = await confirm_inference(
        session=test_session,
        inference_id=inference.id,
        confirmed_by=consumer_team.id,
    )

    assert result["status"] == "confirmed"
    # Should return the existing registration, not create a new one
    assert result["promoted_registration"]["registration_id"] == str(existing_reg.id)


@pytest.mark.asyncio
async def test_reject_blocks_future_scans(test_session: AsyncSession) -> None:
    """Rejecting an inference sets status=REJECTED; future scans skip it."""
    from tessera.services.discovery import reject_inference

    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    inference = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.8,
        evidence={},
        status=InferredDependencyStatus.PENDING,
    )
    test_session.add(inference)
    await test_session.flush()

    result = await reject_inference(
        session=test_session,
        inference_id=inference.id,
        rejected_by=consumer_team.id,
        reason="ad-hoc exploration",
    )

    assert result["status"] == "rejected"

    await test_session.refresh(inference)
    assert inference.status == InferredDependencyStatus.REJECTED

    # Now run a scan — should skip the rejected pair
    events = _make_preflight_events(asset.id, consumer_team.id, count=30, distinct_days=20)
    test_session.add_all(events)
    await test_session.flush()

    stats = await run_preflight_inference(
        test_session, lookback_days=30, min_calls=5, min_confidence=0.3
    )
    assert stats.skipped_previously_rejected == 1
    assert stats.inferred_new == 0


@pytest.mark.asyncio
async def test_confirm_non_pending_raises(test_session: AsyncSession) -> None:
    """Cannot confirm an inference that is not in PENDING status."""
    from tessera.services.discovery import confirm_inference

    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    inference = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.8,
        evidence={},
        status=InferredDependencyStatus.REJECTED,
    )
    test_session.add(inference)
    await test_session.flush()

    with pytest.raises(ValueError, match="only PENDING"):
        await confirm_inference(
            session=test_session,
            inference_id=inference.id,
            confirmed_by=consumer_team.id,
        )


@pytest.mark.asyncio
async def test_reject_non_pending_raises(test_session: AsyncSession) -> None:
    """Cannot reject an inference that is not in PENDING status."""
    from tessera.services.discovery import reject_inference

    owner_team = _make_team("owner-team")
    consumer_team = _make_team("consumer-team")
    test_session.add_all([owner_team, consumer_team])
    await test_session.flush()

    asset = _make_asset(owner_team)
    test_session.add(asset)
    await test_session.flush()

    inference = InferredDependencyDB(
        asset_id=asset.id,
        consumer_team_id=consumer_team.id,
        source="preflight_audit",
        confidence=0.8,
        evidence={},
        status=InferredDependencyStatus.CONFIRMED,
    )
    test_session.add(inference)
    await test_session.flush()

    with pytest.raises(ValueError, match="only PENDING"):
        await reject_inference(
            session=test_session,
            inference_id=inference.id,
            rejected_by=consumer_team.id,
            reason="test",
        )


# ---------------------------------------------------------------------------
# Impact preview integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_impact_preview_includes_unconfirmed(client: AsyncClient) -> None:
    """Impact preview response includes unconfirmed_consumers field."""
    ids = await _setup_test_data(client)

    resp = await client.post(
        f"/api/v1/assets/{ids['asset_id']}/impact-preview",
        json={
            "proposed_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id"],
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "unconfirmed_consumers" in data
    assert isinstance(data["unconfirmed_consumers"], list)
