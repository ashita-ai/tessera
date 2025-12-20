# Tessera Agent Guide

**What is Tessera**: Data contract coordination for warehouses. Producers publish schemas, consumers register dependencies, breaking changes require acknowledgment.

**Your Role**: Python backend engineer building a coordination layer between data producers and consumers. You write production-grade code with comprehensive tests.

**Design Philosophy**: Simplicity wins, use good defaults, coordination over validation.

**Current Phase**: Core implementation complete, building test coverage and DX.

---

## Quick Start (First Session Commands)

```bash
# 1. Verify environment
uv sync --all-extras

# 2. Run tests to verify environment
uv run pytest tests/test_schema_diff.py -v

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
- Run tests before committing: `uv run pytest`
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
- Work directly on main/master branch
- Force push to shared branches
- Delete failing tests instead of fixing them

---

## Communication Preferences

Be concise and direct. No flattery or excessive praise. Focus on what needs to be done.

---

## Project Structure

```
tessera/
├── src/tessera/
│   ├── api/               # FastAPI endpoints
│   │   ├── assets.py      # Asset + contract publishing
│   │   ├── teams.py       # Team management
│   │   ├── contracts.py   # Contract lookup
│   │   ├── registrations.py # Consumer registration
│   │   ├── proposals.py   # Breaking change workflow
│   │   └── sync.py        # dbt manifest sync
│   ├── db/                # SQLAlchemy models + session
│   ├── models/            # Pydantic schemas
│   ├── services/          # Business logic
│   │   ├── schema_diff.py # Schema comparison
│   │   └── audit.py       # Audit logging
│   ├── config.py          # Settings from env
│   └── main.py            # FastAPI app
├── tests/                 # Test suite
│   ├── conftest.py        # Fixtures
│   ├── test_schema_diff.py # Schema diff tests
│   └── test_api.py        # API integration tests
├── examples/              # Usage examples
│   └── quickstart.py      # 5 core workflows
└── assets/                # Images, logos
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

## Testing Requirements

### Running Tests

```bash
# Fast: schema diff tests (no DB)
uv run pytest tests/test_schema_diff.py -v

# Full: all tests (requires PostgreSQL)
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=tessera --cov-report=term-missing
```

### Test Structure

Tests are in `tests/`. The conftest.py provides:
- `client`: AsyncClient for API tests
- `test_session`: SQLAlchemy session for DB tests
- Factory functions for creating test data

### Database for Tests

Tests use the same PostgreSQL database as the app (configured via DATABASE_URL in .env). Schemas isolate test data.

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
uv run pytest

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
3. Add tests in `tests/test_api.py`
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

### Schemas

- `core`: teams, assets, contracts, registrations
- `workflow`: proposals, acknowledgments
- `audit`: events (append-only)

### Connection

Configured via `DATABASE_URL` in `.env`. Currently using Supabase PostgreSQL.

---

## Quick Reference

### Executable Commands

```bash
# Development
uv sync --all-extras
uv run uvicorn tessera.main:app --reload

# Testing
uv run pytest tests/ -v
uv run pytest tests/test_schema_diff.py -v

# Code Quality
uv run ruff check src/tessera/
uv run ruff format src/tessera/
uv run mypy src/tessera/
```

### Key Files

- `api/assets.py`: Contract publishing logic
- `services/schema_diff.py`: Compatibility checking
- `db/models.py`: SQLAlchemy models
- `examples/quickstart.py`: Core workflows

### API Endpoints

All under `/api/v1`:
- `POST /teams` - Create team
- `POST /assets` - Create asset
- `POST /assets/{id}/contracts` - Publish contract
- `POST /assets/{id}/impact` - Impact analysis
- `POST /registrations` - Register as consumer
- `POST /proposals/{id}/acknowledge` - Acknowledge breaking change
- `POST /sync/dbt` - Sync from dbt manifest
