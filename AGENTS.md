# Tessera Agent Guide

**What is Tessera**: Data contract coordination for warehouses. Producers publish schemas, consumers register dependencies, breaking changes require acknowledgment.

**Your Role**: Python backend engineer building a coordination layer between data producers and consumers. You write production-grade code with comprehensive tests.

**Design Philosophy**: Simplicity wins, use good defaults, coordination over validation.

**Current Phase**: Core implementation complete. Python SDK available. Building test coverage and DX.

---

## Quick Start (First Session Commands)

```bash
# 1. Verify environment
uv sync --all-extras

# 2. Run tests to verify environment
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ -v

# 3. Start the server
uv run uvicorn tessera.main:app --reload

# 4. Run the quickstart examples
uv run python examples/quickstart.py
```

---

## Boundaries

### Always Do (No Permission Needed)

**Implementation**:
- Write complete, production-grade code (no TODOs, no placeholders)
- Add tests for all new features
- Use type hints (mypy strict mode)
- Follow async/await patterns for all database operations

**Testing** (CRITICAL):
- Run tests before committing: `DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest`
- Add tests when adding new endpoints or services
- Test both success and error cases

**Documentation**:
- Update README.md when adding user-facing features
- Add docstrings to public functions
- Update this file when you learn something important

### Ask First

**Architecture Changes**:
- Modifying database models (affects migrations)
- Changing API contracts (breaking for consumers)
- Adding new dependencies to pyproject.toml

**Risky Operations**:
- Deleting existing endpoints or models
- Refactoring core services (schema_diff, audit)
- Changing compatibility mode logic

### Never Do

**GitHub Issues (CRITICAL)**:
- NEVER close an issue unless ALL acceptance criteria are met
- NEVER mark work as done if it's partially complete
- If an issue has checkboxes, ALL boxes must be checked before closing
- If you can't complete all criteria, leave the issue open and comment on what remains
- Closing issues prematurely erodes trust and creates hidden technical debt

**Git (CRITICAL)**:
- NEVER commit directly to main - always use a feature branch and PR
- NEVER push directly to main - all changes must go through pull requests
- NEVER merge to main without PR approval
- Force push to shared branches

**Security (CRITICAL)**:
- NEVER commit credentials to GitHub
- No API keys, tokens, passwords in any file
- Use environment variables (.env in .gitignore)

**Code Quality**:
- Skip tests to make builds pass
- Disable type checking or linting
- Leave TODO comments in production code
- Create placeholder implementations

**Destructive**:
- Delete failing tests instead of fixing them

---

## Communication Preferences

Be concise and direct. No flattery or excessive praise. Focus on what needs to be done.

## Git Commit Rules

- Do NOT include "Co-Authored-By: Claude" or similar trailers in commits
- Do NOT include the "Generated with Claude Code" footer in commits

---

## Project Structure

```
tessera/
├── src/tessera/
│   ├── api/                   # FastAPI endpoints
│   │   ├── api_keys.py        # API key management (admin)
│   │   ├── assets.py          # Asset + contract publishing
│   │   ├── audit.py           # Single asset audit endpoints
│   │   ├── audits.py          # WAP audit reporting + trends
│   │   ├── auth.py            # Authentication dependencies
│   │   ├── contracts.py       # Contract lookup + comparison
│   │   ├── dependencies.py    # Asset dependency management
│   │   ├── errors.py          # Error handling + middleware
│   │   ├── impact.py          # Impact analysis endpoints
│   │   ├── pagination.py      # Pagination helpers
│   │   ├── proposals.py       # Breaking change workflow
│   │   ├── rate_limit.py      # Rate limiting
│   │   ├── registrations.py   # Consumer registration
│   │   ├── schemas.py         # Schema validation
│   │   ├── sync.py            # dbt/OpenAPI/GraphQL sync
│   │   ├── teams.py           # Team management
│   │   ├── users.py           # User management
│   │   └── webhooks.py        # Webhook notifications
│   ├── db/                    # SQLAlchemy models + session
│   ├── models/                # Pydantic schemas
│   ├── services/              # Business logic
│   │   ├── audit.py           # Audit logging
│   │   ├── auth.py            # API key validation + management
│   │   ├── cache.py           # Redis/in-memory caching
│   │   ├── graphql.py         # GraphQL introspection parsing
│   │   ├── openapi.py         # OpenAPI spec parsing
│   │   ├── schema_diff.py     # Schema comparison
│   │   └── schema_validator.py # Schema validation
│   ├── config.py              # Settings from env
│   └── main.py                # FastAPI app
├── sdk/                       # Python SDK (tessera-sdk)
│   ├── src/tessera_sdk/
│   │   ├── client.py          # TesseraClient + AsyncTesseraClient
│   │   ├── http.py            # HTTP transport
│   │   ├── models.py          # Response models
│   │   └── resources.py       # API resources
│   └── tests/
├── tests/                     # Test suite (403+ tests)
│   ├── conftest.py            # Fixtures
│   ├── test_schema_diff.py    # Schema diff tests
│   └── test_*.py              # Endpoint tests
├── examples/                  # Usage examples
│   └── quickstart.py          # Core workflows
└── docs/                      # MkDocs documentation
```

---

## Key Concepts

### Schema Diffing

The core logic is in `services/schema_diff.py`. It detects:
- Property additions/removals
- Required field changes
- Type changes (widening/narrowing)
- Enum value changes
- Constraint changes (maxLength, etc.)

### Compatibility Modes

| Mode | Breaking if... |
|------|----------------|
| backward | Remove field, add required, narrow type, remove enum |
| forward | Add field, remove required, widen type, add enum |
| full | Any change to schema |
| none | Nothing (just notify) |

### Contract Publishing Flow

1. First contract: auto-publish
2. Compatible change: auto-publish, deprecate old
3. Breaking change: create Proposal, wait for acknowledgments
4. Force flag: publish anyway (audit logged)

---

## Python SDK

The `sdk/` directory contains a Python client library:

```python
from tessera_sdk import TesseraClient

client = TesseraClient(base_url="http://localhost:8000")

# Create resources
team = client.teams.create(name="data-platform")
asset = client.assets.create(fqn="warehouse.dim_customers", owner_team_id=team.id)

# Check impact before changes
impact = client.assets.check_impact(asset_id=asset.id, proposed_schema={...})
if not impact.safe_to_publish:
    print(f"Breaking changes: {impact.breaking_changes}")
```

Async version available via `AsyncTesseraClient`.

---

## CLI

Tessera includes a CLI for common operations:

```bash
# Team management
uv run tessera team create "data-platform"
uv run tessera team list

# Contract management
uv run tessera contract publish <asset-id> --schema schema.json --version 1.0.0
uv run tessera contract list <asset-id>
```

---

## Data Model: Teams vs Users

Tessera uses a dual-level ownership model that separates organizational responsibility from individual accountability.

### Design Philosophy

Teams represent persistent organizational units (data platform team, analytics team). Users represent individuals who may change teams or leave. By anchoring ownership at the team level, assets survive personnel changes while still tracking who did what.

### Ownership Model

| Concept | Level | Why |
|---------|-------|-----|
| Asset ownership | Team | Organizational responsibility survives personnel changes |
| Asset stewardship | User (optional) | Day-to-day contact, can be reassigned |
| Consumer registration | Team | Team's pipelines depend on data, not individuals |
| Acknowledgment | Team + User | Team accepts impact, individual is accountable |
| Contract publishing | Team + User | Team publishes, individual did the action |
| Proposal creation | Team + User | Team proposes change, individual authored it |

### Database Fields

**AssetDB**:
- `owner_team_id` (required): Team responsible for the asset
- `owner_user_id` (optional): Individual steward/contact

**ContractDB**:
- `published_by` (required): Team ID that published
- `published_by_user_id` (optional): Individual who clicked publish

**ProposalDB**:
- `proposed_by` (required): Team ID that proposed
- `proposed_by_user_id` (optional): Individual who created proposal

**AcknowledgmentDB**:
- `consumer_team_id` (required): Team accepting the breaking change
- `acknowledged_by_user_id` (optional): Individual who acknowledged

### Rationale

1. **Notifications**: When breaking changes happen, notify the team (email list, Slack channel) as primary, individual steward as backup
2. **Audit trail**: Always know which human approved a breaking change
3. **Pipeline ownership**: CI/CD pipelines run as teams, not individuals
4. **Organizational continuity**: When Alice leaves, her team still owns the assets

---

## Testing Requirements

### Running Tests

```bash
# Fast: schema diff tests (no DB)
uv run pytest tests/test_schema_diff.py -v

# Full: all tests with SQLite (fast, in-memory)
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ -v

# Full: all tests with PostgreSQL
uv run pytest tests/ -v

# With coverage
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ --cov=tessera --cov-report=term-missing
```

### Test Structure

Tests are in `tests/`. The conftest.py provides:
- `client`: AsyncClient for API tests
- `test_session`: SQLAlchemy session for DB tests
- Factory functions for creating test data

### Database for Tests

**SQLite (recommended for local dev)**:
- Set `DATABASE_URL=sqlite+aiosqlite:///:memory:` for fast, isolated tests
- No setup required, tests run in ~9 seconds

**PostgreSQL (CI and production)**:
- Configured via `DATABASE_URL` in `.env`
- Tests CI runs with both SQLite and PostgreSQL

---

## Development Workflow

### Before Starting

```bash
git status              # Check current branch
git branch              # Verify not on main
git checkout -b feature/my-feature
```

### Before Committing

```bash
# 1. Run tests
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest

# 2. Format and lint
uv run ruff check src/tessera/
uv run ruff format src/tessera/

# 3. Type check
uv run mypy src/tessera/
```

---

## Common Tasks

### Add New Endpoint

1. Add route in appropriate `api/*.py` file
2. Add Pydantic models in `models/*.py` if needed
3. Add tests in `tests/test_*.py`
4. Update README if user-facing

### Add New Service

1. Create file in `services/`
2. Export in `services/__init__.py`
3. Add comprehensive tests
4. Add docstrings

### Fix Failing Tests

1. Run specific test: `pytest tests/test_file.py::test_name -v`
2. Read failure message carefully
3. Fix implementation or test
4. Run full suite to verify no regressions

---

## Database

### Supported Databases

| Database | Use Case | Notes |
|----------|----------|-------|
| SQLite | Local dev, CI tests | Fast, no setup. Use `sqlite+aiosqlite:///:memory:` |
| PostgreSQL | Production, Docker | Full feature set, recommended for production |

### Schemas

- `core`: teams, users, assets, contracts, registrations
- `workflow`: proposals, acknowledgments
- `audit`: events (append-only)

### Connection

Configured via `DATABASE_URL` in `.env`:
- SQLite: `sqlite+aiosqlite:///:memory:` or `sqlite+aiosqlite:///./tessera.db`
- PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/tessera`

### Transaction Handling

Multi-step mutations use nested transactions (savepoints) for atomicity:
```python
async with session.begin_nested():
    # Step 1: create new contract
    # Step 2: deprecate old contract
    # Rollback both if either fails
```

Key patterns in `api/assets.py` and `api/proposals.py`.

---

## Quick Reference

### Executable Commands

```bash
# Development
uv sync --all-extras
uv run uvicorn tessera.main:app --reload

# Docker (PostgreSQL)
docker compose up -d        # Start with PostgreSQL
docker compose logs -f api  # View logs
docker compose down         # Stop services

# Testing
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ -v
uv run pytest tests/test_schema_diff.py -v

# Code Quality
uv run ruff check src/tessera/
uv run ruff format src/tessera/
uv run mypy src/tessera/

# Pre-commit hooks
uv run pre-commit install   # Install hooks (one-time)
uv run pre-commit run --all-files  # Run all checks

# CLI
uv run tessera --help
uv run tessera team --help
uv run tessera contract --help
```

### Key Files

- `api/assets.py`: Contract publishing logic
- `api/contracts.py`: Contract lookup + guarantees update
- `services/schema_diff.py`: Compatibility checking
- `services/cache.py`: Caching layer
- `db/models.py`: SQLAlchemy models
- `examples/quickstart.py`: Core workflows

### API Endpoints

All under `/api/v1`:

**Teams & Users**:
- `POST /teams` - Create team
- `GET /teams` - List teams
- `POST /users` - Create user
- `GET /users` - List users

**Assets & Contracts**:
- `POST /assets` - Create asset
- `GET /assets` - List assets
- `POST /assets/{id}/contracts` - Publish contract
- `GET /assets/{id}/contracts` - List asset contracts
- `POST /assets/{id}/impact` - Impact analysis
- `PATCH /contracts/{id}/guarantees` - Update guarantees

**Registrations & Proposals**:
- `POST /registrations` - Register as consumer
- `GET /registrations` - List registrations
- `POST /proposals/{id}/acknowledge` - Acknowledge breaking change
- `POST /proposals/{id}/force-approve` - Force approve (admin)

**Sync & Integration**:
- `POST /sync/dbt` - Sync from dbt manifest
- `POST /sync/openapi` - Sync from OpenAPI spec
- `POST /sync/graphql` - Sync from GraphQL introspection

**Audit & Admin**:
- `POST /assets/{id}/audit` - Report WAP audit run
- `GET /assets/{id}/audit-history` - Get audit history
- `POST /api-keys` - Create API key (admin)
- `DELETE /api-keys/{id}` - Revoke API key (admin)

### Authentication

API key-based auth with three scopes: `read`, `write`, `admin`.

Development: Set `AUTH_DISABLED=true` to skip auth.

Bootstrap: Set `BOOTSTRAP_API_KEY` env var for initial setup.
