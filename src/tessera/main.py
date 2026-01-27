"""FastAPI application entry point."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import redis
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from tessera.api import (
    api_keys,
    assets,
    audit,
    audits,
    bulk,
    contracts,
    dependencies,
    impact,
    proposals,
    registrations,
    schemas,
    search,
    sync,
    teams,
    users,
    webhooks,
)
from tessera.api.errors import (
    APIError,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    api_error_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from tessera.api.rate_limit import limiter, rate_limit_exceeded_handler
from tessera.config import DEFAULT_SESSION_SECRET, settings
from tessera.db import get_session, init_db
from tessera.db.database import dispose_engine
from tessera.services.metrics import MetricsMiddleware, get_metrics, update_gauge_metrics
from tessera.web import router as web_router
from tessera.web.routes import register_login_required_handler

# Track application start time for uptime calculation
_app_start_time = time.time()

logger = logging.getLogger(__name__)


async def bootstrap_admin_user() -> None:
    """Bootstrap an admin user from environment variables.

    This is idempotent and safe for k8s rolling restarts:
    - If the user doesn't exist, create them with admin role
    - If the user exists, update their password and ensure admin role
    """
    if not settings.admin_email or not settings.admin_password:
        return

    from argon2 import PasswordHasher

    from tessera.db import TeamDB, UserDB
    from tessera.db.database import get_async_session_maker
    from tessera.models.enums import UserRole

    hasher = PasswordHasher()
    async_session = get_async_session_maker()

    async with async_session() as session:
        # Check if user exists
        result = await session.execute(select(UserDB).where(UserDB.email == settings.admin_email))
        user = result.scalar_one_or_none()

        if user:
            # Update existing user
            user.password_hash = hasher.hash(settings.admin_password)
            user.role = UserRole.ADMIN
            user.name = settings.admin_name
            user.deactivated_at = None  # Re-activate if deactivated
            logger.info(f"Updated bootstrap admin user: {settings.admin_email}")
        else:
            # Need a team for the user - get or create "admin" team
            team_result = await session.execute(
                select(TeamDB).where(TeamDB.name == "admin").where(TeamDB.deleted_at.is_(None))
            )
            team = team_result.scalar_one_or_none()

            if not team:
                team = TeamDB(name="admin", metadata_={"bootstrap": True})
                session.add(team)
                await session.flush()
                logger.info("Created bootstrap admin team")

            # Create new user
            user = UserDB(
                email=settings.admin_email,
                name=settings.admin_name,
                password_hash=hasher.hash(settings.admin_password),
                role=UserRole.ADMIN,
                team_id=team.id,
            )
            session.add(user)
            logger.info(f"Created bootstrap admin user: {settings.admin_email}")

        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Security warnings
    if (
        settings.environment == "production"
        and settings.session_secret_key == DEFAULT_SESSION_SECRET
    ):
        logger.warning(
            "SECURITY WARNING: Using default session secret key in production! "
            "Set SESSION_SECRET_KEY environment variable to a secure random value."
        )
    if settings.environment == "production" and settings.auth_disabled:
        logger.warning(
            "SECURITY WARNING: Authentication is disabled in production! "
            "Set AUTH_DISABLED=false for production deployments."
        )

    await init_db()

    # Bootstrap admin user if configured
    await bootstrap_admin_user()

    yield
    # Clean up database connections on shutdown
    await dispose_engine()


app = FastAPI(
    title="Tessera",
    description="Data contract coordination for warehouses",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
# Only add rate limiting middleware if enabled
if settings.rate_limit_enabled:
    app.add_middleware(SlowAPIMiddleware)

# Session middleware for web UI authentication
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)

# Request ID middleware (must be added first to wrap all other middleware)
app.add_middleware(RequestIDMiddleware)

# Security headers middleware (OWASP A05:2021 - Security Misconfiguration)
app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

# Prometheus metrics middleware
app.add_middleware(MetricsMiddleware)

# CORS middleware
allow_methods = ["*"]
if settings.environment == "production":
    allow_methods = settings.cors_allow_methods

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=allow_methods,
    allow_headers=["*"],
)

# Exception handlers (type: ignore needed for Starlette handler signatures)
app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(ValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, generic_exception_handler)

# Register login required handler for web UI routes
register_login_required_handler(app)

# API v1 router
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(users.router, prefix="/users", tags=["users"])
api_v1.include_router(teams.router, prefix="/teams", tags=["teams"])
api_v1.include_router(assets.router, prefix="/assets", tags=["assets"])
api_v1.include_router(audits.router, prefix="/assets", tags=["audits"])
api_v1.include_router(dependencies.router, prefix="/assets", tags=["dependencies"])
api_v1.include_router(impact.router, prefix="/assets", tags=["impact"])
api_v1.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_v1.include_router(registrations.router, prefix="/registrations", tags=["registrations"])
api_v1.include_router(proposals.router, prefix="/proposals", tags=["proposals"])
api_v1.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
api_v1.include_router(sync.router, prefix="/sync", tags=["sync"])
api_v1.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_v1.include_router(search.router)
api_v1.include_router(webhooks.router)
api_v1.include_router(audit.router)
api_v1.include_router(bulk.router, prefix="/bulk", tags=["bulk"])

app.include_router(api_v1)

# Static files and Web UI
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Web UI routes (must be added after API routes to avoid conflicts)
app.include_router(web_router)


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus metrics endpoint."""
    return PlainTextResponse(get_metrics(), media_type="text/plain; charset=utf-8")


@app.get("/health")
async def health(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Enhanced health check endpoint with dependency checks."""
    uptime_seconds = time.time() - _app_start_time
    checks: dict[str, dict[str, Any]] = {}

    # Database check
    db_status = "healthy"
    db_latency_ms: float | None = None
    try:
        start = time.time()
        await session.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - start) * 1000, 2)
    except Exception as e:
        db_status = "unhealthy"
        logger.error("Health check database failed: %s", e)

    db_check: dict[str, Any] = {
        "status": db_status,
        "latency_ms": db_latency_ms,
    }

    # Connection pool metrics (PostgreSQL only — SQLite uses StaticPool)
    try:
        from sqlalchemy.pool import QueuePool

        from tessera.db.database import get_engine

        engine = get_engine()
        pool = engine.pool
        if isinstance(pool, QueuePool):
            db_check["pool"] = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }
    except Exception:
        pass  # Don't fail health check if pool introspection fails

    checks["database"] = db_check

    # Overall status
    overall_status = (
        "healthy" if all(c["status"] == "healthy" for c in checks.values()) else "degraded"
    )

    # Update gauge metrics while we have a session
    try:
        await update_gauge_metrics(session)
    except (TimeoutError, redis.ConnectionError, redis.TimeoutError):
        pass  # Don't fail health check if metrics update fails

    return {
        "status": overall_status,
        "version": "0.1.0",
        "uptime_seconds": round(uptime_seconds, 1),
        "checks": checks,
    }


@app.get("/health/ready")
async def health_ready(
    session: AsyncSession = Depends(get_session),
) -> dict[str, str | bool]:
    """Readiness probe - verifies database connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": True}
    except Exception as e:
        # Log full error details server-side, return generic message to client
        # to avoid leaking internal hostnames, connection strings, or credentials
        logger.error("Readiness check failed: %s", e)
        return {"status": "not_ready", "database": False}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness probe - basic check that app is running."""
    return {"status": "alive"}
