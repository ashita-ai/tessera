"""Assets API — aggregated router from focused submodules.

Submodules:
    crud        – create, get, update, delete, restore
    search      – list, search, bulk-assign
    publishing  – contract publishing (write path)
    contracts   – contract listing, history, diff, version preview (read path)
    helpers     – shared utilities and constants
"""

from fastapi import APIRouter

# Re-export for backward compatibility with external imports:
#   from tessera.api.assets import get_asset       (tests/test_caching.py)
#   from tessera.api.assets import parse_semver     (tests/test_webhooks.py)
from tessera.services.versioning import parse_semver

from .contracts import router as contracts_router
from .crud import get_asset
from .crud import router as crud_router
from .publishing import router as publishing_router
from .search import router as search_router

__all__ = ["get_asset", "parse_semver", "router"]

router = APIRouter()

# Aggregate routes directly to preserve empty-path routes (e.g. POST "", GET "")
# that FastAPI 0.125+ rejects via include_router when both prefix and path are empty.
# Order matters: search_router must precede crud_router so that fixed paths like
# /search and /bulk-assign are matched before the /{asset_id} parameter route.
for _sub in (search_router, crud_router, publishing_router, contracts_router):
    router.routes.extend(_sub.routes)
