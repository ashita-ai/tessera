# ADR-014: Pivot from Data Warehouse Contracts to Service Contract Coordination

**Status:** Accepted
**Date:** 2026-04-02
**Authors:** Evan Volgas, Jeremiah (co-design)

## Context

Tessera was built to coordinate schema contracts for data warehouses: dbt models publish schemas, downstream consumers register dependencies, breaking changes require acknowledgment. The core abstractions — contracts, proposals, registrations, compatibility modes, schema diffing — work well for this.

But the harder, more valuable problem is the same coordination across **services**. Teams break each other's APIs without knowing. Dependencies between services are invisible unless someone manually documents them. A breaking change to a gRPC method or REST endpoint silently propagates through a service graph, and the team that made the change only finds out when another team's oncall pages at 2 AM.

The data warehouse contract model and the service contract model share the same underlying mechanics:

- A **producer** publishes a schema (OpenAPI spec, protobuf definition, JSON Schema)
- **Consumers** depend on that schema (discovered from traffic or declared explicitly)
- A **breaking change** to the schema needs coordination before it ships
- An **audit trail** records who changed what, when, and why

The difference is in how contracts and dependencies are discovered:

| | Data Warehouse (current) | Service Contracts (proposed) |
|---|---|---|
| **Schema source** | dbt manifest, manual upload | Git repos (OpenAPI, protobuf, GraphQL specs) |
| **Dependency discovery** | Manual registration | Auto-discovered from OTEL traces + manual |
| **Notification** | Webhooks, proposals | Slack, webhooks, proposals |
| **Change detection** | POST new contract to API | Poll repo for spec changes |

Tessera's codebase is well-positioned for this pivot. Of ~26,500 lines of production code, ~4,400 lines (~17%) are warehouse-specific (dbt sync, BigQuery/DuckDB connectors). The remaining 83% — schema diffing, proposal workflow, registrations, impact analysis, audit trail, versioning, auth, webhooks — is already schema-agnostic. The OpenAPI, GraphQL, and gRPC sync endpoints already exist.

## Decision

Evolve Tessera from a data-warehouse-first contract tool into a **service contract coordination platform**. Warehouse support remains as one integration among many, not the primary use case.

### What changes

#### 1. New entities: Repo and Service

The current model is flat: `Team → Asset → Contract`. The pivot introduces two new entities that reflect how services actually work:

```
Team → Repo(s) → Service(s) → Asset(s) → Contract(s)
```

**Repo** is a git repository. It's the unit of code ownership and the place where API specs live. Repos have:

- A git URL and default branch
- An owning team (derived from CODEOWNERS or explicitly set)
- Spec file paths to scan (e.g., `api/openapi.yaml`, `proto/`)
- A polling interval for change detection
- A last-synced commit SHA

**Service** is a deployable unit within a repo. A monorepo may contain multiple services; a single-service repo contains one. Services have:

- A name and a parent repo
- A root path within the repo (e.g., `services/order-service/` or `/` for single-service repos)
- An optional OTEL service name for dependency auto-discovery

Assets (API endpoints, gRPC methods, GraphQL operations) belong to a Service, which belongs to a Repo, which belongs to a Team. This replaces the current pattern where assets are free-floating and manually created.

**Why Repo is separate from Service:**

- A repo is where you run CI checks ("did this PR break a contract?"). That's a per-repo question.
- Multiple services can live in one repo (monorepo). You need the indirection.
- CODEOWNERS is a repo-level concept — it maps file paths to teams/reviewers.
- Git operations (clone, fetch, poll) happen at the repo level, not the service level. Without a Repo entity, a monorepo with 5 services would be cloned 5 times.

**CODEOWNERS as a discovery mechanism:**

"Team" remains the organizational entity. CODEOWNERS is a way to *auto-populate* team ownership, not a replacement for it:

1. Register a repo → Tessera reads CODEOWNERS
2. CODEOWNERS maps path patterns to GitHub teams/users
3. Tessera suggests team mappings for each service based on its root path
4. Human confirms or overrides

This works because not everyone uses GitHub (GitLab has a similar but different format), CODEOWNERS can be stale, and "team" is what humans think in.

#### 2. Repo-based spec discovery

Instead of requiring producers to POST schemas to Tessera, Tessera pulls specs from git repositories:

1. Team registers a repo, pointing at a git URL + spec paths
2. Tessera discovers services within the repo (from directory structure, CODEOWNERS, or explicit config)
3. Background worker polls the repo (or receives a webhook from CI)
4. On change: parse the spec using existing sync logic (OpenAPI, gRPC, GraphQL parsers already exist)
5. Run schema diff against the current contract
6. Auto-publish compatible changes; create proposals for breaking changes

This is the core proof of concept. It reuses the existing sync endpoints (`api/sync/openapi.py`, `api/sync/graphql.py`, `api/sync/grpc.py`) as internal libraries rather than HTTP endpoints.

#### 3. OTEL-based dependency discovery

Instead of requiring consumers to manually register dependencies, Tessera observes them from real traffic:

1. Query an OTEL-compatible backend (Jaeger, Tempo, Datadog) for service-to-service call edges
2. Map observed edges to `AssetDependency` records with confidence scores
3. Reconcile: observed dependencies that don't have explicit registrations get flagged for review; explicit registrations not seen in traffic get flagged as potentially stale
4. When a breaking change is detected, Tessera already knows who to notify — from traffic data, not manual config

Start with **one** backend (Jaeger Query API). Add Tempo, Datadog, Observe as connectors later. Do not attempt a universal OTEL adapter on day one.

#### 4. Slack notifications

When a breaking change is detected or a proposal is created, notify the affected team's Slack channel. This builds on the existing webhook infrastructure:

- New formatter: proposal/breaking-change events → Slack Block Kit messages
- Configuration: team → Slack channel mapping
- Uses the webhook delivery system (outbox pattern from #397 when implemented)

### What stays the same

- **Contract/proposal/registration model** — the workflow is identical. A breaking API change creates a proposal, affected consumers acknowledge it, force-publish is the escape hatch.
- **Schema diffing engine** — JSON Schema comparison is format-agnostic. OpenAPI, protobuf, and GraphQL specs already normalize to JSON Schema.
- **Compatibility modes** (ADR-005) — backward/forward/full/none apply to API contracts the same way they apply to data contracts.
- **Publishing flow** (ADR-009) — three-path logic (first contract, compatible change, breaking change) is unchanged.
- **Audit trail** — same append-only event log with actor_type (human/agent).
- **Versioning** — semantic versioning applies to API contracts.
- **Auth model** — teams own repos which own services; API keys identify agents. PR #407 added username-based auth and bot users (UserType.BOT), which provides the foundation for machine identity. Bot users authenticate exclusively via API keys and are blocked from web login — this is how background sync workers and CI integrations identify themselves.

### What gets deprecated

- **dbt sync endpoints** — continue as a sync adapter on equal footing with OpenAPI, GraphQL, and gRPC. No longer the primary integration path.
- **BigQuery/DuckDB connectors** — removed. These were speculative and had zero test coverage (#395).
- **Warehouse-specific resource types** (MODEL, SOURCE, SEED, SNAPSHOT) — still valid enum values but not the focus.

### What happens to the AI Enablement epic (#362)

The MCP tool server concept (ADR-001, #361) is still sound, but the tool surface needs to reflect services rather than data contracts:

| Current tool | Becomes |
|---|---|
| `tessera_search_assets` | `tessera_search_services` / `tessera_search_assets` (both) |
| `tessera_register_asset` | `tessera_register_repo` / `tessera_register_service` |
| (new) | `tessera_discover_dependencies` (trigger OTEL scan) |
| (new) | `tessera_check_api_compat` (diff a local spec against current contract) |

Defer MCP implementation until the service registry and OTEL discovery are stable.

## Implementation Sequence

### Phase 1: Repo + service registry and repo-based discovery (weeks 1–3)

- `RepoDB` and `ServiceDB` models + migration
- CRUD endpoints for repos and services
- CODEOWNERS parser for team ownership suggestions
- Background worker: git clone/pull → spec extraction → existing sync logic
- Demo: register a repo with two services, change an OpenAPI spec, Tessera detects the breaking change

**Why first:** This is the smallest thing that demonstrates the pivot's value. It reuses existing code (sync parsers, schema diff, proposal workflow) and requires no external infrastructure beyond git.

### Phase 2: OTEL dependency discovery (weeks 4–7)

- Jaeger Query API client
- Dependency edge extraction from traces
- Confidence scoring (frequency, recency)
- Reconciliation with explicit registrations
- Auto-registration of discovered consumers

**Why second:** Dependency discovery is the force multiplier, but the system must be useful with manual registration first. If repo-based discovery doesn't work well, auto-discovery won't save it.

### Phase 3: Slack notifications + polish (weeks 8–10)

- Slack Block Kit formatter
- Team → channel configuration
- Service dependency graph visualization
- ~~Deprecation of warehouse-first documentation and framing~~ (done)

**Why third:** Notifications are the most visible feature to end users but depend on the proposal workflow already generating the right events.

## Consequences

**Benefits:**

- Addresses a broader market. Every team with microservices has this problem; not every team uses dbt.
- 83% of the codebase is reusable. The pivot is additive, not a rewrite.
- OTEL-based discovery removes the biggest adoption barrier (manual dependency registration).
- The existing proposal/acknowledgment workflow is a differentiator — most API change tools just detect breaking changes without coordinating resolution.

**Costs:**

- Maintaining multiple sync adapters (OpenAPI, GraphQL, gRPC, dbt) increases surface area. Each adapter is intentionally thin — parsing and normalization only.
- OTEL integration ties Tessera to the observability stack. Teams without OTEL can still use manual registration, but the "magic" auto-discovery feature requires it.
- Repo polling introduces git as an infrastructure dependency. Webhook-based triggers (CI integration) are the long-term answer but add integration work.
- The dbt community was a natural early-adopter audience. Pivoting away from warehouse-first messaging means finding a new go-to-market angle.

## Alternatives Considered

**Rewrite in Go:** Go would give better concurrency primitives and smaller deployment artifacts. Rejected because: (a) 58K lines of working Python + tests would be thrown away, (b) the workload is coordination (low throughput, schema comparison, DB queries), not data-plane (high throughput, low latency), (c) Python has first-class OTEL SDK support, (d) the team knows Python. If OTEL ingestion needs raw-span-level throughput later, write that component as a Go sidecar.

**Fork into a new project:** Rejected because the domain model is the same. An API endpoint is an asset, an OpenAPI spec is a contract, a service calling another service is a registration. Forking means rewriting 22K lines of reusable code to end up with the same abstractions.

**Keep warehouse-first, add services as secondary:** Rejected because the framing matters. If Tessera is "a dbt contract tool that also does services," service-oriented teams won't evaluate it. The core abstractions are general; the product framing should be too.
