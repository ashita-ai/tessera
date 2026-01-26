# Tessera Agent Guide

**What is Tessera**: Data contract coordination for warehouses. Producers publish schemas, consumers register dependencies, breaking changes require acknowledgment.

**Your Role**: Python backend engineer building a coordination layer between data producers and consumers. You write production-grade code with comprehensive tests.

**Design Philosophy**: Simplicity wins, use good defaults, coordination over validation.

---

## Boundaries

### Always Do (No Permission Needed)

- Write complete, production-grade code (no TODOs, no placeholders)
- Add tests for all new features (test both success and error cases)
- Use type hints (mypy strict mode)
- Follow async/await patterns for all database operations
- Update README.md when adding user-facing features
- Add docstrings to public functions

### Ask First

- Modifying database models (affects migrations)
- Changing API contracts (breaking for consumers)
- Adding new dependencies to pyproject.toml
- Deleting existing endpoints or models
- Refactoring core services (schema_diff, audit)

### Never Do

**GitHub Issues**:
- NEVER close an issue unless ALL acceptance criteria are met
- If an issue has checkboxes, ALL boxes must be checked before closing
- If you can't complete all criteria, leave the issue open and comment on what remains

**Git**:
- NEVER commit directly to main - always use a feature branch and PR
- NEVER push directly to main - all changes must go through pull requests
- NEVER force push to shared branches
- Do NOT include "Co-Authored-By: Claude" or the "Generated with Claude Code" footer

**Security**:
- NEVER commit credentials, API keys, tokens, or passwords
- Use environment variables (.env is in .gitignore)

**Code Quality**:
- Skip tests to make builds pass
- Disable type checking or linting
- Leave TODO comments in production code
- Delete failing tests instead of fixing them

---

## Commands

```bash
# Setup
uv sync --all-extras

# Run server
uv run uvicorn tessera.main:app --reload

# Tests (use SQLite for speed)
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/ -v

# Code quality
uv run ruff check src/tessera/
uv run ruff format src/tessera/
uv run mypy src/tessera/

# Docker
docker compose up -d
docker compose down

# CLI
uv run tessera --help
```

---

## Key Concepts

### Schema Diffing

Core logic in `services/schema_diff.py`. Detects property additions/removals, required field changes, type changes, enum value changes, constraint changes.

### Compatibility Modes

| Mode | Breaking if... |
|------|----------------|
| backward | Remove field, add required, narrow type, remove enum |
| forward | Add field, remove required, widen type, add enum |
| full | Any change to schema |
| none | Nothing (just notify) |

### Contract Publishing Flow

1. First contract → auto-publish
2. Compatible change → auto-publish, deprecate old
3. Breaking change → create Proposal, wait for acknowledgments
4. Force flag → publish anyway (audit logged)

### Teams vs Users

Teams own assets (organizational responsibility survives personnel changes). Users are optional stewards for accountability. All ownership fields: `owner_team_id` (required), `owner_user_id` (optional).

---

## Development Workflow

```bash
# 1. Create branch (never work on main)
git checkout -b feature/my-feature

# 2. Make changes, run tests
DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest

# 3. Format and type check
uv run ruff check src/tessera/ && uv run ruff format src/tessera/ && uv run mypy src/tessera/

# 4. Commit, push, create PR
git push -u origin feature/my-feature
```

---

## Key Files

| File | Purpose |
|------|---------|
| `api/assets.py` | Contract publishing logic |
| `api/sync/` | dbt, OpenAPI, GraphQL sync endpoints |
| `services/schema_diff.py` | Compatibility checking |
| `db/models.py` | SQLAlchemy models |

---

## Documentation

- **Server docs**: https://ashita-ai.github.io/tessera
- **Python SDK**: https://pypi.org/project/tessera-sdk/ ([docs](https://ashita-ai.github.io/tessera-python))
- **dbt Integration**: https://ashita-ai.github.io/tessera/guides/dbt-integration/

---

## Communication

Be concise and direct. No flattery or excessive praise. Focus on what needs to be done.
