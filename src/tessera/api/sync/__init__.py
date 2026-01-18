"""Sync API endpoints package.

Provides endpoints for synchronizing schemas from external sources:
- dbt manifest.json for auto-registering assets and contracts
- OpenAPI specifications for API endpoint contracts
- GraphQL introspection for GraphQL schema contracts
"""

from fastapi import APIRouter

from tessera.api.sync.dbt import router as dbt_router
from tessera.api.sync.graphql import router as graphql_router
from tessera.api.sync.openapi import router as openapi_router

router = APIRouter()
router.include_router(dbt_router)
router.include_router(openapi_router)
router.include_router(graphql_router)

__all__ = ["router"]
