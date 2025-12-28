"""Global search API endpoint."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import get_session
from tessera.db.models import AssetDB, ContractDB, TeamDB, UserDB

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50, description="Max results per entity type"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search across teams, users, assets, and contracts.

    Returns results grouped by entity type with matches highlighted.
    Search is case-insensitive and matches partial strings.
    """
    search_term = f"%{q.lower()}%"

    # Search teams by name
    teams_result = await session.execute(
        select(TeamDB)
        .where(TeamDB.deleted_at.is_(None))
        .where(TeamDB.name.ilike(search_term))
        .limit(limit)
    )
    teams = teams_result.scalars().all()

    # Search users by name or email
    users_result = await session.execute(
        select(UserDB)
        .where(UserDB.deactivated_at.is_(None))
        .where(or_(UserDB.name.ilike(search_term), UserDB.email.ilike(search_term)))
        .limit(limit)
    )
    users = users_result.scalars().all()

    # Search assets by FQN
    assets_result = await session.execute(
        select(AssetDB)
        .where(AssetDB.deleted_at.is_(None))
        .where(AssetDB.fqn.ilike(search_term))
        .limit(limit)
    )
    assets = assets_result.scalars().all()

    # Search contracts by version (less common but useful)
    contracts_result = await session.execute(
        select(ContractDB).where(ContractDB.version.ilike(search_term)).limit(limit)
    )
    contracts = contracts_result.scalars().all()

    return {
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
                    "email": u.email,
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
