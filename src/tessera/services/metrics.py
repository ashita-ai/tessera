"""Prometheus metrics for Tessera.

Provides application metrics for monitoring and observability.
"""

import time
from typing import Any

import redis
from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# HTTP request metrics
http_requests_total = Counter(
    "tessera_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "tessera_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress = Gauge(
    "tessera_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method", "endpoint"],
)

# Business metrics - Contracts
contracts_published_total = Counter(
    "tessera_contracts_published_total",
    "Total contracts published",
    ["change_type"],
)

contracts_active = Gauge(
    "tessera_contracts_active",
    "Number of active contracts",
)

# Business metrics - Proposals
proposals_created_total = Counter(
    "tessera_proposals_created_total",
    "Total proposals created",
)

proposals_acknowledged_total = Counter(
    "tessera_proposals_acknowledged_total",
    "Total proposal acknowledgments",
    ["response"],
)

proposals_pending = Gauge(
    "tessera_proposals_pending",
    "Number of pending proposals",
)

# Business metrics - Assets
assets_total = Gauge(
    "tessera_assets_total",
    "Total number of assets",
)

# Business metrics - Registrations
registrations_total = Gauge(
    "tessera_registrations_total",
    "Total number of consumer registrations",
)

# Business metrics - Teams
teams_total = Gauge(
    "tessera_teams_total",
    "Total number of teams",
)

# Business metrics - Users
users_total = Gauge(
    "tessera_users_total",
    "Total number of users",
)

# Database metrics
db_query_duration_seconds = Histogram(
    "tessera_db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# Application info
app_info = Gauge(
    "tessera_app_info",
    "Application information",
    ["version"],
)
app_info.labels(version="0.1.0").set(1)

# Uptime tracking
_start_time = time.time()

app_uptime_seconds = Gauge(
    "tessera_app_uptime_seconds",
    "Application uptime in seconds",
)


def update_uptime() -> None:
    """Update the uptime gauge."""
    app_uptime_seconds.set(time.time() - _start_time)


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    update_uptime()
    return generate_latest(REGISTRY)


def _normalize_path(path: str) -> str:
    """Normalize URL paths to avoid high cardinality metrics.

    Replaces UUIDs and numeric IDs with placeholders.
    """
    import re

    # Replace UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
        flags=re.IGNORECASE,
    )
    # Replace numeric IDs
    path = re.sub(r"/\d+(/|$)", "/{id}\\1", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting HTTP request metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request and record metrics."""
        # Skip metrics for the metrics endpoint itself to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path = _normalize_path(request.url.path)

        # Track in-progress requests
        http_requests_in_progress.labels(method=method, endpoint=path).inc()

        start_time = time.time()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            duration = time.time() - start_time

            # Record metrics
            http_requests_total.labels(method=method, endpoint=path, status=str(status)).inc()
            http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)
            http_requests_in_progress.labels(method=method, endpoint=path).dec()

        return response


# Helper functions for recording business metrics
def record_contract_published(change_type: str = "patch") -> None:
    """Record a contract publication."""
    contracts_published_total.labels(change_type=change_type).inc()


def record_proposal_created() -> None:
    """Record a proposal creation."""
    proposals_created_total.inc()


def record_proposal_acknowledged(response: str) -> None:
    """Record a proposal acknowledgment."""
    proposals_acknowledged_total.labels(response=response).inc()


async def update_gauge_metrics(session: Any) -> None:
    """Update gauge metrics from database counts.

    This should be called periodically or on-demand to refresh gauge values.
    """
    from sqlalchemy import func, select

    from tessera.db import AssetDB, ContractDB, ProposalDB, RegistrationDB, TeamDB, UserDB

    try:
        # Count active assets
        result = await session.execute(select(func.count(AssetDB.id)))
        assets_total.set(result.scalar_one())

        # Count active contracts
        result = await session.execute(
            select(func.count(ContractDB.id)).where(ContractDB.status == "active")
        )
        contracts_active.set(result.scalar_one())

        # Count pending proposals
        result = await session.execute(
            select(func.count(ProposalDB.id)).where(ProposalDB.status == "pending")
        )
        proposals_pending.set(result.scalar_one())

        # Count registrations
        result = await session.execute(select(func.count(RegistrationDB.id)))
        registrations_total.set(result.scalar_one())

        # Count teams
        result = await session.execute(select(func.count(TeamDB.id)))
        teams_total.set(result.scalar_one())

        # Count users
        result = await session.execute(select(func.count(UserDB.id)))
        users_total.set(result.scalar_one())

    except (TimeoutError, redis.ConnectionError, redis.TimeoutError):
        # Don't fail if we can't update metrics
        pass
