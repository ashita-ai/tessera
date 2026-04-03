<p align="center">
  <img src="https://raw.githubusercontent.com/ashita-ai/tessera/main/assets/logo.png" alt="Tessera" width="300">
</p>

<h3 align="center">Service contract coordination — stop breaking each other's APIs</h3>

<p align="center">
  <a href="https://ashita-ai.github.io/tessera">Docs</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="https://pypi.org/project/tessera-sdk/">Python SDK</a> |
  <a href="https://github.com/ashita-ai/tessera/issues">Issues</a>
</p>

---

## What Tessera does

Other tools detect breaking changes. Tessera **coordinates the workflow around them**.

When a producer wants to make a breaking API change, Tessera creates a proposal, notifies every affected consumer, and blocks publication until they acknowledge. The change ships only when everyone downstream is ready.

```
Producer: "I want to remove the email field from GET /users/{id}"
    ↓
Tessera: "3 services depend on this. Creating proposal, notifying them."
    ↓
Consumers: "We've migrated. Acknowledged."
    ↓
Tessera: "All consumers ready. Publishing v2.0.0."
```

Non-breaking changes skip this entirely and auto-publish with a version bump.

### The problem

Services break each other's APIs without knowing. A team renames a field in their OpenAPI spec, removes a gRPC method, or changes a GraphQL return type — and the team that depends on it only finds out when their oncall pages at 2 AM. Dependencies between services are invisible unless someone manually documents them.

Tessera makes these dependencies explicit and breaking changes coordinated. It works the same way regardless of source: OpenAPI specs, GraphQL schemas, gRPC/protobuf definitions, dbt models, or raw JSON Schema. Everything normalizes to JSON Schema internally for diffing and compatibility checking.

## Why not just use...

| Tool | What it does well | Gap Tessera fills |
|------|------------------|-------------------|
| **Schema Registry** (Confluent) | Schema versioning + compatibility for Kafka streams | Block-or-allow only. No proposal workflow, no consumer notification, no acknowledgment tracking |
| **Buf** | Protobuf linting and breaking change detection in CI | Detection only. No consumer registry, no coordination workflow |
| **Optic** | OpenAPI diff and changelog in CI/CD | CLI tool for individual specs. No cross-service dependency graph or proposal workflow |
| **GraphQL Inspector** | Schema diff and validation for GraphQL | Single-schema tool. No consumer registry, no multi-service coordination |
| **Backstage** | Service catalog with metadata and ownership | Catalog, not a contract enforcement layer. No schema diffing or change coordination |
| **datacontract-cli** | Lint, validate, test, export contracts in CI/CD | CLI tool, no server. No consumer registry, no coordination |

Tessera's unique contribution is the **proposal-acknowledgment workflow**: a self-hosted coordination server where breaking changes are blocked until affected consumers explicitly sign off. It works across API types (OpenAPI, GraphQL, gRPC, dbt) through a schema-agnostic contract engine.

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
- **Proposal workflow** - Breaking changes create proposals; all registered consumers must acknowledge before publication
- **Sync adapters** - OpenAPI, GraphQL, gRPC, and dbt sync adapters import schemas into a unified contract engine. All normalize to JSON Schema internally
- **Impact analysis** - Recursive lineage traversal shows all downstream assets and teams affected by a change
- **AI agent integration** - Agents register as consumers, check contracts before modifying schemas, and participate in the proposal workflow
- **Semantic versioning** - Auto, suggest, or enforce modes with pre-release support
- **Data quality guarantees** - Not-null, unique, accepted_values, freshness, volume checks tracked alongside schemas
- **Write-Audit-Publish** - Optionally block publishing if data quality audits are failing
- **Semantic metadata** - Tag assets with free-form labels (e.g., `pii`, `financial`) and annotate individual contract fields with descriptions and tags using JSONPath keys. Metadata carries forward automatically across contract versions for unchanged fields
- **Team-based ownership** - Assets belong to teams (survives personnel changes), with optional user-level stewardship
- **Webhooks** - Signed delivery with SSRF protection, retry with backoff, delivery tracking
- **API keys** - Scoped (read, write, admin), revocable, expiring. Supports agent identity (`agent_name`, `agent_framework`) with separate rate limit tiers for machine clients
- **Preflight checks** - Consumption-time endpoint returns contract metadata, freshness SLAs, and guarantees; every call is audit-logged for utilization tracking
- **Audit log** - Append-only history of every contract publish, proposal, acknowledgment, force-approve, and consumption event. Tracks whether each action was performed by a human or agent (`actor_type`)
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
- [AI Agent Integration](https://ashita-ai.github.io/tessera/guides/ai-agent-integration/)
- [Sync Adapters](https://ashita-ai.github.io/tessera/api/sync/) (OpenAPI, GraphQL, gRPC, dbt)
- [API Reference](https://ashita-ai.github.io/tessera/api/overview/)

## License

MIT
