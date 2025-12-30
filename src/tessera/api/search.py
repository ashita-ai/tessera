"""Global search API endpoint."""

from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.api.auth import Auth, RequireRead
from tessera.db import get_session
from tessera.db.models import AssetDB, ContractDB, TeamDB, UserDB
from tessera.services.cache import cache_global_search, get_cached_global_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchEntityType(str, Enum):
    """Entity types supported by global search."""

    teams = "teams"
    users = "users"
    assets = "assets"
    contracts = "contracts"


@router.get("")
async def search(
    auth: Auth,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50, description="Max results per entity type"),
    types: list[SearchEntityType] | None = Query(None, description="Limit results to entity types"),
    _: None = RequireRead,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search across teams, users, assets, and contracts.

    Returns results grouped by entity type with matches highlighted.
    Search is case-insensitive and matches partial strings.
    """
    if limit == 10 and not types:
        cached = await get_cached_global_search(q, limit)
        if cached:
            return cached

    type_values = (
        {item.value for item in types}
        if types
        else {
            "teams",
            "users",
            "assets",
            "contracts",
        }
    )

    search_term = f"%{q.lower()}%"

    # Search teams by name
    teams: list[TeamDB] = []
    if "teams" in type_values:
        teams_result = await session.execute(
            select(TeamDB)
            .where(TeamDB.deleted_at.is_(None))
            .where(TeamDB.name.ilike(search_term))
            .limit(limit)
        )
        teams = list(teams_result.scalars().all())

    # Search users by name or email
    users: list[UserDB] = []
    if "users" in type_values:
        users_result = await session.execute(
            select(UserDB)
            .where(UserDB.deactivated_at.is_(None))
            .where(or_(UserDB.name.ilike(search_term), UserDB.email.ilike(search_term)))
            .limit(limit)
        )
        users = list(users_result.scalars().all())

    # Search assets by FQN
    assets: list[AssetDB] = []
    if "assets" in type_values:
        assets_result = await session.execute(
            select(AssetDB)
            .where(AssetDB.deleted_at.is_(None))
            .where(AssetDB.fqn.ilike(search_term))
            .limit(limit)
        )
        assets = list(assets_result.scalars().all())

    # Search contracts by version (less common but useful)
    contracts: list[ContractDB] = []
    if "contracts" in type_values:
        contracts_result = await session.execute(
            select(ContractDB).where(ContractDB.version.ilike(search_term)).limit(limit)
        )
        contracts = list(contracts_result.scalars().all())

    response = {
        "query": q,
        "results": {
            "teams": [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "type": "team",
                }
                for t in teams
            ],
            "users": [
                {
                    "id": str(u.id),
                    "name": u.name,
                    "team_id": str(u.team_id) if u.team_id else None,
                    "type": "user",
                }
                for u in users
            ],
            "assets": [
                {
                    "id": str(a.id),
                    "fqn": a.fqn,
                    "resource_type": a.resource_type.value if a.resource_type else None,
                    "type": "asset",
                }
                for a in assets
            ],
            "contracts": [
                {
                    "id": str(c.id),
                    "version": c.version,
                    "asset_id": str(c.asset_id),
                    "status": c.status.value if c.status else None,
                    "type": "contract",
                }
                for c in contracts
            ],
        },
        "counts": {
            "teams": len(teams),
            "users": len(users),
            "assets": len(assets),
            "contracts": len(contracts),
            "total": len(teams) + len(users) + len(assets) + len(contracts),
        },
    }
    if limit == 10 and not types:
        await cache_global_search(q, limit, response)
    return response
