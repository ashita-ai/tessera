"""Tests for Prometheus metrics and health endpoints."""

from httpx import AsyncClient


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    async def test_metrics_returns_prometheus_format(self, client: AsyncClient):
        """Test that /metrics returns valid Prometheus format."""
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

        content = response.text
        # Should contain standard metrics
        assert "tessera_http_requests_total" in content
        assert "tessera_http_request_duration_seconds" in content
        assert "tessera_app_info" in content
        assert "tessera_app_uptime_seconds" in content

    async def test_metrics_contains_business_metrics(self, client: AsyncClient):
        """Test that /metrics contains business metrics."""
        response = await client.get("/metrics")
        assert response.status_code == 200

        content = response.text
        # Business metrics should be present
        assert "tessera_contracts_active" in content
        assert "tessera_proposals_pending" in content
        assert "tessera_assets_total" in content
        assert "tessera_registrations_total" in content
        assert "tessera_teams_total" in content
        assert "tessera_users_total" in content

    async def test_metrics_tracks_requests(self, client: AsyncClient):
        """Test that HTTP requests are tracked in metrics."""
        # Make a request that will be tracked
        await client.get("/health")

        # Check metrics
        response = await client.get("/metrics")
        content = response.text

        # Should have recorded the /health request
        assert "tessera_http_requests_total" in content


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    async def test_health_returns_status(self, client: AsyncClient):
        """Test that /health returns overall status."""
        response = await client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded"]

    async def test_health_includes_version(self, client: AsyncClient):
        """Test that /health includes version."""
        response = await client.get("/health")
        data = response.json()

        assert "version" in data
        assert data["version"] == "0.1.0"

    async def test_health_includes_uptime(self, client: AsyncClient):
        """Test that /health includes uptime."""
        response = await client.get("/health")
        data = response.json()

        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int | float)
        assert data["uptime_seconds"] >= 0

    async def test_health_includes_database_check(self, client: AsyncClient):
        """Test that /health includes database check."""
        response = await client.get("/health")
        data = response.json()

        assert "checks" in data
        assert "database" in data["checks"]
        assert "status" in data["checks"]["database"]
        assert "latency_ms" in data["checks"]["database"]

    async def test_health_database_latency_is_measured(self, client: AsyncClient):
        """Test that database latency is measured."""
        response = await client.get("/health")
        data = response.json()

        db_check = data["checks"]["database"]
        assert db_check["status"] == "healthy"
        assert db_check["latency_ms"] is not None
        assert isinstance(db_check["latency_ms"], int | float)
        assert db_check["latency_ms"] >= 0


class TestReadinessEndpoint:
    """Tests for /health/ready endpoint."""

    async def test_ready_returns_status(self, client: AsyncClient):
        """Test that /health/ready returns ready status."""
        response = await client.get("/health/ready")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] == "ready"

    async def test_ready_includes_database_status(self, client: AsyncClient):
        """Test that /health/ready includes database status."""
        response = await client.get("/health/ready")
        data = response.json()

        assert "database" in data
        assert data["database"] is True


class TestLivenessEndpoint:
    """Tests for /health/live endpoint."""

    async def test_live_returns_alive(self, client: AsyncClient):
        """Test that /health/live returns alive status."""
        response = await client.get("/health/live")
        assert response.status_code == 200

        data = response.json()
        assert data == {"status": "alive"}


class TestMetricsService:
    """Tests for metrics service functions."""

    def test_normalize_path_replaces_uuids(self):
        """Test that UUIDs are replaced with {id}."""
        from tessera.services.metrics import _normalize_path

        path = "/api/v1/assets/550e8400-e29b-41d4-a716-446655440000/contracts"
        normalized = _normalize_path(path)
        assert normalized == "/api/v1/assets/{id}/contracts"

    def test_normalize_path_replaces_numeric_ids(self):
        """Test that numeric IDs are replaced with {id}."""
        from tessera.services.metrics import _normalize_path

        path = "/api/v1/items/12345/details"
        normalized = _normalize_path(path)
        assert normalized == "/api/v1/items/{id}/details"

    def test_normalize_path_handles_multiple_ids(self):
        """Test that multiple IDs are all replaced."""
        from tessera.services.metrics import _normalize_path

        path = "/api/v1/teams/550e8400-e29b-41d4-a716-446655440000/assets/123"
        normalized = _normalize_path(path)
        assert normalized == "/api/v1/teams/{id}/assets/{id}"

    def test_record_contract_published(self):
        """Test recording contract publication."""
        from tessera.services.metrics import contracts_published_total, record_contract_published

        # Get initial value
        initial = contracts_published_total.labels(change_type="minor")._value.get()

        record_contract_published("minor")

        # Value should have incremented
        new_value = contracts_published_total.labels(change_type="minor")._value.get()
        assert new_value == initial + 1

    def test_record_proposal_created(self):
        """Test recording proposal creation."""
        from tessera.services.metrics import proposals_created_total, record_proposal_created

        initial = proposals_created_total._value.get()
        record_proposal_created()
        assert proposals_created_total._value.get() == initial + 1

    def test_record_proposal_acknowledged(self):
        """Test recording proposal acknowledgment."""
        from tessera.services.metrics import (
            proposals_acknowledged_total,
            record_proposal_acknowledged,
        )

        initial = proposals_acknowledged_total.labels(response="accepted")._value.get()
        record_proposal_acknowledged("accepted")
        assert proposals_acknowledged_total.labels(response="accepted")._value.get() == initial + 1

    def test_get_metrics_returns_bytes(self):
        """Test that get_metrics returns bytes."""
        from tessera.services.metrics import get_metrics

        result = get_metrics()
        assert isinstance(result, bytes)
        assert b"tessera_" in result

    def test_update_uptime(self):
        """Test that uptime is updated."""
        from tessera.services.metrics import app_uptime_seconds, update_uptime

        update_uptime()
        # Uptime should be positive
        assert app_uptime_seconds._value.get() > 0
