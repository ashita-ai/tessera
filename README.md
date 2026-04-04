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
- **Git-based repo sync** — Register repositories and Tessera automatically clones them, discovers spec files (OpenAPI, gRPC, GraphQL), creates services, and publishes contracts. A background worker polls for changes on a configurable interval
- **Audit log** — Append-only history of every publish, proposal, acknowledgment, force-approve, and consumption event
- **Web UI** — Create and manage teams, register repositories and services, review and acknowledge proposals, explore the service dependency graph, search assets, and browse the audit log. Data ingestion (dbt, OpenAPI, GraphQL, gRPC sync) is API-only, designed for CI/CD pipelines

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
| `TESSERA_REPO_DIR` | Directory for cloned repositories | `./data/repos` |
| `TESSERA_GIT_TOKEN` | Git auth token for private repos (injected into HTTPS clone URLs) | None |
| `TESSERA_SYNC_INTERVAL` | Background repo sync poll interval in seconds (0 to disable) | `60` |
| `TESSERA_REPO_MAX_SIZE_MB` | Maximum clone size in megabytes | `500` |
| `TESSERA_GIT_TIMEOUT` | Git operation timeout in seconds | `120` |
| `TESSERA_SYNC_TIMEOUT` | Overall sync operation timeout in seconds | `600` |
| `TESSERA_SYNC_CONCURRENCY` | Max repos to sync concurrently in background worker | `4` |

See [configuration docs](https://ashita-ai.github.io/tessera/getting-started/quickstart/) for the full list.

## Git-based repo sync

Register a repository and Tessera automatically discovers spec files, creates services, and publishes contracts. A background worker polls for changes so contracts stay up to date without CI integration.

### Registering a repo

```bash
curl -X POST http://localhost:8000/api/v1/repos \
  -H "Content-Type: application/json" \
  -d '{
    "name": "orders-service",
    "git_url": "https://github.com/acme/orders-service.git",
    "owner_team_id": "<team-uuid>",
    "default_branch": "main",
    "spec_paths": ["api/", "proto/"],
    "sync_enabled": true
  }'
```

### Input validation

| Field | Constraints |
|-------|-------------|
| `git_url` | Must start with `https://` or `git@`. Max 500 characters. |
| `default_branch` | Must start with an alphanumeric character. Allowed characters: `a-z A-Z 0-9 . / _ -`. Must not contain `..`. Max 100 characters. |
| `spec_paths` | Glob patterns relative to the repo root. Must not contain `..` path components. |

### How sync works

1. **Clone/pull** — First sync does a shallow clone (`--depth 1`). Subsequent syncs fetch and reset to the latest commit. Repos exceeding `TESSERA_REPO_MAX_SIZE_MB` are rejected.
2. **Spec discovery** — Scans `spec_paths` globs for `.yaml`/`.json` (OpenAPI, detected by `openapi` key), `.proto` (gRPC), and `.graphql`/`.gql` files. Hidden directories and `node_modules`/`vendor` are skipped.
3. **Service assignment** — Each spec file is assigned to the service whose `root_path` is the longest prefix match. If no service matches, one is auto-created with a name inferred from the directory structure.
4. **Contract publishing** — Parsed schemas are published via the standard contract engine with backward compatibility mode. Compatible changes auto-publish; breaking changes create proposals.

### Triggering a sync manually

```bash
curl -X POST http://localhost:8000/api/v1/repos/<repo-uuid>/sync
```

Returns the full sync result including specs found, contracts published, and any errors.

### Background worker

When `TESSERA_SYNC_INTERVAL` > 0 (default: 60s), a background task polls repos with `sync_enabled=true`. Each repo is synced in its own database transaction so failures are isolated. Set `TESSERA_SYNC_INTERVAL=0` to disable polling entirely.

### Private repos

Set `TESSERA_GIT_TOKEN` to a GitHub personal access token or app installation token. The token is injected into HTTPS clone URLs as `x-access-token`. SSH URLs (`git@...`) are passed through unchanged — ensure the server has the appropriate SSH key.

## Documentation

- [Quickstart Guide](https://ashita-ai.github.io/tessera/getting-started/quickstart/)
- [Sync Adapters](https://ashita-ai.github.io/tessera/api/sync/) (OpenAPI, GraphQL, gRPC, dbt)
- [Python SDK](https://ashita-ai.github.io/tessera/guides/python-sdk/) | [PyPI](https://pypi.org/project/tessera-sdk/)
- [AI Agent Integration](https://ashita-ai.github.io/tessera/guides/ai-agent-integration/)
- [API Reference](https://ashita-ai.github.io/tessera/api/overview/)

## License

Apache License 2.0
