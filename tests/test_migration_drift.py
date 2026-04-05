"""Verify Alembic migrations produce the same schema as models.py create_all().

This test prevents the migration chain from drifting out of sync with the
SQLAlchemy model definitions. It creates two in-memory SQLite databases —
one via Alembic ``upgrade head``, one via ``Base.metadata.create_all()`` —
and asserts they have identical tables, columns, and constraints.
"""

import os
import tempfile
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect

from alembic import command
from alembic.config import Config
from tessera.db.models import Base

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_alembic_config(db_url: str) -> Config:
    """Build an Alembic Config pointing at the given database URL."""
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    # Prevent Alembic from trying to use asyncpg for SQLite
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    return cfg


def _normalize_type(type_str: str) -> str:
    """Normalize SQLAlchemy type representations for comparison.

    SQLite represents all types as strings; minor formatting differences
    (e.g. ``VARCHAR(255)`` vs ``VARCHAR(length=255)``) should not cause
    false failures.
    """
    return str(type_str).upper().replace(" ", "")


def _get_schema_snapshot(engine: Engine) -> dict:
    """Extract a comparable schema snapshot from a database."""
    insp = inspect(engine)
    snapshot: dict = {}

    for table_name in sorted(insp.get_table_names()):
        if table_name == "alembic_version":
            continue

        columns = {}
        for col in insp.get_columns(table_name):
            columns[col["name"]] = {
                "type": _normalize_type(col["type"]),
                "nullable": col["nullable"],
            }

        unique_constraints = set()
        for uc in insp.get_unique_constraints(table_name):
            unique_constraints.add((uc["name"] or "", tuple(sorted(uc["column_names"]))))

        indexes = set()
        for idx in insp.get_indexes(table_name):
            indexes.add((idx["name"], tuple(sorted(idx["column_names"])), idx.get("unique", False)))

        snapshot[table_name] = {
            "columns": columns,
            "unique_constraints": unique_constraints,
            "indexes": indexes,
        }

    return snapshot


def test_migrations_match_models() -> None:
    """Assert that running all migrations produces the same schema as create_all()."""
    # ── DB 1: built by Alembic migrations ──
    # Use a temp file because Alembic opens its own connection.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        migration_db_path = f.name

    try:
        migration_url = f"sqlite:///{migration_db_path}"
        # Set DATABASE_URL so env.py picks it up (it converts async URLs but
        # passes sqlite URLs through unchanged).
        old_env = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = migration_url
        try:
            cfg = _get_alembic_config(migration_url)
            command.upgrade(cfg, "head")
        finally:
            if old_env is not None:
                os.environ["DATABASE_URL"] = old_env
            else:
                os.environ.pop("DATABASE_URL", None)

        migration_engine = create_engine(migration_url)
        migration_snapshot = _get_schema_snapshot(migration_engine)
        migration_engine.dispose()
    finally:
        Path(migration_db_path).unlink(missing_ok=True)

    # ── DB 2: built by create_all() ──
    model_engine = create_engine("sqlite:///:memory:")
    with model_engine.begin() as conn:
        Base.metadata.create_all(conn)
    model_snapshot = _get_schema_snapshot(model_engine)
    model_engine.dispose()

    # ── Compare ──
    migration_tables = set(migration_snapshot.keys())
    model_tables = set(model_snapshot.keys())

    missing_from_migrations = model_tables - migration_tables
    extra_in_migrations = migration_tables - model_tables

    errors: list[str] = []

    if missing_from_migrations:
        errors.append(f"Tables in models but NOT in migrations: {sorted(missing_from_migrations)}")
    if extra_in_migrations:
        errors.append(f"Tables in migrations but NOT in models: {sorted(extra_in_migrations)}")

    # Compare columns, types, nullability, constraints, and indexes
    common_tables = migration_tables & model_tables
    for table in sorted(common_tables):
        mig_cols = migration_snapshot[table]["columns"]
        mod_cols = model_snapshot[table]["columns"]

        mig_col_names = set(mig_cols.keys())
        mod_col_names = set(mod_cols.keys())

        missing_cols = mod_col_names - mig_col_names
        extra_cols = mig_col_names - mod_col_names

        if missing_cols:
            errors.append(
                f"Table '{table}': columns in models but NOT in migrations: {sorted(missing_cols)}"
            )
        if extra_cols:
            errors.append(
                f"Table '{table}': columns in migrations but NOT in models: {sorted(extra_cols)}"
            )

        # Compare type and nullability for columns present in both
        for col in sorted(mig_col_names & mod_col_names):
            mig_type = mig_cols[col]["type"]
            mod_type = mod_cols[col]["type"]
            if mig_type != mod_type:
                errors.append(
                    f"Table '{table}', column '{col}': type mismatch — "
                    f"migration={mig_type}, model={mod_type}"
                )

            mig_nullable = mig_cols[col]["nullable"]
            mod_nullable = mod_cols[col]["nullable"]
            if mig_nullable != mod_nullable:
                errors.append(
                    f"Table '{table}', column '{col}': nullable mismatch — "
                    f"migration={mig_nullable}, model={mod_nullable}"
                )

        # Compare unique constraints
        mig_ucs = migration_snapshot[table]["unique_constraints"]
        mod_ucs = model_snapshot[table]["unique_constraints"]
        missing_ucs = mod_ucs - mig_ucs
        extra_ucs = mig_ucs - mod_ucs
        if missing_ucs:
            errors.append(
                f"Table '{table}': unique constraints in models "
                f"but NOT in migrations: {sorted(missing_ucs)}"
            )
        if extra_ucs:
            errors.append(
                f"Table '{table}': unique constraints in migrations "
                f"but NOT in models: {sorted(extra_ucs)}"
            )

        # Compare indexes
        mig_idxs = migration_snapshot[table]["indexes"]
        mod_idxs = model_snapshot[table]["indexes"]
        missing_idxs = mod_idxs - mig_idxs
        extra_idxs = mig_idxs - mod_idxs
        if missing_idxs:
            errors.append(
                f"Table '{table}': indexes in models but NOT in migrations: {sorted(missing_idxs)}"
            )
        if extra_idxs:
            errors.append(
                f"Table '{table}': indexes in migrations but NOT in models: {sorted(extra_idxs)}"
            )

    if errors:
        raise AssertionError(
            "Migration/model drift detected:\n" + "\n".join(f"  - {e}" for e in errors)
        )
