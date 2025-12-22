# tessera

Data contract coordination for warehouses.

## The Problem

Data contracts tell you something is wrong. They don't tell you what to do about it.

The Kafka ecosystem solved producer/consumer coordination years ago with schema registries. Warehouses have nothing equivalent. When a producer wants to drop a column, rename a field, or change a type, the workflow is tribal knowledge: Slack threads, Confluence pages, and hope.

## What Tessera Does

Tessera is a coordination layer between data producers and consumers. It tracks:

- **Who owns what**: Explicit ownership of tables, views, and models
- **Who depends on what**: Consumers register their dependencies
- **What's changing**: Producers propose schema changes
- **Who's affected**: Impact analysis before deploy
- **Who's acknowledged**: Breaking changes require consumer sign-off

## Core Concepts

**Asset**: A data object (table, view, dbt model) with an owner.

**Contract**: A versioned schema plus guarantees—freshness, volume bounds, nullability, accepted values.

**Registration**: A consumer declaring "I depend on this contract."

**Proposal**: A producer requesting a breaking change. Triggers notifications to affected consumers.

**Acknowledgment**: A consumer responding to a proposal—approved, blocked, or migrating.

## The Name

In ancient Rome, a *tessera* was a token split between two parties to prove identity or agreement. Each half was meaningless alone. Matching edges proved the agreement was valid.

That's the producer/consumer relationship. Neither side works alone. Tessera makes the agreement explicit.

## Database Support

**PostgreSQL** (Recommended for production)
- Full support with schemas: `core`, `workflow`, `audit`
- Use Alembic migrations: `alembic upgrade head`

**SQLite** (Testing only)
- Supported for unit tests via in-memory databases
- Set `DATABASE_URL=sqlite+aiosqlite:///:memory:`
- Tables created without schema prefixes
- Not recommended for production

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Set up environment
cp .env.example .env
# Edit .env with your DATABASE_URL

# Run migrations
alembic upgrade head

# Start the server
uv run uvicorn tessera.main:app --reload

# Run tests
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest
```

## Production Configuration

For production deployments, ensure the following environment variables are set:

- `ENVIRONMENT=production`: Enables security restrictions (e.g., tighter CORS).
- `CORS_ORIGINS`: Comma-separated list of allowed origins (no `*`).
- `AUTH_DISABLED=false`: Ensure authentication is enabled.
- `BOOTSTRAP_API_KEY`: Set a strong bootstrap key for initial setup.
- `DATABASE_URL`: Use a robust PostgreSQL database.
- `REDIS_URL`: Enable Redis for caching.

### CORS in Production
In production, Tessera restricts allowed HTTP methods to `GET, POST, PATCH, DELETE, OPTIONS`. Wildcard origins are disabled; you must explicitly list your frontend domains in `CORS_ORIGINS`.

## Status

Early development.
