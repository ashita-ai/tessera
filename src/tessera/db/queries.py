"""Query helpers that enforce soft-delete filtering.

Use these helpers as the starting point for queries against soft-deletable
models to ensure deleted records are never accidentally included.

For models with ``deleted_at``: AssetDB, TeamDB, RegistrationDB,
AssetDependencyDB, RepoDB, ServiceDB.

For users with ``deactivated_at``: UserDB.

Generic helper: ``active_only(query, Model)`` appends the appropriate
``WHERE deleted_at IS NULL`` (or ``deactivated_at IS NULL``) clause.
"""

from typing import Any, TypeVar

from sqlalchemy import Select, select

from tessera.db.models import (
    AssetDB,
    AssetDependencyDB,
    RegistrationDB,
    RepoDB,
    ServiceDB,
    TeamDB,
    UserDB,
)

_T = TypeVar("_T")


def active_only(query: Select[Any], model: type[Any]) -> Select[Any]:
    """Append a soft-delete filter to *query* for the given *model*.

    Handles both ``deleted_at`` and ``deactivated_at`` columns.
    """
    if hasattr(model, "deleted_at"):
        return query.where(model.deleted_at.is_(None))
    if hasattr(model, "deactivated_at"):
        return query.where(model.deactivated_at.is_(None))
    return query


def active_assets() -> Select[tuple[AssetDB]]:
    """Base query for non-deleted assets."""
    return select(AssetDB).where(AssetDB.deleted_at.is_(None))


def active_registrations() -> Select[tuple[RegistrationDB]]:
    """Base query for non-deleted registrations."""
    return select(RegistrationDB).where(RegistrationDB.deleted_at.is_(None))


def active_teams() -> Select[tuple[TeamDB]]:
    """Base query for non-deleted teams."""
    return select(TeamDB).where(TeamDB.deleted_at.is_(None))


def active_dependencies() -> Select[tuple[AssetDependencyDB]]:
    """Base query for non-deleted dependencies."""
    return select(AssetDependencyDB).where(AssetDependencyDB.deleted_at.is_(None))


def active_repos() -> Select[tuple[RepoDB]]:
    """Base query for non-deleted repos."""
    return select(RepoDB).where(RepoDB.deleted_at.is_(None))


def active_services() -> Select[tuple[ServiceDB]]:
    """Base query for non-deleted services."""
    return select(ServiceDB).where(ServiceDB.deleted_at.is_(None))


def active_users() -> Select[tuple[UserDB]]:
    """Base query for non-deactivated users."""
    return select(UserDB).where(UserDB.deactivated_at.is_(None))
