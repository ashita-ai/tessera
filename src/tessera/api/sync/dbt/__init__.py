"""dbt sync endpoints package.

Provides endpoints for synchronizing schemas from dbt manifest.json
for auto-registering assets and contracts.
"""

from fastapi import APIRouter

from tessera.api.sync.dbt.diff import router as diff_router
from tessera.api.sync.dbt.upload import router as upload_router

router = APIRouter()
router.include_router(upload_router)
router.include_router(diff_router)

__all__ = ["router"]
