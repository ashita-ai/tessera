"""Tests for OTEL dependency discovery (Spec-007)."""

import math
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    OtelSyncConfigDB,
    RepoDB,
    ServiceDB,
    TeamDB,
)
from tessera.models.enums import DependencySource, DependencyType, OtelBackendType
from tessera.services.otel import (
    build_reconciliation_report,
    compute_confidence,
    fetch_jaeger_dependencies,
    mark_stale_dependencies,
    resolve_service_name,
    run_sync,
    upsert_otel_dependency,
    validate_otel_endpoint_host,
)


@pytest.fixture(autouse=True)
def _bypass_ssrf_validation_in_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch SSRF validation at the API layer so test URLs like jaeger:16686 pass.

    Direct SSRF unit tests import and call validate_otel_endpoint_host from
    tessera.services.otel, so they still exercise the real implementation.
    """

    async def _allow_all(url: str) -> tuple[bool, str]:
        return True, ""

    monkeypatch.setattr("tessera.api.otel.validate_otel_endpoint_host", _allow_all)


# ── Confidence scoring ────────────────────────────────────────


class TestComputeConfidence:
    """Tests for the confidence scoring function."""

    def test_zero_calls_returns_zero_count_score(self) -> None:
        """Zero calls should contribute 0 to the count component."""
        result = compute_confidence(call_count=0, syncs_seen=1, total_syncs=1)
        # count_score = min(log10(1)/4, 1.0) = 0.0
        # consistency = 1/1 = 1.0
        # 0.6*0 + 0.4*1 = 0.4
        assert result == 0.4

    def test_ten_thousand_calls_maxes_count_score(self) -> None:
        """10k calls should max out the count component at 1.0."""
        result = compute_confidence(call_count=10000, syncs_seen=1, total_syncs=1)
        # count_score = min(log10(10000)/4, 1.0) = min(4/4, 1.0) = 1.0
        # consistency = 1/1 = 1.0
        # 0.6*1 + 0.4*1 = 1.0
        assert result == 1.0

    def test_hundred_calls_partial_count_score(self) -> None:
        """100 calls should give a partial count score."""
        result = compute_confidence(call_count=100, syncs_seen=1, total_syncs=1)
        expected_count = min(math.log10(100) / 4.0, 1.0)  # 2/4 = 0.5
        expected = round(0.6 * expected_count + 0.4 * 1.0, 2)
        assert result == expected

    def test_consistency_affects_score(self) -> None:
        """Seeing the edge in fewer syncs should lower the score."""
        full = compute_confidence(call_count=1000, syncs_seen=10, total_syncs=10)
        half = compute_confidence(call_count=1000, syncs_seen=5, total_syncs=10)
        assert full > half

    def test_zero_total_syncs_no_division_error(self) -> None:
        """Zero total syncs should not cause ZeroDivisionError."""
        result = compute_confidence(call_count=100, syncs_seen=0, total_syncs=0)
        assert 0.0 <= result <= 1.0

    def test_result_bounded(self) -> None:
        """Confidence should always be between 0 and 1."""
        for call_count in [0, 1, 10, 100, 1000, 10000, 1000000]:
            for syncs_seen, total in [(0, 0), (1, 10), (10, 10)]:
                result = compute_confidence(call_count, syncs_seen, total)
                assert 0.0 <= result <= 1.0


# ── Jaeger client ─────────────────────────────────────────────


class TestFetchJaegerDependencies:
    """Tests for the Jaeger API client."""

    @pytest.fixture
    def config(self) -> OtelSyncConfigDB:
        return OtelSyncConfigDB(
            id=uuid4(),
            name="test-jaeger",
            backend_type=OtelBackendType.JAEGER,
            endpoint_url="http://jaeger:16686",
            lookback_seconds=86400,
            poll_interval_seconds=3600,
            min_call_count=10,
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_parses_flat_array(self, config: OtelSyncConfigDB) -> None:
        """Jaeger may return a flat JSON array."""
        mock_response = httpx.Response(
            200,
            json=[
                {"parent": "svc-a", "child": "svc-b", "callCount": 100},
                {"parent": "svc-a", "child": "svc-c", "callCount": 50},
            ],
            request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        edges = await fetch_jaeger_dependencies(config, http_client=mock_client)
        assert len(edges) == 2
        assert edges[0].parent == "svc-a"
        assert edges[0].child == "svc-b"
        assert edges[0].call_count == 100

    @pytest.mark.asyncio
    async def test_parses_data_wrapper(self, config: OtelSyncConfigDB) -> None:
        """Jaeger may return {"data": [...]}."""
        mock_response = httpx.Response(
            200,
            json={"data": [{"parent": "svc-x", "child": "svc-y", "callCount": 200}]},
            request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        edges = await fetch_jaeger_dependencies(config, http_client=mock_client)
        assert len(edges) == 1
        assert edges[0].parent == "svc-x"
        assert edges[0].call_count == 200

    @pytest.mark.asyncio
    async def test_passes_auth_header(self, config: OtelSyncConfigDB) -> None:
        """Auth header should be forwarded to Jaeger."""
        config.auth_header = "Bearer test-token"
        mock_response = httpx.Response(
            200,
            json=[],
            request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        await fetch_jaeger_dependencies(config, http_client=mock_client)

        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, config: OtelSyncConfigDB) -> None:
        """HTTP errors from Jaeger should propagate."""
        mock_response = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_jaeger_dependencies(config, http_client=mock_client)

    @pytest.mark.asyncio
    async def test_handles_float_call_count(self, config: OtelSyncConfigDB) -> None:
        """callCount as a JSON float (e.g. 150.0) should parse without error."""
        mock_response = httpx.Response(
            200,
            json=[{"parent": "svc-a", "child": "svc-b", "callCount": 150.0}],
            request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        edges = await fetch_jaeger_dependencies(config, http_client=mock_client)
        assert len(edges) == 1
        assert edges[0].call_count == 150


# ── Service resolution ────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_service_name_found(test_session) -> None:
    """Should resolve a known otel_service_name to a ServiceDB."""
    team = TeamDB(name="team-a")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(name="repo-a", git_url="https://git.example.com/a", owner_team_id=team.id)
    test_session.add(repo)
    await test_session.flush()

    svc = ServiceDB(
        name="order-service",
        repo_id=repo.id,
        otel_service_name="order-svc",
    )
    test_session.add(svc)
    await test_session.flush()

    resolved = await resolve_service_name(test_session, "order-svc")
    assert resolved is not None
    assert resolved.id == svc.id


@pytest.mark.asyncio
async def test_resolve_service_name_not_found(test_session) -> None:
    """Should return None for an unknown otel_service_name."""
    resolved = await resolve_service_name(test_session, "nonexistent-svc")
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_service_name_ignores_deleted(test_session) -> None:
    """Should not resolve a soft-deleted service."""
    team = TeamDB(name="team-b")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(name="repo-b", git_url="https://git.example.com/b", owner_team_id=team.id)
    test_session.add(repo)
    await test_session.flush()

    svc = ServiceDB(
        name="deleted-svc",
        repo_id=repo.id,
        otel_service_name="deleted-otel",
        deleted_at=datetime.now(UTC),
    )
    test_session.add(svc)
    await test_session.flush()

    resolved = await resolve_service_name(test_session, "deleted-otel")
    assert resolved is None


# ── Dependency upsert ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_creates_new_dependency(test_session) -> None:
    """Should create a new OTEL dependency when none exists."""
    team = TeamDB(name="team-upsert")
    test_session.add(team)
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="upsert-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    asset_a = AssetDB(fqn="svc-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="svc-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    now = datetime.now(UTC)
    dep, created = await upsert_otel_dependency(
        test_session,
        asset_a.id,
        asset_b.id,
        call_count=500,
        confidence=0.8,
        now=now,
        config_id=config.id,
    )

    assert created is True
    assert dep.source == DependencySource.OTEL
    assert dep.confidence == 0.8
    assert dep.call_count == 500
    assert dep.syncs_seen == 1
    assert dep.otel_config_id == config.id


@pytest.mark.asyncio
async def test_upsert_updates_existing_otel_dependency(test_session) -> None:
    """Should update call_count and confidence for existing OTEL deps."""
    team = TeamDB(name="team-upsert2")
    test_session.add(team)
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="upsert2-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    asset_a = AssetDB(fqn="svc-a2.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="svc-b2.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    now = datetime.now(UTC)
    # First upsert creates
    dep1, created1 = await upsert_otel_dependency(
        test_session,
        asset_a.id,
        asset_b.id,
        call_count=100,
        confidence=0.5,
        now=now,
        config_id=config.id,
    )
    assert created1 is True

    # Second upsert updates
    later = now + timedelta(hours=1)
    dep2, created2 = await upsert_otel_dependency(
        test_session,
        asset_a.id,
        asset_b.id,
        call_count=500,
        confidence=0.9,
        now=later,
        config_id=config.id,
    )
    assert created2 is False
    assert dep2.id == dep1.id
    assert dep2.call_count == 500
    assert dep2.confidence == 0.9
    assert dep2.last_observed_at == later
    assert dep2.syncs_seen == 2  # Incremented from 1 to 2


@pytest.mark.asyncio
async def test_upsert_creates_otel_row_alongside_manual(test_session) -> None:
    """OTEL upsert should create a separate OTEL row when a manual dep exists."""
    team = TeamDB(name="team-manual")
    test_session.add(team)
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="manual-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    asset_a = AssetDB(fqn="svc-manual-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="svc-manual-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    # Create a manual dependency first
    manual_dep = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.MANUAL,
    )
    test_session.add(manual_dep)
    await test_session.flush()

    # OTEL upsert should create a new OTEL row, not touch the manual one
    now = datetime.now(UTC)
    dep, created = await upsert_otel_dependency(
        test_session,
        asset_a.id,
        asset_b.id,
        call_count=999,
        confidence=0.99,
        now=now,
        config_id=config.id,
    )
    assert created is True
    assert dep.source == DependencySource.OTEL
    assert dep.call_count == 999
    assert dep.otel_config_id == config.id

    # Manual dep should be untouched
    await test_session.refresh(manual_dep)
    assert manual_dep.source == DependencySource.MANUAL
    assert manual_dep.call_count is None


# ── Stale detection ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_stale_dependencies(test_session) -> None:
    """Should demote confidence of OTEL deps not observed recently."""
    team = TeamDB(name="team-stale")
    test_session.add(team)
    await test_session.flush()

    asset_a = AssetDB(fqn="stale-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="stale-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="stale-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=3600,  # 1 hour
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    # Dependency observed 5 hours ago (stale threshold = 3 * 1h = 3h)
    old_time = datetime.now(UTC) - timedelta(hours=5)
    dep = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.8,
        last_observed_at=old_time,
        call_count=100,
        otel_config_id=config.id,
    )
    test_session.add(dep)
    await test_session.flush()

    now = datetime.now(UTC)
    stale_count = await mark_stale_dependencies(test_session, config, now)
    assert stale_count == 1

    await test_session.refresh(dep)
    assert dep.confidence == 0.01


@pytest.mark.asyncio
async def test_mark_stale_skips_recent_dependencies(test_session) -> None:
    """Should not mark recently observed deps as stale."""
    team = TeamDB(name="team-fresh")
    test_session.add(team)
    await test_session.flush()

    asset_a = AssetDB(fqn="fresh-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="fresh-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="fresh-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=3600,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    # Dependency observed 1 hour ago (stale threshold = 3h)
    recent = datetime.now(UTC) - timedelta(hours=1)
    dep = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.8,
        last_observed_at=recent,
        call_count=100,
        otel_config_id=config.id,
    )
    test_session.add(dep)
    await test_session.flush()

    now = datetime.now(UTC)
    stale_count = await mark_stale_dependencies(test_session, config, now)
    assert stale_count == 0


# ── Full sync ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_sync_creates_dependencies(test_session) -> None:
    """Full sync should create deps for resolved edges above min_call_count."""
    team = TeamDB(name="team-sync")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(name="repo-sync", git_url="https://git.example.com/sync", owner_team_id=team.id)
    test_session.add(repo)
    await test_session.flush()

    svc_a = ServiceDB(name="svc-a", repo_id=repo.id, otel_service_name="order-svc")
    svc_b = ServiceDB(name="svc-b", repo_id=repo.id, otel_service_name="payment-svc")
    test_session.add_all([svc_a, svc_b])
    await test_session.flush()

    asset_a = AssetDB(fqn="order-svc.api", owner_team_id=team.id, service_id=svc_a.id)
    asset_b = AssetDB(fqn="payment-svc.api", owner_team_id=team.id, service_id=svc_b.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="sync-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    # Mock Jaeger response
    mock_response = httpx.Response(
        200,
        json=[{"parent": "order-svc", "child": "payment-svc", "callCount": 5000}],
        request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await run_sync(test_session, config, http_client=mock_client)

    assert result.edges_fetched == 1
    assert result.edges_resolved == 1
    assert result.edges_created == 1
    assert result.edges_updated == 0
    assert len(result.unresolved_services) == 0


@pytest.mark.asyncio
async def test_run_sync_skips_below_min_call_count(test_session) -> None:
    """Edges below min_call_count should be skipped."""
    team = TeamDB(name="team-skip")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(name="repo-skip", git_url="https://git.example.com/skip", owner_team_id=team.id)
    test_session.add(repo)
    await test_session.flush()

    svc_a = ServiceDB(name="svc-skip-a", repo_id=repo.id, otel_service_name="low-a")
    svc_b = ServiceDB(name="svc-skip-b", repo_id=repo.id, otel_service_name="low-b")
    test_session.add_all([svc_a, svc_b])
    await test_session.flush()

    asset_a = AssetDB(fqn="low-a.api", owner_team_id=team.id, service_id=svc_a.id)
    asset_b = AssetDB(fqn="low-b.api", owner_team_id=team.id, service_id=svc_b.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="skip-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=100,  # High threshold
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    mock_response = httpx.Response(
        200,
        json=[{"parent": "low-a", "child": "low-b", "callCount": 5}],  # Below threshold
        request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await run_sync(test_session, config, http_client=mock_client)
    assert result.edges_fetched == 1
    assert result.edges_resolved == 0
    assert result.edges_created == 0


@pytest.mark.asyncio
async def test_run_sync_reports_unresolved_services(test_session) -> None:
    """Unresolved service names should appear in the sync result."""
    config = OtelSyncConfigDB(
        name="unresolved-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    mock_response = httpx.Response(
        200,
        json=[{"parent": "unknown-a", "child": "unknown-b", "callCount": 5000}],
        request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await run_sync(test_session, config, http_client=mock_client)
    assert result.edges_fetched == 1
    assert result.edges_resolved == 0
    assert len(result.unresolved_services) == 2

    names = {u.otel_service_name for u in result.unresolved_services}
    assert names == {"unknown-a", "unknown-b"}


# ── Reconciliation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_report(test_session) -> None:
    """Should classify deps into declared_only, observed_only, and both."""
    team = TeamDB(name="team-recon")
    test_session.add(team)
    await test_session.flush()

    asset_a = AssetDB(fqn="recon-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="recon-b.api", owner_team_id=team.id)
    asset_c = AssetDB(fqn="recon-c.api", owner_team_id=team.id)
    asset_d = AssetDB(fqn="recon-d.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b, asset_c, asset_d])
    await test_session.flush()

    # Manual only: a → b
    test_session.add(
        AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_b.id,
            dependency_type=DependencyType.CONSUMES,
            source=DependencySource.MANUAL,
        )
    )
    # OTEL only: c → d
    test_session.add(
        AssetDependencyDB(
            dependent_asset_id=asset_c.id,
            dependency_asset_id=asset_d.id,
            dependency_type=DependencyType.CONSUMES,
            source=DependencySource.OTEL,
            confidence=0.85,
            call_count=3000,
            last_observed_at=datetime.now(UTC),
        )
    )
    # Both manual and OTEL: a → d (two separate rows, same edge, different source)
    test_session.add(
        AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_d.id,
            dependency_type=DependencyType.CONSUMES,
            source=DependencySource.MANUAL,
        )
    )
    test_session.add(
        AssetDependencyDB(
            dependent_asset_id=asset_a.id,
            dependency_asset_id=asset_d.id,
            dependency_type=DependencyType.CONSUMES,
            source=DependencySource.OTEL,
            confidence=0.95,
            call_count=10000,
            last_observed_at=datetime.now(UTC),
        )
    )
    await test_session.flush()

    report = await build_reconciliation_report(test_session)

    assert len(report.declared_only) >= 1
    assert len(report.observed_only) >= 1
    assert len(report.both) >= 1

    # Check that a→b is in declared_only
    declared_pairs = {
        (item.dependent_asset_id, item.dependency_asset_id) for item in report.declared_only
    }
    assert (asset_a.id, asset_b.id) in declared_pairs

    # Check that c→d is in observed_only
    observed_pairs = {
        (item.dependent_asset_id, item.dependency_asset_id) for item in report.observed_only
    }
    assert (asset_c.id, asset_d.id) in observed_pairs

    # Check that a→d is in both (confirmed by both sources)
    both_pairs = {(item.dependent_asset_id, item.dependency_asset_id) for item in report.both}
    assert (asset_a.id, asset_d.id) in both_pairs
    confirmed = next(i for i in report.both if i.dependent_asset_id == asset_a.id)
    assert confirmed.status == "confirmed"


# ── API endpoint tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_otel_config(client: AsyncClient) -> None:
    """POST /api/v1/otel/configs should create a config."""
    response = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "production-jaeger",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger-query:16686",
            "lookback_seconds": 86400,
            "poll_interval_seconds": 3600,
            "min_call_count": 10,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "production-jaeger"
    assert data["backend_type"] == "jaeger"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_create_otel_config_duplicate_name(client: AsyncClient) -> None:
    """Duplicate config names should return 409."""
    payload = {
        "name": "dupe-config",
        "backend_type": "jaeger",
        "endpoint_url": "http://jaeger:16686",
    }
    await client.post("/api/v1/otel/configs", json=payload)
    response = await client.post("/api/v1/otel/configs", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_otel_config_invalid_url_scheme(client: AsyncClient) -> None:
    """Non-HTTP URLs should be rejected (SSRF protection)."""
    response = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "bad-scheme",
            "backend_type": "jaeger",
            "endpoint_url": "file:///etc/passwd",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_otel_config_ftp_scheme_rejected(client: AsyncClient) -> None:
    """FTP URLs should also be rejected."""
    response = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "ftp-scheme",
            "backend_type": "jaeger",
            "endpoint_url": "ftp://evil.com/data",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_otel_configs(client: AsyncClient) -> None:
    """GET /api/v1/otel/configs should list configs."""
    await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "list-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
        },
    )
    response = await client.get("/api/v1/otel/configs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(c["name"] == "list-test" for c in data["results"])


@pytest.mark.asyncio
async def test_list_otel_configs_filter_enabled(client: AsyncClient) -> None:
    """Should filter by enabled status."""
    await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "enabled-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
            "enabled": True,
        },
    )
    await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "disabled-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger2:16686",
            "enabled": False,
        },
    )
    response = await client.get("/api/v1/otel/configs", params={"enabled": "true"})
    assert response.status_code == 200
    data = response.json()
    assert all(c["enabled"] is True for c in data["results"])


@pytest.mark.asyncio
async def test_get_otel_config(client: AsyncClient) -> None:
    """GET /api/v1/otel/configs/{id} should return a single config."""
    create_resp = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "get-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
        },
    )
    config_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/otel/configs/{config_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "get-test"


@pytest.mark.asyncio
async def test_get_otel_config_not_found(client: AsyncClient) -> None:
    """Should return 404 for non-existent config."""
    response = await client.get(f"/api/v1/otel/configs/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_otel_config(client: AsyncClient) -> None:
    """PATCH /api/v1/otel/configs/{id} should update fields."""
    create_resp = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "patch-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
        },
    )
    config_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/otel/configs/{config_id}",
        json={"enabled": False, "lookback_seconds": 43200},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["lookback_seconds"] == 43200


@pytest.mark.asyncio
async def test_delete_otel_config(client: AsyncClient) -> None:
    """DELETE /api/v1/otel/configs/{id} should remove the config."""
    create_resp = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "delete-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
        },
    )
    config_id = create_resp.json()["id"]

    response = await client.delete(f"/api/v1/otel/configs/{config_id}")
    assert response.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/api/v1/otel/configs/{config_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_sync_otel_disabled(client: AsyncClient) -> None:
    """Should return 400 when OTEL is globally disabled."""
    create_resp = await client.post(
        "/api/v1/otel/configs",
        json={
            "name": "sync-disabled-test",
            "backend_type": "jaeger",
            "endpoint_url": "http://jaeger:16686",
        },
    )
    config_id = create_resp.json()["id"]

    # OTEL is disabled by default in test settings
    response = await client.post(f"/api/v1/otel/configs/{config_id}/sync")
    assert response.status_code == 400
    assert "OTEL_DISABLED" in response.json()["error"]["code"]


@pytest.mark.asyncio
async def test_trigger_sync_config_not_found(client: AsyncClient) -> None:
    """Should return 404 for non-existent config sync trigger."""
    from tessera.config import settings

    original = settings.otel_enabled
    settings.otel_enabled = True
    try:
        response = await client.post(f"/api/v1/otel/configs/{uuid4()}/sync")
        assert response.status_code == 404
    finally:
        settings.otel_enabled = original


@pytest.mark.asyncio
async def test_list_otel_dependencies_empty(client: AsyncClient) -> None:
    """Should return empty list when no OTEL deps exist."""
    response = await client.get("/api/v1/otel/dependencies")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_reconciliation_endpoint(client: AsyncClient) -> None:
    """GET /api/v1/dependencies/reconciliation should return a reconciliation report."""
    response = await client.get("/api/v1/dependencies/reconciliation")
    assert response.status_code == 200
    data = response.json()
    assert "declared_only" in data
    assert "observed_only" in data
    assert "both" in data


# ── Contradictory filter guard ────────────────────────────────


@pytest.mark.asyncio
async def test_list_otel_dependencies_contradictory_filters(client: AsyncClient) -> None:
    """Combining stale=true with min_confidence > 0.05 should return 400."""
    response = await client.get(
        "/api/v1/otel/dependencies",
        params={"stale": "true", "min_confidence": "0.3"},
    )
    assert response.status_code == 400
    assert "stale" in response.json()["error"]["message"].lower()


# ── Stale scoping isolation ───────────────────────────────────


@pytest.mark.asyncio
async def test_mark_stale_scoped_to_config(test_session) -> None:
    """Stale marking should only affect deps belonging to the triggering config."""
    team = TeamDB(name="team-scope")
    test_session.add(team)
    await test_session.flush()

    asset_a = AssetDB(fqn="scope-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="scope-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config_a = OtelSyncConfigDB(
        name="scope-config-a",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,  # 24 hours
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    config_b = OtelSyncConfigDB(
        name="scope-config-b",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger2:16686",
        lookback_seconds=3600,  # 1 hour
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add_all([config_a, config_b])
    await test_session.flush()

    # Dep discovered by config_a, observed 5 hours ago
    old_time = datetime.now(UTC) - timedelta(hours=5)
    dep = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.8,
        last_observed_at=old_time,
        call_count=100,
        otel_config_id=config_a.id,
    )
    test_session.add(dep)
    await test_session.flush()

    # Running stale marking from config_b should NOT affect config_a's dep
    now = datetime.now(UTC)
    stale_count = await mark_stale_dependencies(test_session, config_b, now)
    assert stale_count == 0

    await test_session.refresh(dep)
    assert dep.confidence == 0.8  # Unchanged


# ── SSRF host validation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_otel_endpoint_rejects_localhost() -> None:
    """Should reject URLs targeting localhost."""
    is_valid, msg = await validate_otel_endpoint_host("http://127.0.0.1:16686")
    assert is_valid is False
    assert "blocked" in msg.lower()


@pytest.mark.asyncio
async def test_validate_otel_endpoint_rejects_metadata_service() -> None:
    """Should reject AWS IMDS endpoint."""
    is_valid, msg = await validate_otel_endpoint_host("http://169.254.169.254/latest/meta-data/")
    assert is_valid is False
    assert "blocked" in msg.lower()


@pytest.mark.asyncio
async def test_validate_otel_endpoint_rejects_private_ip() -> None:
    """Should reject RFC 1918 private addresses."""
    is_valid, msg = await validate_otel_endpoint_host("http://10.0.0.1:16686")
    assert is_valid is False
    assert "blocked" in msg.lower()


@pytest.mark.asyncio
async def test_validate_otel_endpoint_rejects_unresolvable_host() -> None:
    """Should reject hostnames that fail DNS resolution (SSRF bypass prevention)."""
    is_valid, msg = await validate_otel_endpoint_host(
        "http://this-host-does-not-exist-98zx7q.example.invalid:16686"
    )
    assert is_valid is False
    assert "resolve" in msg.lower()


# ── FK cascade: delete config with dependencies ──────────────


@pytest.mark.asyncio
async def test_delete_otel_config_with_dependencies(test_session) -> None:
    """Deleting an OTEL config should SET NULL on referencing dependencies, not 500."""
    team = TeamDB(name="team-cascade")
    test_session.add(team)
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="cascade-test",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
    )
    test_session.add(config)
    await test_session.flush()

    asset_a = AssetDB(fqn="cascade-a.api", owner_team_id=team.id)
    asset_b = AssetDB(fqn="cascade-b.api", owner_team_id=team.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    dep, created = await upsert_otel_dependency(
        test_session,
        asset_a.id,
        asset_b.id,
        call_count=100,
        confidence=0.7,
        now=datetime.now(UTC),
        config_id=config.id,
    )
    assert created is True
    assert dep.otel_config_id == config.id

    # Delete the config — should not raise IntegrityError
    await test_session.delete(config)
    await test_session.flush()

    # Dependency row should still exist with otel_config_id set to NULL
    await test_session.refresh(dep)
    assert dep.otel_config_id is None
    assert dep.dependent_asset_id == asset_a.id


# ── Multi-sync confidence tracking ───────────────────────────


@pytest.mark.asyncio
async def test_run_sync_increments_syncs_seen_on_repeat(test_session) -> None:
    """Running sync twice should increment syncs_seen and use it in confidence."""
    team = TeamDB(name="team-multi-sync")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(name="repo-multi", git_url="https://git.example.com/multi", owner_team_id=team.id)
    test_session.add(repo)
    await test_session.flush()

    svc_a = ServiceDB(
        name="svc-multi-a",
        repo_id=repo.id,
        otel_service_name="multi-parent",
    )
    svc_b = ServiceDB(
        name="svc-multi-b",
        repo_id=repo.id,
        otel_service_name="multi-child",
    )
    test_session.add_all([svc_a, svc_b])
    await test_session.flush()

    asset_a = AssetDB(fqn="multi-parent.api", owner_team_id=team.id, service_id=svc_a.id)
    asset_b = AssetDB(fqn="multi-child.api", owner_team_id=team.id, service_id=svc_b.id)
    test_session.add_all([asset_a, asset_b])
    await test_session.flush()

    config = OtelSyncConfigDB(
        name="multi-sync-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()

    mock_response = httpx.Response(
        200,
        json=[{"parent": "multi-parent", "child": "multi-child", "callCount": 5000}],
        request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    # First sync
    result1 = await run_sync(test_session, config, http_client=mock_client)
    assert result1.edges_created == 1
    assert config.sync_count == 1

    # Verify syncs_seen = 1 on the created dependency
    dep_result = await test_session.execute(
        select(AssetDependencyDB).where(
            AssetDependencyDB.dependent_asset_id == asset_b.id,
            AssetDependencyDB.dependency_asset_id == asset_a.id,
            AssetDependencyDB.source == DependencySource.OTEL,
        )
    )
    dep = dep_result.scalar_one()
    assert dep.syncs_seen == 1

    # Second sync
    result2 = await run_sync(test_session, config, http_client=mock_client)
    assert result2.edges_updated == 1
    assert config.sync_count == 2

    await test_session.refresh(dep)
    assert dep.syncs_seen == 2

    # Confidence should use real syncs_seen/total_syncs (2/2 = 1.0 consistency)
    expected = compute_confidence(5000, syncs_seen=2, total_syncs=2)
    assert dep.confidence == expected


@pytest.mark.asyncio
async def test_sync_count_increments_on_config(test_session) -> None:
    """Config sync_count should increment after each successful sync."""
    config = OtelSyncConfigDB(
        name="count-config",
        backend_type=OtelBackendType.JAEGER,
        endpoint_url="http://jaeger:16686",
        lookback_seconds=86400,
        poll_interval_seconds=3600,
        min_call_count=10,
        enabled=True,
    )
    test_session.add(config)
    await test_session.flush()
    assert config.sync_count == 0

    # Sync with empty response (no edges)
    mock_response = httpx.Response(
        200,
        json=[],
        request=httpx.Request("GET", "http://jaeger:16686/api/dependencies"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    await run_sync(test_session, config, http_client=mock_client)
    assert config.sync_count == 1

    await run_sync(test_session, config, http_client=mock_client)
    assert config.sync_count == 2


# ── service_name filter ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_otel_dependencies_service_name_filter(
    client: AsyncClient, test_session
) -> None:
    """GET /api/v1/otel/dependencies?service_name=X should filter by service."""
    team = TeamDB(name="team-svc-filter")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="repo-svc-filter",
        git_url="https://git.example.com/svc-filter",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    svc_a = ServiceDB(
        name="filter-svc-a",
        repo_id=repo.id,
        otel_service_name="filter-alpha",
    )
    svc_b = ServiceDB(
        name="filter-svc-b",
        repo_id=repo.id,
        otel_service_name="filter-beta",
    )
    svc_c = ServiceDB(
        name="filter-svc-c",
        repo_id=repo.id,
        otel_service_name="filter-gamma",
    )
    test_session.add_all([svc_a, svc_b, svc_c])
    await test_session.flush()

    asset_a = AssetDB(fqn="filter-alpha.api", owner_team_id=team.id, service_id=svc_a.id)
    asset_b = AssetDB(fqn="filter-beta.api", owner_team_id=team.id, service_id=svc_b.id)
    asset_c = AssetDB(fqn="filter-gamma.api", owner_team_id=team.id, service_id=svc_c.id)
    test_session.add_all([asset_a, asset_b, asset_c])
    await test_session.flush()

    # Create OTEL deps: a→b and c→b (beta is involved in both)
    dep_ab = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.8,
        call_count=1000,
        last_observed_at=datetime.now(UTC),
    )
    dep_cb = AssetDependencyDB(
        dependent_asset_id=asset_c.id,
        dependency_asset_id=asset_b.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.7,
        call_count=500,
        last_observed_at=datetime.now(UTC),
    )
    # Unrelated: a→c (should not appear when filtering by beta)
    dep_ac = AssetDependencyDB(
        dependent_asset_id=asset_a.id,
        dependency_asset_id=asset_c.id,
        dependency_type=DependencyType.CONSUMES,
        source=DependencySource.OTEL,
        confidence=0.6,
        call_count=200,
        last_observed_at=datetime.now(UTC),
    )
    test_session.add_all([dep_ab, dep_cb, dep_ac])
    await test_session.flush()

    # Filter by filter-beta — should return dep_ab and dep_cb (both involve beta)
    response = await client.get("/api/v1/otel/dependencies", params={"service_name": "filter-beta"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2

    # Filter by filter-gamma — should return dep_cb and dep_ac
    response2 = await client.get(
        "/api/v1/otel/dependencies", params={"service_name": "filter-gamma"}
    )
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["total"] == 2

    # Filter by nonexistent service — should return 0
    response3 = await client.get(
        "/api/v1/otel/dependencies", params={"service_name": "nonexistent-svc"}
    )
    assert response3.status_code == 200
    assert response3.json()["total"] == 0


# ── Reconciliation at new path ───────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_old_path_returns_404(client: AsyncClient) -> None:
    """The old /api/v1/otel/reconciliation path should now return 404."""
    response = await client.get("/api/v1/otel/reconciliation")
    assert response.status_code == 404
