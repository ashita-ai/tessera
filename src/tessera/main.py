"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import text
from starlette.exceptions import HTTPException

from tessera.api import assets, contracts, proposals, registrations, schemas, sync, teams
from tessera.api.errors import (
    APIError,
    RequestIDMiddleware,
    api_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from tessera.config import settings
from tessera.db import init_db
from tessera.db.database import async_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    await init_db()
    yield


app = FastAPI(
    title="Tessera",
    description="Data contract coordination for warehouses",
    version="0.1.0",
    lifespan=lifespan,
)

# Request ID middleware (must be added first to wrap all other middleware)
app.add_middleware(RequestIDMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(ValidationError, validation_exception_handler)

# API v1 router
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(teams.router, prefix="/teams", tags=["teams"])
api_v1.include_router(assets.router, prefix="/assets", tags=["assets"])
api_v1.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_v1.include_router(registrations.router, prefix="/registrations", tags=["registrations"])
api_v1.include_router(proposals.router, prefix="/proposals", tags=["proposals"])
api_v1.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
api_v1.include_router(sync.router, prefix="/sync", tags=["sync"])

app.include_router(api_v1)


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic health check endpoint (liveness probe)."""
    return {"status": "healthy"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str | bool]:
    """Readiness probe - verifies database connectivity."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": True}
    except Exception as e:
        return {"status": "not_ready", "database": False, "error": str(e)}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness probe - basic check that app is running."""
    return {"status": "alive"}
