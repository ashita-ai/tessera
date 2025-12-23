<p align="center">
  <img src="assets/logo.png" alt="Tessera" width="300">
</p>

<h3 align="center">Data contract coordination for warehouses</h3>

## The Problem

Data contracts tell you something is wrong. They don't tell you what to do about it.

The Kafka ecosystem solved producer/consumer coordination with schema registries. Warehouses have nothing equivalent. When a producer wants to drop a column, the workflow is tribal knowledge: Slack threads, Confluence pages, and hope.

## How It Works

**Without Tessera** — breaking changes break things:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#dc2626', 'primaryTextColor': '#fff', 'primaryBorderColor': '#b91c1c', 'lineColor': '#6b7280', 'noteBkgColor': '#fef2f2', 'noteTextColor': '#7f1d1d', 'noteBorderColor': '#fca5a5', 'actorBkg': '#6b7280', 'actorTextColor': '#f9fafb', 'actorBorder': '#4b5563', 'signalColor': '#6b7280', 'signalTextColor': '#1f2937'}}}%%
sequenceDiagram
    participant P as 📦 Producer
    participant C as 👥 Consumer

    P->>P: Drop column from table
    P--xC: 💥 Pipeline fails at 3am
    Note over C: ❌ No warning<br/>❌ No migration time<br/>❌ Broken dashboards
    C->>P: 😡 Slack: "Who broke prod?"
```

**With Tessera** — coordinate before you ship:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#6366f1', 'primaryTextColor': '#fff', 'primaryBorderColor': '#4f46e5', 'lineColor': '#475569', 'noteBkgColor': '#f0fdf4', 'noteTextColor': '#14532d', 'noteBorderColor': '#86efac', 'actorBkg': '#1e293b', 'actorTextColor': '#f8fafc', 'actorBorder': '#475569', 'signalColor': '#475569', 'signalTextColor': '#0f172a'}}}%%
sequenceDiagram
    participant P as 📦 Producer
    participant T as ⚡ Tessera
    participant C as 👥 Consumer

    P->>T: Propose: drop column
    T-->>T: Detect breaking change
    T->>C: ⚠️ "Producer wants to drop user_id"
    C->>T: ✅ Approve (migrated)
    T->>P: All consumers ready
    P->>T: Ship v2.0.0
    Note over P,C: ✓ Zero downtime, no one paged
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

## dbt Integration

Tessera extracts contract guarantees directly from dbt tests:

| dbt Test | Tessera Guarantee |
|----------|-------------------|
| `not_null` | `nullability: {column: "never"}` |
| `accepted_values` | `accepted_values: {column: [...]}` |
| `unique` | `custom: {type: "unique", ...}` |
| `relationships` | `custom: {type: "relationships", ...}` |
| `dbt_expectations.*` | `custom: {type: "test_name", ...}` |
| Singular tests (SQL) | `custom: {type: "singular", sql: "..."}` |

**Singular tests** are SQL files in your `tests/` directory that express business logic assertions. Tessera captures these as contract guarantees — removing them is a breaking change.

```sql
-- tests/assert_revenue_positive.sql
SELECT revenue_id, amount
FROM {{ ref('fct_revenue') }}
WHERE status = 'completed' AND amount <= 0
```

### WAP (Write-Audit-Publish) Integration

Tessera tracks data quality audit results for visibility into runtime enforcement:

```yaml
# dbt_project.yml
on-run-end:
  - "python scripts/report_to_tessera.py"
```

The script parses `target/run_results.json` and reports to Tessera:

```bash
# Environment setup
export TESSERA_URL=http://localhost:8000
export TESSERA_API_KEY=your-api-key

# After dbt test
python scripts/report_to_tessera.py
```

Query audit history and trends via API:
```bash
# Get audit history (paginated)
curl $TESSERA_URL/api/v1/assets/{asset_id}/audit-history

# Get trends and alerts (failure rates, patterns, alerts)
curl $TESSERA_URL/api/v1/assets/{asset_id}/audit-trends?days=30
```

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
