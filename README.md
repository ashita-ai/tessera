<p align="center">
  <img src="https://raw.githubusercontent.com/ashita-ai/tessera/main/assets/logo.png" alt="Tessera" width="300">
</p>

<h3 align="center">Data contract coordination for warehouses</h3>

<p align="center">
  <a href="https://ashita-ai.github.io/tessera">Docs</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="https://github.com/ashita-ai/tessera/issues">Issues</a>
</p>

---

**Tessera coordinates breaking changes between data producers and consumers.**

When a producer wants to drop a column, Tessera notifies affected consumers and blocks the change until they acknowledge. No more 3am pages from broken pipelines.

```
Producer: "I want to drop user_email"
    ↓
Tessera: "3 teams depend on this. Notifying them."
    ↓
Consumers: "We've migrated. Approved."
    ↓
Producer: Ships v2.0.0 safely
```

## Quick Start

```bash
# Docker (recommended)
docker compose up -d
open http://localhost:8000

# Or from source
uv sync --all-extras
docker compose up -d db  # PostgreSQL
uv run uvicorn tessera.main:app --reload
```

## Key Features

- **Schema contracts** - JSON Schema definitions with semantic versioning
- **Breaking change detection** - Auto-detect incompatible changes
- **Consumer registration** - Track who depends on what
- **Proposal workflow** - Coordinate changes across teams
- **dbt integration** - Sync contracts from your dbt manifest
- **Web UI** - Visual interface for managing contracts

## How It Works

1. **Producers** publish contracts (schema + guarantees) for their data assets
2. **Consumers** register dependencies on contracts they use
3. **Breaking changes** create proposals requiring consumer acknowledgment
4. **Non-breaking changes** auto-publish with version bumps

## Documentation

Full documentation at [ashita-ai.github.io/tessera](https://ashita-ai.github.io/tessera):

- [Quickstart Guide](https://ashita-ai.github.io/tessera/getting-started/quickstart/)
- [dbt Integration](https://ashita-ai.github.io/tessera/guides/dbt-integration/)
- [API Reference](https://ashita-ai.github.io/tessera/api/overview/)

## License

MIT
