"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from tessera.api import assets, contracts, proposals, registrations, sync, teams
from tessera.db import init_db


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

# Include routers
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.include_router(assets.router, prefix="/assets", tags=["assets"])
app.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
app.include_router(registrations.router, prefix="/registrations", tags=["registrations"])
app.include_router(proposals.router, prefix="/proposals", tags=["proposals"])
app.include_router(sync.router, prefix="/sync", tags=["sync"])


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
