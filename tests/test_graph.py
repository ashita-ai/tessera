"""Tests for /api/v1/graph endpoints.

Covers: graph construction, edge aggregation, neighborhood filtering,
impact traversal, team filter, breaking proposal flag, confidence filtering,
and timezone handling.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    ProposalDB,
    RepoDB,
    ServiceDB,
    TeamDB,
)
from tessera.models.enums import DependencySource, DependencyType, ProposalStatus
from tessera.services.graph import _ensure_utc, _sync_status

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_graph(test_engine) -> dict[str, str]:
    """Build a graph with two teams, three services, and asset-level dependencies.

    Topology (service level):
        order-service --(CONSUMES)--> payment-service
        order-service --(CONSUMES)--> payment-service  (second asset pair, same type)
        order-service --(REFERENCES)--> inventory-service

    Returns dict mapping friendly names to UUID strings.
    """
    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        # Teams
        commerce = TeamDB(name="Commerce")
        logistics = TeamDB(name="Logistics")
        session.add_all([commerce, logistics])
        await session.flush()

        # Repos
        order_repo = RepoDB(
            name="acme/order-service",
            git_url="https://github.com/acme/order-service",
            owner_team_id=commerce.id,
        )
        payment_repo = RepoDB(
            name="acme/payment-service",
            git_url="https://github.com/acme/payment-service",
            owner_team_id=commerce.id,
        )
        inventory_repo = RepoDB(
            name="acme/inventory-service",
            git_url="https://github.com/acme/inventory-service",
            owner_team_id=logistics.id,
        )
        session.add_all([order_repo, payment_repo, inventory_repo])
        await session.flush()

        # Services
        order_svc = ServiceDB(
            name="order-service",
            repo_id=order_repo.id,
        )
        payment_svc = ServiceDB(
            name="payment-service",
            repo_id=payment_repo.id,
        )
        inventory_svc = ServiceDB(
            name="inventory-service",
            repo_id=inventory_repo.id,
        )
        session.add_all([order_svc, payment_svc, inventory_svc])
        await session.flush()

        # Assets (two in order, two in payment, one in inventory)
        order_a1 = AssetDB(
            fqn="order-service.rest.POST_/orders",
            owner_team_id=commerce.id,
            service_id=order_svc.id,
        )
        order_a2 = AssetDB(
            fqn="order-service.rest.GET_/orders",
            owner_team_id=commerce.id,
            service_id=order_svc.id,
        )
        payment_a1 = AssetDB(
            fqn="payment-service.rest.POST_/payments",
            owner_team_id=commerce.id,
            service_id=payment_svc.id,
        )
        payment_a2 = AssetDB(
            fqn="payment-service.rest.GET_/status",
            owner_team_id=commerce.id,
            service_id=payment_svc.id,
        )
        inventory_a1 = AssetDB(
            fqn="inventory-service.rest.GET_/stock",
            owner_team_id=logistics.id,
            service_id=inventory_svc.id,
        )
        session.add_all([order_a1, order_a2, payment_a1, payment_a2, inventory_a1])
        await session.flush()

        # Dependencies:
        # order_a1 -> payment_a1 (CONSUMES)
        # order_a2 -> payment_a2 (CONSUMES)
        # order_a1 -> inventory_a1 (REFERENCES)
        dep1 = AssetDependencyDB(
            dependent_asset_id=order_a1.id,
            dependency_asset_id=payment_a1.id,
            dependency_type=DependencyType.CONSUMES,
        )
        dep2 = AssetDependencyDB(
            dependent_asset_id=order_a2.id,
            dependency_asset_id=payment_a2.id,
            dependency_type=DependencyType.CONSUMES,
        )
        dep3 = AssetDependencyDB(
            dependent_asset_id=order_a1.id,
            dependency_asset_id=inventory_a1.id,
            dependency_type=DependencyType.REFERENCES,
        )
        session.add_all([dep1, dep2, dep3])
        await session.flush()
        await session.commit()

        return {
            "commerce_team_id": str(commerce.id),
            "logistics_team_id": str(logistics.id),
            "order_svc_id": str(order_svc.id),
            "payment_svc_id": str(payment_svc.id),
            "inventory_svc_id": str(inventory_svc.id),
            "order_a1_id": str(order_a1.id),
            "order_a2_id": str(order_a2.id),
            "payment_a1_id": str(payment_a1.id),
            "inventory_a1_id": str(inventory_a1.id),
        }


# ---------------------------------------------------------------------------
# GET /api/v1/graph/services — full graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFullGraph:
    """Tests for GET /api/v1/graph/services."""

    async def test_full_graph_nodes_and_edges(self, client: AsyncClient, test_engine):
        """Full graph returns all 3 services and 2 aggregated edges."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        assert resp.status_code == 200

        data = resp.json()
        assert data["metadata"]["node_count"] == 3
        # Two edges: order->payment (CONSUMES), order->inventory (REFERENCES)
        assert data["metadata"]["edge_count"] == 2
        assert sorted(data["metadata"]["teams"]) == ["Commerce", "Logistics"]

        node_names = {n["name"] for n in data["nodes"]}
        assert node_names == {"order-service", "payment-service", "inventory-service"}

    async def test_edge_aggregation(self, client: AsyncClient, test_engine):
        """Two asset-level CONSUMES edges between order and payment aggregate to one edge."""
        ids = await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        data = resp.json()

        consumes_edges = [e for e in data["edges"] if e["dependency_type"] == "consumes"]
        assert len(consumes_edges) == 1
        edge = consumes_edges[0]
        assert edge["source"] == ids["order_svc_id"]
        assert edge["target"] == ids["payment_svc_id"]
        assert edge["asset_level_edges"] == 2
        assert edge["source_type"] == "manual"
        assert edge["confidence"] is None
        assert edge["call_count"] is None

    async def test_node_asset_count(self, client: AsyncClient, test_engine):
        """Nodes report correct asset counts."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        data = resp.json()

        by_name = {n["name"]: n for n in data["nodes"]}
        assert by_name["order-service"]["asset_count"] == 2
        assert by_name["payment-service"]["asset_count"] == 2
        assert by_name["inventory-service"]["asset_count"] == 1

    async def test_node_fields(self, client: AsyncClient, test_engine):
        """Nodes include required fields: repo_name, team_name, sync_status."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        node = resp.json()["nodes"][0]
        required_keys = {
            "id",
            "name",
            "repo_id",
            "repo_name",
            "team_id",
            "team_name",
            "asset_count",
            "has_breaking_proposal",
            "last_synced_at",
            "sync_status",
        }
        assert required_keys.issubset(node.keys())

    async def test_unregistered_services_empty(self, client: AsyncClient, test_engine):
        """Without OTEL, unregistered_services is always empty."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        assert resp.json()["unregistered_services"] == []

    async def test_empty_graph(self, client: AsyncClient):
        """Empty database returns empty graph."""
        resp = await client.get("/api/v1/graph/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["node_count"] == 0
        assert data["metadata"]["edge_count"] == 0


# ---------------------------------------------------------------------------
# Team filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTeamFilter:
    """Tests for team_id query parameter."""

    async def test_team_filter_includes_neighbors(self, client: AsyncClient, test_engine):
        """Filtering by Logistics team should return inventory + order (neighbor)."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(
            "/api/v1/graph/services",
            params={"team_id": ids["logistics_team_id"]},
        )
        assert resp.status_code == 200
        data = resp.json()

        node_names = {n["name"] for n in data["nodes"]}
        # inventory-service (team's own) + order-service (neighbor via REFERENCES)
        assert "inventory-service" in node_names
        assert "order-service" in node_names

    async def test_team_filter_excludes_unconnected(self, client: AsyncClient, test_engine):
        """Team filter for Commerce shows order + payment + inventory (neighbor),
        which is the full graph here since order connects to both."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(
            "/api/v1/graph/services",
            params={"team_id": ids["commerce_team_id"]},
        )
        data = resp.json()
        node_names = {n["name"] for n in data["nodes"]}
        # Commerce owns order + payment; inventory is neighbor of order
        assert node_names == {"order-service", "payment-service", "inventory-service"}


# ---------------------------------------------------------------------------
# Breaking proposal flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBreakingProposalFlag:
    """Tests for has_breaking_proposal node field."""

    async def test_no_proposals_means_false(self, client: AsyncClient, test_engine):
        """Without proposals, all services have has_breaking_proposal=false."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/services")
        for node in resp.json()["nodes"]:
            assert node["has_breaking_proposal"] is False

    async def test_pending_proposal_sets_flag(self, client: AsyncClient, test_engine):
        """A PENDING proposal on one of a service's assets sets the flag."""
        ids = await _seed_graph(test_engine)

        # Create a pending proposal on order_a1
        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            proposal = ProposalDB(
                asset_id=UUID(ids["order_a1_id"]),
                proposed_schema={"type": "object", "properties": {"x": {"type": "string"}}},
                change_type="major",
                breaking_changes=[{"path": "/x", "description": "removed"}],
                status=ProposalStatus.PENDING,
                proposed_by=UUID(ids["commerce_team_id"]),
            )
            session.add(proposal)
            await session.flush()
            await session.commit()

        resp = await client.get("/api/v1/graph/services")
        by_name = {n["name"]: n for n in resp.json()["nodes"]}
        assert by_name["order-service"]["has_breaking_proposal"] is True
        assert by_name["payment-service"]["has_breaking_proposal"] is False
        assert by_name["inventory-service"]["has_breaking_proposal"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/graph/services/{id}/neighborhood
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNeighborhood:
    """Tests for GET /api/v1/graph/services/{id}/neighborhood."""

    async def test_neighborhood_of_order_service(self, client: AsyncClient, test_engine):
        """Order service's neighborhood includes payment and inventory."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(f"/api/v1/graph/services/{ids['order_svc_id']}/neighborhood")
        assert resp.status_code == 200
        data = resp.json()

        node_names = {n["name"] for n in data["nodes"]}
        assert node_names == {"order-service", "payment-service", "inventory-service"}
        assert data["metadata"]["edge_count"] == 2

    async def test_neighborhood_of_payment_service(self, client: AsyncClient, test_engine):
        """Payment service's neighborhood includes only order (upstream)."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(f"/api/v1/graph/services/{ids['payment_svc_id']}/neighborhood")
        data = resp.json()

        node_names = {n["name"] for n in data["nodes"]}
        assert node_names == {"order-service", "payment-service"}
        assert data["metadata"]["edge_count"] == 1

    async def test_neighborhood_of_nonexistent_service(self, client: AsyncClient, test_engine):
        """Non-existent service returns 404."""
        await _seed_graph(test_engine)
        resp = await client.get(
            "/api/v1/graph/services/00000000-0000-0000-0000-000000000001/neighborhood"
        )
        assert resp.status_code == 404

    async def test_neighborhood_of_isolated_service(self, client: AsyncClient, test_engine):
        """A service with no edges returns only itself."""
        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            team = TeamDB(name="lonely-team")
            session.add(team)
            await session.flush()
            repo = RepoDB(
                name="lonely-repo",
                git_url="https://github.com/acme/lonely",
                owner_team_id=team.id,
            )
            session.add(repo)
            await session.flush()
            svc = ServiceDB(name="lonely-svc", repo_id=repo.id)
            session.add(svc)
            await session.flush()
            await session.commit()
            svc_id = str(svc.id)

        resp = await client.get(f"/api/v1/graph/services/{svc_id}/neighborhood")
        data = resp.json()
        assert data["metadata"]["node_count"] == 1
        assert data["metadata"]["edge_count"] == 0
        assert data["nodes"][0]["name"] == "lonely-svc"


# ---------------------------------------------------------------------------
# GET /api/v1/graph/impact/{asset_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestImpactGraph:
    """Tests for GET /api/v1/graph/impact/{asset_id}."""

    async def test_impact_from_payment_asset(self, client: AsyncClient, test_engine):
        """Impact of payment_a1 should show order-service as affected (depth 1)."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(f"/api/v1/graph/impact/{ids['payment_a1_id']}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["source_asset"]["id"] == ids["payment_a1_id"]
        assert data["source_asset"]["service_name"] == "payment-service"

        affected_names = {s["name"] for s in data["affected_services"]}
        assert "order-service" in affected_names

    async def test_impact_from_asset_with_no_downstream(self, client: AsyncClient, test_engine):
        """An asset that nothing depends on has no affected services."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(f"/api/v1/graph/impact/{ids['order_a1_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["affected_services"] == []
        assert data["impact_edges"] == []

    async def test_impact_depth_limit(self, client: AsyncClient, test_engine):
        """Depth parameter limits traversal."""
        ids = await _seed_graph(test_engine)
        resp = await client.get(
            f"/api/v1/graph/impact/{ids['payment_a1_id']}",
            params={"depth": 1},
        )
        assert resp.status_code == 200

    async def test_impact_asset_not_found(self, client: AsyncClient, test_engine):
        """Non-existent asset returns 404."""
        await _seed_graph(test_engine)
        resp = await client.get("/api/v1/graph/impact/00000000-0000-0000-0000-000000000001")
        assert resp.status_code == 404

    async def test_transitive_impact(self, client: AsyncClient, test_engine):
        """Multi-hop impact: A -> B -> C propagates to C at depth 2."""
        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            team = TeamDB(name="chain-team")
            session.add(team)
            await session.flush()

            repo = RepoDB(
                name="chain-repo",
                git_url="https://github.com/acme/chain",
                owner_team_id=team.id,
            )
            session.add(repo)
            await session.flush()

            svc_a = ServiceDB(name="svc-a", repo_id=repo.id)
            svc_b = ServiceDB(name="svc-b", repo_id=repo.id)
            svc_c = ServiceDB(name="svc-c", repo_id=repo.id)
            session.add_all([svc_a, svc_b, svc_c])
            await session.flush()

            asset_a = AssetDB(fqn="chain.a", owner_team_id=team.id, service_id=svc_a.id)
            asset_b = AssetDB(fqn="chain.b", owner_team_id=team.id, service_id=svc_b.id)
            asset_c = AssetDB(fqn="chain.c", owner_team_id=team.id, service_id=svc_c.id)
            session.add_all([asset_a, asset_b, asset_c])
            await session.flush()

            # B depends on A, C depends on B
            dep_ba = AssetDependencyDB(
                dependent_asset_id=asset_b.id,
                dependency_asset_id=asset_a.id,
                dependency_type=DependencyType.CONSUMES,
            )
            dep_cb = AssetDependencyDB(
                dependent_asset_id=asset_c.id,
                dependency_asset_id=asset_b.id,
                dependency_type=DependencyType.CONSUMES,
            )
            session.add_all([dep_ba, dep_cb])
            await session.flush()
            await session.commit()

            asset_a_id = str(asset_a.id)

        resp = await client.get(
            f"/api/v1/graph/impact/{asset_a_id}",
            params={"depth": 5},
        )
        assert resp.status_code == 200
        data = resp.json()

        affected_names = {s["name"] for s in data["affected_services"]}
        assert "svc-b" in affected_names
        assert "svc-c" in affected_names

        # svc-b at depth 1, svc-c at depth 2
        by_name = {s["name"]: s for s in data["affected_services"]}
        assert by_name["svc-b"]["depth"] == 1
        assert by_name["svc-c"]["depth"] == 2


# ---------------------------------------------------------------------------
# Confidence filtering (min_confidence query param)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConfidenceFilter:
    """Tests for min_confidence query parameter on GET /graph/services."""

    async def _seed_with_otel_edge(self, test_engine) -> dict[str, str]:
        """Seed graph with one manual and one OTEL edge.

        Topology:
            svc-api --(CONSUMES, manual)--> svc-db
            svc-api --(CONSUMES, otel, confidence=0.4)--> svc-cache
        """
        session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            team = TeamDB(name="platform")
            session.add(team)
            await session.flush()

            repo = RepoDB(
                name="acme/platform",
                git_url="https://github.com/acme/platform",
                owner_team_id=team.id,
            )
            session.add(repo)
            await session.flush()

            svc_api = ServiceDB(name="svc-api", repo_id=repo.id)
            svc_db = ServiceDB(name="svc-db", repo_id=repo.id)
            svc_cache = ServiceDB(name="svc-cache", repo_id=repo.id)
            session.add_all([svc_api, svc_db, svc_cache])
            await session.flush()

            asset_api = AssetDB(fqn="api.endpoint", owner_team_id=team.id, service_id=svc_api.id)
            asset_db = AssetDB(fqn="db.table", owner_team_id=team.id, service_id=svc_db.id)
            asset_cache = AssetDB(fqn="cache.key", owner_team_id=team.id, service_id=svc_cache.id)
            session.add_all([asset_api, asset_db, asset_cache])
            await session.flush()

            # Manual edge: api -> db
            dep_manual = AssetDependencyDB(
                dependent_asset_id=asset_api.id,
                dependency_asset_id=asset_db.id,
                dependency_type=DependencyType.CONSUMES,
                source=DependencySource.MANUAL,
            )
            # OTEL edge: api -> cache (low confidence)
            dep_otel = AssetDependencyDB(
                dependent_asset_id=asset_api.id,
                dependency_asset_id=asset_cache.id,
                dependency_type=DependencyType.CONSUMES,
                source=DependencySource.OTEL,
                confidence=0.4,
                call_count=150,
            )
            session.add_all([dep_manual, dep_otel])
            await session.flush()
            await session.commit()

            return {
                "svc_api_id": str(svc_api.id),
                "svc_db_id": str(svc_db.id),
                "svc_cache_id": str(svc_cache.id),
            }

    async def test_no_filter_returns_all_edges(self, client: AsyncClient, test_engine):
        """Default min_confidence=0.0 includes all edges."""
        await self._seed_with_otel_edge(test_engine)
        resp = await client.get("/api/v1/graph/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["edge_count"] == 2

    async def test_high_confidence_excludes_low_otel_edge(self, client: AsyncClient, test_engine):
        """min_confidence=0.5 excludes the 0.4-confidence OTEL edge."""
        await self._seed_with_otel_edge(test_engine)
        resp = await client.get(
            "/api/v1/graph/services",
            params={"min_confidence": 0.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only the manual edge remains (confidence=NULL passes through)
        assert data["metadata"]["edge_count"] == 1
        edge = data["edges"][0]
        assert edge["source_type"] == "manual"
        assert edge["confidence"] is None

    async def test_manual_edges_always_included(self, client: AsyncClient, test_engine):
        """Manual edges (confidence=NULL) are never filtered by min_confidence."""
        await self._seed_with_otel_edge(test_engine)
        resp = await client.get(
            "/api/v1/graph/services",
            params={"min_confidence": 1.0},
        )
        data = resp.json()
        # Only manual edge survives at max confidence filter
        assert data["metadata"]["edge_count"] == 1
        assert data["edges"][0]["source_type"] == "manual"

    async def test_otel_edge_has_confidence_and_call_count(self, client: AsyncClient, test_engine):
        """OTEL edges report aggregated confidence and call_count."""
        await self._seed_with_otel_edge(test_engine)
        resp = await client.get("/api/v1/graph/services")
        data = resp.json()
        otel_edges = [e for e in data["edges"] if e["source_type"] == "otel"]
        assert len(otel_edges) == 1
        assert otel_edges[0]["confidence"] == pytest.approx(0.4)
        assert otel_edges[0]["call_count"] == 150

    async def test_include_unregistered_param_accepted(self, client: AsyncClient, test_engine):
        """include_unregistered parameter is accepted and returns empty list (no OTEL data)."""
        await self._seed_with_otel_edge(test_engine)
        resp = await client.get(
            "/api/v1/graph/services",
            params={"include_unregistered": True},
        )
        assert resp.status_code == 200
        assert resp.json()["unregistered_services"] == []


# ---------------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------------


class TestTimezoneHandling:
    """Tests for _sync_status and _ensure_utc timezone correctness."""

    def test_ensure_utc_naive_datetime(self):
        """Naive datetime gets UTC tzinfo stamped."""
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = _ensure_utc(naive)
        assert result.tzinfo is UTC
        assert result.hour == 12

    def test_ensure_utc_already_utc(self):
        """UTC-aware datetime passes through unchanged."""
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = _ensure_utc(aware)
        assert result.tzinfo is UTC
        assert result.hour == 12

    def test_ensure_utc_non_utc_timezone(self):
        """Non-UTC datetime is converted (not just re-labeled)."""
        # UTC+5 at 17:00 should become 12:00 UTC
        tz_plus5 = timezone(timedelta(hours=5))
        aware = datetime(2026, 1, 1, 17, 0, 0, tzinfo=tz_plus5)
        result = _ensure_utc(aware)
        assert result.tzinfo is UTC
        assert result.hour == 12

    def test_sync_status_none(self):
        """None last_synced_at returns 'never'."""
        assert _sync_status(None) == "never"

    def test_sync_status_recent(self):
        """Recently synced returns 'ok'."""
        recent = datetime.now(UTC) - timedelta(hours=1)
        assert _sync_status(recent) == "ok"

    def test_sync_status_stale(self):
        """Sync older than 24h returns 'stale'."""
        old = datetime.now(UTC) - timedelta(hours=25)
        assert _sync_status(old) == "stale"

    def test_sync_status_naive_datetime(self):
        """Naive datetime (from SQLite) is handled correctly."""
        # Naive datetime representing "1 hour ago in UTC"
        naive_recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        assert _sync_status(naive_recent) == "ok"
