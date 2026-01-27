<p align="center">
  <img src="https://raw.githubusercontent.com/ashita-ai/tessera/main/assets/logo.png" alt="Tessera" width="300">
</p>

<h3 align="center">Coordinate breaking schema changes across data teams</h3>

<p align="center">
  <a href="https://ashita-ai.github.io/tessera">Docs</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="https://pypi.org/project/tessera-sdk/">Python SDK</a> |
  <a href="https://github.com/ashita-ai/tessera/issues">Issues</a>
</p>

---

## What Tessera does

Other tools detect breaking changes. Tessera **coordinates the human workflow around them**.

When a producer wants to make a breaking schema change, Tessera creates a proposal, notifies every affected consumer, and blocks publication until they acknowledge. The change ships only when everyone downstream is ready.

```
Producer: "I want to drop user_email"
    ↓
Tessera: "3 teams depend on this. Creating proposal, notifying them."
    ↓
Consumers: "We've migrated. Acknowledged."
    ↓
Tessera: "All consumers ready. Publishing v2.0.0."
```

Non-breaking changes skip this entirely and auto-publish with a version bump.

## Why not just use...

| Tool | What it does well | Gap Tessera fills |
|------|------------------|-------------------|
| **Schema Registry** (Confluent) | Schema versioning + compatibility for Kafka streams | Block-or-allow only. No proposal workflow, no consumer notification, no acknowledgment tracking |
| **datacontract-cli** | Lint, validate, test, export contracts in CI/CD | CLI tool, no server. No consumer registry, no coordination |
| **Open Data Contract Standard** | Standardized YAML format for defining contracts | A spec, not a runtime. No enforcement or coordination |
| **Soda Data Contracts** | Pipeline quality gates and data quality checks | Quality validation, not schema change coordination |
| **Data Mesh Manager** | Data product marketplace with contract support | Commercial SaaS. Broader scope, less focused on change coordination |

Tessera's unique contribution is the **proposal-acknowledgment workflow**: a self-hosted coordination server where breaking changes are blocked until affected consumers explicitly sign off. Nothing else in the open-source ecosystem does this.

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

## Core workflow

1. **Producers** publish contracts (schema + data quality guarantees) for their assets
2. **Consumers** register dependencies on the contracts they read
3. When a producer publishes a **breaking change**, Tessera creates a proposal and notifies all registered consumers
4. Each consumer **acknowledges** (ready, needs-time, or blocks the change)
5. Once all consumers acknowledge, the contract publishes. If anyone blocks, the proposal is rejected
6. **Non-breaking changes** skip the proposal and auto-publish

Force-approve is available for emergencies, but it's audit-logged.

## Key features

- **Schema diffing** - Detects property changes, type narrowing/widening, constraint tightening, enum changes, required field changes, nullable changes, and more
- **Compatibility modes** - Backward, forward, full, or none (matching Kafka semantics)
- **Multi-format schemas** - JSON Schema, Avro, OpenAPI, GraphQL (normalized to JSON Schema internally)
- **dbt integration** - Import models, tests, and lineage from dbt manifests
- **Impact analysis** - Recursive lineage traversal shows all downstream assets and teams affected by a change
- **Semantic versioning** - Auto, suggest, or enforce modes with pre-release support
- **Data quality guarantees** - Not-null, unique, accepted_values, freshness, volume checks tracked alongside schemas
- **Write-Audit-Publish** - Optionally block publishing if data quality audits are failing
- **Team-based ownership** - Assets belong to teams (survives personnel changes), with optional user-level stewardship
- **Webhooks** - Signed delivery with SSRF protection, retry with backoff, delivery tracking
- **API keys** - Scoped (read, write, admin), revocable, expiring
- **Audit log** - Append-only history of every contract publish, proposal, acknowledgment, and force-approve
- **Web UI** - Browse assets, view contract history, manage teams

## Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://tessera:tessera@localhost:5432/tessera` |
| `REDIS_URL` | Redis for caching (optional) | None (caching disabled) |
| `WEBHOOK_URL` | Destination for webhook events | None |
| `WEBHOOK_SECRET` | HMAC-SHA256 signing secret | None |
| `WEBHOOK_ALLOWED_DOMAINS` | Comma-separated domain allowlist | None (all allowed) |
| `AUTH_DISABLED` | Disable auth for development | `false` |
| `ENVIRONMENT` | `development` or `production` | `development` |

See [configuration docs](https://ashita-ai.github.io/tessera/getting-started/quickstart/) for the full list.

## Documentation

- [Quickstart Guide](https://ashita-ai.github.io/tessera/getting-started/quickstart/)
- [Python SDK](https://ashita-ai.github.io/tessera/guides/python-sdk/) | [PyPI](https://pypi.org/project/tessera-sdk/)
- [dbt Integration](https://ashita-ai.github.io/tessera/guides/dbt-integration/)
- [API Reference](https://ashita-ai.github.io/tessera/api/overview/)

## License

MIT
