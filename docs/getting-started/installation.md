# Installation

## Docker (Recommended)

The easiest way to run Tessera is with Docker Compose:

```bash
git clone https://github.com/ashita-ai/tessera.git
cd tessera
docker compose up -d
```

This starts:
- Tessera API server on port 8000
- PostgreSQL database on port 5432
- Redis for caching (optional)

## Python Package

Install from PyPI:

```bash
pip install tessera-contracts
```

Or with uv:

```bash
uv add tessera-contracts
```

### Running the Server

```bash
# Set required environment variables
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/tessera"
export SECRET_KEY="your-secret-key-here"

# Run database migrations
alembic upgrade head

# Start the server
tessera serve
```

## From Source

```bash
# Clone the repository
git clone https://github.com/ashita-ai/tessera.git
cd tessera

# Install with uv
uv sync --all-extras

# Run migrations
DATABASE_URL=postgresql+asyncpg://... uv run alembic upgrade head

# Start the server
uv run uvicorn tessera.main:app --reload
```

## Database Setup

Tessera supports:

| Database | Use Case | Connection String |
|----------|----------|-------------------|
| PostgreSQL | Production | `postgresql+asyncpg://user:pass@host:5432/db` |
| SQLite | Development/Testing | `sqlite+aiosqlite:///./tessera.db` |

### PostgreSQL Setup

```bash
# Create database
createdb tessera

# Run migrations
DATABASE_URL=postgresql+asyncpg://localhost/tessera alembic upgrade head
```

### SQLite Setup (Development)

```bash
# SQLite works out of the box
DATABASE_URL=sqlite+aiosqlite:///./tessera.db alembic upgrade head
```

## Verify Installation

```bash
# Check health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status": "healthy"}
```

## Next Steps

- [Configuration](configuration.md) - Set up environment variables
- [Quickstart](quickstart.md) - Create your first contract
