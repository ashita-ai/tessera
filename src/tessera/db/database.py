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
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.config import settings
from tessera.db.models import Base

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Initialize database schemas and tables.

    Note: This function requires PostgreSQL. For SQLite, use Alembic migrations
    which handle schema differences automatically.
    """
    async with engine.begin() as conn:
        # Create schemas first (required for table creation)
        # These statements will fail on SQLite - use Alembic migrations instead
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        # Then create tables
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for a single request.

    The session wraps the request in a transaction:
    - Commits on successful completion
    - Rolls back on any exception

    For multi-step atomic operations, use session.begin_nested() for savepoints.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
