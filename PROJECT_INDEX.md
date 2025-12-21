# Tessera Project Index

> Data contract coordination for warehouses. Producers publish schemas, consumers register dependencies, breaking changes require acknowledgment.

## Quick Reference

| Attribute | Value |
|-----------|-------|
| Python Version | >=3.11 |
| Package Manager | uv |
| Framework | FastAPI + SQLAlchemy |
| Database | PostgreSQL (prod) / SQLite (dev/test) |
| Test Count | 126 |
| License | MIT |

## Project Structure

```
tessera/
├── src/tessera/              # Main application
│   ├── main.py               # FastAPI app entry point
│   ├── config.py             # Pydantic settings from env
│   ├── api/                  # REST endpoints
│   │   ├── api_keys.py       # API key management (admin)
│   │   ├── assets.py         # Asset + contract publishing
│   │   ├── auth.py           # Authentication dependencies
│   │   ├── contracts.py      # Contract lookup
│   │   ├── errors.py         # Error handling + middleware
│   │   ├── pagination.py     # Pagination helpers
│   │   ├── proposals.py      # Breaking change workflow
│   │   ├── registrations.py  # Consumer registration
│   │   ├── schemas.py        # Schema validation
│   │   ├── sync.py           # dbt manifest sync + impact analysis
│   │   └── teams.py          # Team CRUD
│   ├── db/                   # Database layer
│   │   ├── database.py       # Async session management
│   │   └── models.py         # SQLAlchemy ORM models
│   ├── models/               # Pydantic schemas
│   │   ├── acknowledgment.py # Acknowledgment DTOs
│   │   ├── api_key.py        # API key DTOs
│   │   ├── asset.py          # Asset DTOs
│   │   ├── contract.py       # Contract DTOs
│   │   ├── dependency.py     # Dependency DTOs
│   │   ├── enums.py          # Status/type enums
│   │   ├── proposal.py       # Proposal DTOs
│   │   ├── registration.py   # Registration DTOs
│   │   └── team.py           # Team DTOs
│   └── services/             # Business logic
│       ├── audit.py          # Audit event logging
│       ├── auth.py           # API key validation + management
│       ├── schema_diff.py    # JSON Schema diffing + compatibility
│       └── schema_validator.py # Schema validation
├── sdk/                      # Python SDK (tessera-sdk)
│   ├── src/tessera_sdk/      # SDK source
│   │   ├── client.py         # TesseraClient (sync/async)
│   │   └── models.py         # SDK Pydantic models
│   └── pyproject.toml        # SDK package config
├── tests/                    # Test suite (126 tests)
│   ├── conftest.py           # Fixtures + factories
│   ├── test_assets.py        # Asset endpoint tests
│   ├── test_contracts.py     # Contract endpoint tests
│   ├── test_health.py        # Health check tests
│   ├── test_proposals.py     # Proposal endpoint tests
│   ├── test_registrations.py # Registration endpoint tests
│   ├── test_schema_diff.py   # Schema diff unit tests
│   ├── test_schema_validator.py # Validator tests
│   ├── test_sync.py          # Sync endpoint tests
│   └── test_teams.py         # Team endpoint tests
├── examples/                 # Usage examples
│   └── quickstart.py         # 5 core workflows demo
├── alembic/                  # Database migrations
├── docker-compose.yml        # PostgreSQL + API services
└── pyproject.toml            # Project configuration
```

## Core Modules

### Entry Point
- **`src/tessera/main.py`**: FastAPI app initialization, CORS, router mounting

### Configuration
- **`src/tessera/config.py`**: Environment-based settings via pydantic-settings
  - `DATABASE_URL`: Database connection string
  - `API_HOST/API_PORT`: Server binding
  - `CORS_ORIGINS`: Allowed origins
  - `GIT_SYNC_PATH`: Optional path for git-based sync
  - `WEBHOOK_URL/WEBHOOK_SECRET`: Optional webhook integration
  - `AUTH_DISABLED`: Disable auth for development (default: false)
  - `BOOTSTRAP_API_KEY`: Initial admin key for bootstrapping

### Database Models (`src/tessera/db/models.py`)
| Model | Schema | Description |
|-------|--------|-------------|
| TeamDB | core | Team identity and metadata |
| AssetDB | core | Data asset (table/view) |
| ContractDB | core | Versioned schema contract |
| RegistrationDB | core | Consumer dependency registration |
| APIKeyDB | core | API key for authentication |
| AssetDependencyDB | core | Asset-to-asset lineage |
| ProposalDB | workflow | Breaking change proposal |
| AcknowledgmentDB | workflow | Consumer acknowledgment |
| AuditEventDB | audit | Append-only event log |

### Schema Diffing (`src/tessera/services/schema_diff.py`)
Core logic for detecting schema changes:
- `diff_schemas(old, new)` → `SchemaDiffResult`
- `check_compatibility(old, new, mode)` → `(bool, list[BreakingChange])`

**Compatibility Modes:**
| Mode | Breaking When |
|------|---------------|
| backward | Remove field, add required, narrow type, remove enum |
| forward | Add field, remove required, widen type, add enum |
| full | Any change |
| none | Nothing (notify only) |

**Change Types Detected:**
- Property added/removed/renamed
- Type changed/widened/narrowed
- Required added/removed
- Enum values added/removed
- Constraints tightened/relaxed
- Default added/removed/changed
- Nullable added/removed

## API Endpoints

Base path: `/api/v1`

### Teams
| Method | Path | Description |
|--------|------|-------------|
| POST | `/teams` | Create team |
| GET | `/teams` | List teams |
| GET | `/teams/{id}` | Get team |
| PUT | `/teams/{id}` | Update team |

### Assets
| Method | Path | Description |
|--------|------|-------------|
| POST | `/assets` | Create asset |
| GET | `/assets` | List assets |
| GET | `/assets/{id}` | Get asset |
| POST | `/assets/{id}/contracts` | Publish contract |
| POST | `/assets/{id}/impact` | Impact analysis |

### Contracts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/contracts` | List contracts |
| GET | `/contracts/{id}` | Get contract |

### Registrations
| Method | Path | Description |
|--------|------|-------------|
| POST | `/registrations` | Register as consumer |
| GET | `/registrations` | List registrations |
| DELETE | `/registrations/{id}` | Unregister |

### Proposals
| Method | Path | Description |
|--------|------|-------------|
| GET | `/proposals` | List proposals |
| GET | `/proposals/{id}` | Get proposal |
| POST | `/proposals/{id}/acknowledge` | Acknowledge breaking change |

### Sync (dbt integration)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/sync/push` | Push contracts to git (requires GIT_SYNC_PATH) |
| POST | `/sync/pull` | Pull contracts from git (requires GIT_SYNC_PATH) |
| POST | `/sync/dbt` | Sync from dbt manifest |
| POST | `/sync/dbt/impact` | CI/CD impact analysis (API-first) |

### Schemas
| Method | Path | Description |
|--------|------|-------------|
| POST | `/schemas/validate` | Validate JSON Schema |

### API Keys
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api-keys` | Create API key (admin only) |
| GET | `/api-keys` | List API keys |
| GET | `/api-keys/{id}` | Get API key |
| DELETE | `/api-keys/{id}` | Revoke API key (admin only) |

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Basic health check |
| GET | `/health/ready` | Readiness probe (checks DB) |
| GET | `/health/live` | Liveness probe |

## SDK (tessera-sdk)

Python SDK for interacting with Tessera API.

**Installation:**
```bash
pip install tessera-sdk
```

**Usage:**
```python
from tessera_sdk import TesseraClient

client = TesseraClient("http://localhost:8000")

# Create team
team = client.create_team("data-platform")

# Create asset with contract
asset = client.create_asset(
    fqn="analytics.orders",
    owner_team_id=team.id
)

contract = client.publish_contract(
    asset_id=asset.id,
    schema_def={"type": "object", "properties": {...}},
    published_by=team.id
)
```

**Async support:**
```python
async with TesseraClient("http://localhost:8000") as client:
    team = await client.create_team("data-platform")
```

## Development Commands

```bash
# Setup
uv sync --all-extras

# Run server
uv run uvicorn tessera.main:app --reload

# Run tests (SQLite - fast)
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ -v

# Run tests (PostgreSQL)
docker compose up -d db
uv run pytest tests/ -v

# Type checking
uv run mypy src/tessera/

# Linting
uv run ruff check src/tessera/
uv run ruff format src/tessera/

# Coverage
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ --cov=tessera --cov-report=term-missing
```

## Docker

```bash
# Start services (PostgreSQL + API)
docker compose up -d

# View logs
docker compose logs -f api

# Stop
docker compose down
```

## Key Patterns

### Contract Publishing Flow
1. First contract → auto-publish
2. Compatible change → auto-publish, deprecate old
3. Breaking change → create Proposal, wait for acknowledgments
4. Force flag → publish anyway (audit logged)

### Database Transactions
Multi-step mutations use nested transactions (savepoints):
```python
async with session.begin_nested():
    # Step 1: create new contract
    # Step 2: deprecate old contract
    # Rollback both if either fails
```

### Dual Database Support
Models support both PostgreSQL (schemas: core, workflow, audit) and SQLite (no schemas).

## Dependencies

### Runtime
- fastapi
- uvicorn
- sqlalchemy[asyncio]
- asyncpg (PostgreSQL)
- aiosqlite (SQLite)
- pydantic
- pydantic-settings

### Development
- pytest + pytest-asyncio
- ruff
- mypy
- pre-commit

## Links

- Repository: https://github.com/ashita-ai/tessera
- Issues: https://github.com/ashita-ai/tessera/issues
