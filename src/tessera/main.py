"""FastAPI application entry point."""

import asyncio
import importlib.metadata
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import redis
from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
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
    asset_context,
    assets,
    audit,
    audits,
    bulk,
    contracts,
    dependencies,
    discovery,
    graph,
    impact,
    impact_preview,
    otel,
    pending_proposals,
    preflight,
    proposals,
    registrations,
    repos,
    schemas,
    search,
    services,
    slack_configs,
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
from tessera.logging import configure_logging
from tessera.services.metrics import MetricsMiddleware, get_metrics, update_gauge_metrics
from tessera.web.routes import register_login_required_handler

# Track application start time for uptime calculation
_app_start_time = time.time()

logger = logging.getLogger(__name__)


async def bootstrap_admin_user() -> None:
    """Bootstrap an admin user from environment variables.

    This is idempotent and safe for k8s rolling restarts:
    - If the user doesn't exist, create them with admin role
    - If the user exists, update their password and ensure admin role

    Only runs when both ADMIN_USERNAME and ADMIN_PASSWORD are set.
    """
    if not settings.admin_username or not settings.admin_password:
        return
    from argon2 import PasswordHasher

    from tessera.db import TeamDB, UserDB
    from tessera.db.database import get_async_session_maker
    from tessera.models.enums import UserRole, UserType

    hasher = PasswordHasher()
    async_session = get_async_session_maker()

    async with async_session() as session:
        # Look up by username
        result = await session.execute(
            select(UserDB).where(UserDB.username == settings.admin_username)
        )
        user = result.scalar_one_or_none()

        if user:
            # Update existing user
            user.password_hash = hasher.hash(settings.admin_password)
            user.role = UserRole.ADMIN
            user.name = settings.admin_name
            user.user_type = UserType.HUMAN
            if settings.admin_email:
                user.email = settings.admin_email
            user.deactivated_at = None  # Re-activate if deactivated
            logger.info("Updated bootstrap admin user: %s", settings.admin_username)
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
                username=settings.admin_username,
                email=settings.admin_email,
                name=settings.admin_name,
                user_type=UserType.HUMAN,
                password_hash=hasher.hash(settings.admin_password),
                role=UserRole.ADMIN,
                team_id=team.id,
            )
            session.add(user)
            logger.info("Created bootstrap admin user: %s", settings.admin_username)

        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    configure_logging(level=settings.log_level, fmt=settings.log_format)

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

    # Start background repo sync worker
    sync_task = None
    if settings.sync_interval > 0:
        from tessera.services.repo_sync import start_background_worker

        sync_task = await start_background_worker()

    yield

    # Cancel background worker on shutdown
    if sync_task is not None:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    # Clean up database connections on shutdown
    await dispose_engine()


app = FastAPI(
    title="Tessera",
    description="Service contract coordination",
    version=importlib.metadata.version("tessera-contracts"),
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
api_v1.include_router(asset_context.router, prefix="/assets", tags=["assets"])
api_v1.include_router(assets.router, prefix="/assets", tags=["assets"])
api_v1.include_router(audits.router, prefix="/assets", tags=["audits"])
api_v1.include_router(dependencies.router, prefix="/assets", tags=["dependencies"])
api_v1.include_router(impact.router, prefix="/assets", tags=["impact"])
api_v1.include_router(impact_preview.router, prefix="/assets", tags=["impact-preview"])
api_v1.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_v1.include_router(registrations.router, prefix="/registrations", tags=["registrations"])
api_v1.include_router(proposals.router, prefix="/proposals", tags=["proposals"])
api_v1.include_router(pending_proposals.router, tags=["proposals"])
api_v1.include_router(repos.router, prefix="/repos", tags=["repos"])
api_v1.include_router(services.router, prefix="/services", tags=["services"])
api_v1.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
api_v1.include_router(sync.router, prefix="/sync", tags=["sync"])
api_v1.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_v1.include_router(search.router)
api_v1.include_router(slack_configs.router, prefix="/slack/configs", tags=["slack"])
api_v1.include_router(webhooks.router)
api_v1.include_router(audit.router)
api_v1.include_router(preflight.router, prefix="/assets", tags=["preflight"])
api_v1.include_router(discovery.router, prefix="/discovery", tags=["discovery"])
api_v1.include_router(graph.router, prefix="/graph", tags=["graph"])
api_v1.include_router(otel.router, prefix="/otel", tags=["otel"])
api_v1.include_router(bulk.router, prefix="/bulk", tags=["bulk"])

app.include_router(api_v1)

# Static files — React SPA only, no legacy fallback.
static_dir = Path(__file__).parent / "static"
spa_dist_dir = static_dir / "dist"
images_dir = static_dir / "images"

# Favicons and logo referenced by the SPA via /static/images/.
if images_dir.exists():
    app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="static-images")

# Vite build assets: JS/CSS bundles at /assets/index-*.{js,css}.
if spa_dist_dir.exists() and (spa_dist_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(spa_dist_dir / "assets")), name="spa-assets")

# SPA catch-all entry point.
_spa_index = spa_dist_dir / "index.html" if spa_dist_dir.exists() else None


def _read_spa_html() -> str | None:
    """Read SPA index.html from disk so frontend rebuilds apply without restart."""
    if _spa_index and _spa_index.exists():
        return _spa_index.read_text()
    return None


# Auth routes: POST /login (form submission) and GET /logout.
# GET /login is served by the SPA catch-all (React renders the login page).
_auth_router = APIRouter(tags=["auth"])


@_auth_router.post("/login")
async def login_submit_handler(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Handle login form submission."""
    from tessera.web.routes import login_submit

    return await login_submit(request, username, password, session)


@_auth_router.get("/logout")
async def logout_handler(request: Request) -> Any:
    """Handle logout."""
    from tessera.web.routes import logout

    return await logout(request)


app.include_router(_auth_router)


# SPA catch-all must be the LAST route. We define it as a function and register
# it after /health and /metrics (see below).
def _register_spa_catchall() -> None:
    """Register the SPA catch-all AFTER all other routes."""

    # Paths that should NOT be handled by the SPA catch-all
    _non_spa_prefixes = (
        "/api/",
        "/static/",
        "/assets/",
        "/health",
        "/metrics",
        "/logout",
    )

    @app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    async def spa_catchall(path: str) -> HTMLResponse:
        """Serve the React SPA for all non-API, non-system routes."""
        full_path = f"/{path}"
        if any(full_path.startswith(p) for p in _non_spa_prefixes):
            raise HTTPException(status_code=404, detail="Not found")
        spa_html = _read_spa_html()
        if spa_html:
            return HTMLResponse(spa_html)
        raise HTTPException(status_code=404, detail="Not found")


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
        logger.debug("Pool introspection failed during health check", exc_info=True)

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


# Register SPA catch-all LAST so /health, /metrics, and other routes take priority.
_register_spa_catchall()
