# Tessera

Data contract coordination for warehouses.

## The Problem

Data contracts tell you something is wrong. They don't tell you what to do about it.

The Kafka ecosystem solved producer/consumer coordination with schema registries. Warehouses have nothing equivalent. When a producer wants to drop a column, the workflow is tribal knowledge: Slack threads, Confluence pages, and hope.

## How It Works

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#6366f1', 'primaryTextColor': '#fff', 'primaryBorderColor': '#4f46e5', 'lineColor': '#475569', 'secondaryColor': '#f1f5f9', 'tertiaryColor': '#f8fafc', 'noteBkgColor': '#fef3c7', 'noteTextColor': '#78350f', 'noteBorderColor': '#f59e0b', 'actorBkg': '#1e293b', 'actorTextColor': '#f8fafc', 'actorBorder': '#475569', 'signalColor': '#475569', 'signalTextColor': '#0f172a'}}}%%
sequenceDiagram
    autonumber
    participant P as 📦 Producer
    participant T as ⚡ Tessera
    participant C as 👥 Consumer

    rect rgba(34, 197, 94, 0.15)
        Note over P,C: 🟢 BEFORE: Initial Setup
        P->>T: Create Asset
        P->>T: Publish Contract v1.0.0
        C->>T: Register as consumer
        Note over C: ✓ Using v1.0.0
    end

    rect rgba(241, 245, 249, 0.6)
        Note over P,C: ⏳ Production usage...
    end

    rect rgba(239, 68, 68, 0.12)
        Note over P,C: 🔴 AFTER: Breaking Change Proposed
        P->>T: Publish breaking change
        T-->>T: Detect incompatibility
        T->>C: ⚠️ Notify: schema changing
    end

    rect rgba(59, 130, 246, 0.12)
        Note over P,C: 🔵 RESOLUTION
        alt ✅ Approved
            C->>T: Acknowledge OK
            T->>P: All clear
            P->>T: Publish v2.0.0
            Note over C: ✓ Migrated to v2.0.0
        else 🚫 Blocked
            C->>T: Acknowledge BLOCKED
            T-->>P: Cannot proceed
            Note over C: ✓ Still on v1.0.0
        end
    end
```

**Producers** own assets and publish versioned contracts (JSON Schema + guarantees).

**Consumers** register dependencies on contracts they use.

**Breaking changes** create proposals that block until affected consumers acknowledge.

## Quick Start

```bash
# Install
uv sync --all-extras

# Configure
cp .env.example .env
# Edit DATABASE_URL

# Run migrations
alembic upgrade head

# Start server
uv run uvicorn tessera.main:app --reload

# Test
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest
```

## CLI

```bash
tessera team create "Analytics"
tessera asset create warehouse.core.users --team <team-id>
tessera contract publish --asset <id> --team <id> --version 1.0.0 --schema schema.json
tessera register --asset <id> --team <consumer-id>
tessera proposal acknowledge <id> --team <id> --response approved
```

Full reference: [docs/cli.md](docs/cli.md)

## API

All endpoints under `/api/v1`. Interactive docs at `/docs`.

| Resource | Endpoints |
|----------|-----------|
| Teams | CRUD + restore |
| Assets | CRUD + restore, dependencies, lineage |
| Contracts | Publish, list, diff, compare, impact analysis |
| Registrations | CRUD (consumer dependencies) |
| Proposals | List, acknowledge, withdraw, force, publish |
| Sync | Push/pull state, dbt manifest sync |
| Admin | API keys, webhooks, audit trail |

Full reference: [docs/api.md](docs/api.md)

## Deployment

Docker Compose, Kubernetes, and Helm deployment options: [docs/deployment.md](docs/deployment.md)

## Compatibility Modes

| Mode | Breaking if... |
|------|----------------|
| `backward` | Remove field, add required, narrow type |
| `forward` | Add field, remove required, widen type |
| `full` | Any schema change |
| `none` | Nothing (notify only) |

## Configuration

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL or SQLite connection string |
| `AUTH_DISABLED` | Skip auth for development (`true`/`false`) |
| `BOOTSTRAP_API_KEY` | Initial admin key for setup |
| `ENVIRONMENT` | `development` or `production` |
| `CORS_ORIGINS` | Allowed origins (comma-separated) |
| `REDIS_URL` | Redis for caching (optional) |

## Database

**PostgreSQL** (production): Full support with migrations via Alembic.

**SQLite** (development): `DATABASE_URL=sqlite+aiosqlite:///:memory:`

## Status

Early development.
