"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException

from tessera.api import (
    api_keys,
    assets,
    audit,
    contracts,
    dependencies,
    impact,
    proposals,
    registrations,
    schemas,
    sync,
    teams,
    webhooks,
)
from tessera.api.errors import (
    APIError,
    RequestIDMiddleware,
    api_error_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from tessera.api.rate_limit import limiter, rate_limit_exceeded_handler
from tessera.config import settings
from tessera.db import init_db
from tessera.db.database import dispose_engine, get_async_session_maker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    await init_db()
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

# Request ID middleware (must be added first to wrap all other middleware)
app.add_middleware(RequestIDMiddleware)

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

# API v1 router
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(teams.router, prefix="/teams", tags=["teams"])
api_v1.include_router(assets.router, prefix="/assets", tags=["assets"])
api_v1.include_router(dependencies.router, prefix="/assets", tags=["dependencies"])
api_v1.include_router(impact.router, prefix="/assets", tags=["impact"])
api_v1.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_v1.include_router(registrations.router, prefix="/registrations", tags=["registrations"])
api_v1.include_router(proposals.router, prefix="/proposals", tags=["proposals"])
api_v1.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
api_v1.include_router(sync.router, prefix="/sync", tags=["sync"])
api_v1.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_v1.include_router(webhooks.router)
api_v1.include_router(audit.router)

app.include_router(api_v1)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect root to API documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic health check endpoint (liveness probe)."""
    return {"status": "healthy"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str | bool]:
    """Readiness probe - verifies database connectivity."""
    try:
        async_session = get_async_session_maker()
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": True}
    except Exception as e:
        return {"status": "not_ready", "database": False, "error": str(e)}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness probe - basic check that app is running."""
    return {"status": "alive"}
