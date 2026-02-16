"""Query helpers that enforce soft-delete filtering.

Use these helpers as the starting point for queries against soft-deletable
models to ensure deleted records are never accidentally included.
"""

from sqlalchemy import Select, select

from tessera.db.models import AssetDB, RegistrationDB, TeamDB


def active_assets() -> Select[tuple[AssetDB]]:
    """Base query for non-deleted assets."""
    return select(AssetDB).where(AssetDB.deleted_at.is_(None))


def active_registrations() -> Select[tuple[RegistrationDB]]:
    """Base query for non-deleted registrations."""
    return select(RegistrationDB).where(RegistrationDB.deleted_at.is_(None))


def active_teams() -> Select[tuple[TeamDB]]:
    """Base query for non-deleted teams."""
    return select(TeamDB).where(TeamDB.deleted_at.is_(None))
