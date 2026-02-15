"""Database connection and session management.

Transaction Model
-----------------
Each API request gets a single database session via get_session(). The session
wraps the entire request in a transaction that:
- Commits after the endpoint returns successfully
- Rolls back on any exception

For multi-step operations (e.g., create contract + deprecate old + audit log),
endpoints should use session.begin_nested() to create savepoints. This ensures
all steps complete atomically even if an error occurs mid-operation.

Database Support
----------------
- **PostgreSQL**: Full support with schemas (core, workflow, audit)
- **SQLite**: Supported for testing via in-memory databases (DATABASE_URL=sqlite+aiosqlite:///:memory:)
  - Note: SQLite does not support schemas, so tables are created without schema prefixes
  - init_db() will fail on SQLite due to CREATE SCHEMA statements; use Alembic migrations instead

Production Configuration
------------------------
Set AUTO_CREATE_TABLES=false in production to require Alembic migrations instead
of automatic table creation. This prevents accidental schema changes and ensures
all database changes go through proper migration review.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tessera.config import settings
from tessera.db.models import Base

logger = logging.getLogger(__name__)

# Lazy engine initialization to avoid creating connections at import time
_engine: AsyncEngine | None = None
_async_session: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the database engine (lazy initialization).

    Configures connection pooling for PostgreSQL. SQLite uses NullPool
    (no pooling) as it doesn't support concurrent connections.
    """
    global _engine
    if _engine is None:
        # SQLite doesn't support connection pooling
        is_sqlite = settings.database_url.startswith("sqlite")
        if is_sqlite:
            from sqlalchemy.pool import StaticPool

            _engine = create_async_engine(
                settings.database_url,
                echo=False,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            # PostgreSQL with connection pooling
            _engine = create_async_engine(
                settings.database_url,
                echo=False,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_recycle=settings.db_pool_recycle,
                pool_pre_ping=True,  # Verify connections before use
            )
    return _engine


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session maker."""
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session


async def dispose_engine() -> None:
    """Dispose of the database engine and clean up connections."""
    global _engine, _async_session
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session = None


async def init_db() -> None:
    """Initialize database schemas and tables.

    Supports both PostgreSQL (with schemas) and SQLite (without schemas).

    Behavior is controlled by the AUTO_CREATE_TABLES setting:
    - True (default): Automatically create schemas and tables
    - False: Skip table creation (requires Alembic migrations)

    In production, set AUTO_CREATE_TABLES=false to ensure all schema changes
    go through proper migration review.
    """
    if not settings.auto_create_tables:
        logger.info(
            "Skipping automatic table creation (AUTO_CREATE_TABLES=false). "
            "Ensure database is initialized via Alembic migrations."
        )
        return

    engine = get_engine()
    is_sqlite = settings.database_url.startswith("sqlite")

    logger.info("Creating database schemas and tables (AUTO_CREATE_TABLES=true)")
    async with engine.begin() as conn:
        if not is_sqlite:
            # PostgreSQL: Create schemas first (required for table creation)
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        # Create tables
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for a single request.

    The session wraps the request in a transaction:
    - Commits on successful completion
    - Rolls back on any exception

    For multi-step atomic operations, use session.begin_nested() for savepoints.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
