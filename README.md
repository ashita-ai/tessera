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

In ancient Rome, a *tessera hospitalis* was a tablet broken in half between two parties as a contract of mutual obligation. Each side kept one piece; fitting them together proved the relationship — even generations later.

Tessera does the same thing for services. Producers and consumers each hold their side of a contract. When someone wants to change the shape, Tessera makes sure the pieces still fit.

## What Tessera does

Other tools detect breaking changes. Tessera **coordinates the workflow around them**.

When a producer publishes a breaking change, Tessera creates a proposal, notifies every registered consumer, and blocks publication until each one acknowledges. The change ships only when everyone downstream is ready.

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

Services break each other without warning. A team renames a field in their OpenAPI spec, removes a gRPC method, or changes a GraphQL return type — and the team that depends on it finds out when their oncall pages at 2 AM.

Tessera makes dependencies explicit and breaking changes coordinated. It works the same way regardless of source format: OpenAPI specs, GraphQL schemas, gRPC/protobuf definitions, dbt models, or raw JSON Schema. Every sync adapter normalizes to JSON Schema internally, feeding the same diffing, compatibility, and proposal engine.

## Why not just use...

| Tool | What it does well | Gap Tessera fills |
|------|------------------|-------------------|
| **Schema Registry** (Confluent) | Schema versioning + compatibility for Kafka | No proposal workflow, no consumer notification, no acknowledgment tracking |
| **Buf** | Protobuf linting and breaking change detection in CI | Detection only — no consumer registry, no coordination |
| **Optic** | OpenAPI diff and changelog in CI/CD | Single-spec CLI tool — no cross-service dependency graph |
| **GraphQL Inspector** | Schema diff and validation for GraphQL | Single-schema tool — no multi-service coordination |
| **Backstage** | Service catalog with metadata and ownership | Catalog, not contract enforcement — no schema diffing |
| **datacontract-cli** | Lint, validate, test, export contracts in CI/CD | CLI tool, no server — no consumer registry |

Tessera's contribution is the **proposal-acknowledgment workflow**: a self-hosted coordination server where breaking changes are blocked until affected consumers explicitly sign off, across all API types.

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
4. Each consumer **acknowledges** — approved, migrating, or blocked
5. Once all consumers acknowledge, the contract publishes
6. **Non-breaking changes** skip the proposal and auto-publish

Force-publish is available for emergencies (admin-only, audit-logged).

## Key features

- **Schema-agnostic contract engine** — OpenAPI, GraphQL, gRPC, and dbt sync adapters all normalize to JSON Schema. Same diffing, compatibility checking, and proposal workflow regardless of source format
- **Proposal workflow** — Breaking changes create proposals; all registered consumers must acknowledge before publication
- **Schema diffing** — Detects property changes, type narrowing/widening, constraint tightening, enum changes, required field changes, nullable changes, and more
- **Compatibility modes** — Backward, forward, full, or none (matching Kafka Schema Registry semantics)
- **Service dependency graph** — `GET /api/v1/graph/services` returns a service-to-service dependency graph aggregated from asset-level edges, with team filtering, neighborhood subgraphs (`/services/{id}/neighborhood`), and downstream impact traversal (`/graph/impact/{asset_id}`)
- **Impact analysis** — Recursive lineage traversal shows all downstream assets and teams affected by a change
- **Semantic versioning** — Auto, suggest, or enforce modes with pre-release support
- **Data quality guarantees** — Not-null, unique, accepted_values, freshness, volume checks tracked alongside schemas
- **Write-Audit-Publish** — Optionally block publishing until data quality audits pass
- **Semantic metadata** — Tag assets with labels (e.g., `pii`, `financial`) and annotate individual fields with descriptions and tags via JSONPath keys
- **Service management** — Register services as deployable units within repositories, track which assets belong to each service, filter by repo/team/OTel name
- **Team-based ownership** — Assets belong to teams (survives personnel changes), with optional user-level stewardship
- **AI agent integration** — Agents register as consumers, check contracts before modifying schemas, and participate in the proposal workflow
- **Webhooks** — Signed delivery (HMAC-SHA256) with SSRF protection, retry with backoff, delivery tracking
- **API keys** — Scoped (read, write, admin), revocable, expiring. Supports agent identity with separate rate limit tiers
- **Passive dependency discovery** — Mines preflight audit signals to infer which teams consume which assets, with confidence scoring and a confirm/reject workflow to promote inferences to registrations
- **Audit log** — Append-only history of every publish, proposal, acknowledgment, force-approve, and consumption event
- **Web UI** — Browse assets, view contract history, manage proposals and teams

## Configuration

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
- [Sync Adapters](https://ashita-ai.github.io/tessera/api/sync/) (OpenAPI, GraphQL, gRPC, dbt)
- [Python SDK](https://ashita-ai.github.io/tessera/guides/python-sdk/) | [PyPI](https://pypi.org/project/tessera-sdk/)
- [AI Agent Integration](https://ashita-ai.github.io/tessera/guides/ai-agent-integration/)
- [API Reference](https://ashita-ai.github.io/tessera/api/overview/)

## License

MIT
