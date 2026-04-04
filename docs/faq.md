# Frequently Asked Questions

## General

### Why is it called Tessera?

In ancient Rome, a *tessera hospitalis* was a small tablet of bone, ivory, or terracotta that two parties broke in half as a binding contract of mutual obligation — a relationship called *hospitium*. Each party kept one half. When the holders (or even their descendants, generations later) needed to prove the relationship, they fit the pieces together. No central authority required — the match itself was the proof.

That's the idea behind this project. Producers and consumers each hold their side of a service contract. Tessera is the system that makes sure the pieces still fit when someone wants to change the shape.

### What is Tessera?

Tessera is a service contract coordination platform. It lets producers publish schema contracts for their APIs, services, and data models while consumers register dependencies — so breaking changes require explicit acknowledgment before going live. It works across OpenAPI, GraphQL, gRPC, and dbt through a schema-agnostic contract engine that normalizes everything to JSON Schema.

### How is Tessera different from a schema registry?

Schema registries (like Confluent Schema Registry) store and version schemas, but they don't coordinate between producers and consumers. Tessera adds a **proposal-acknowledgment workflow**: when a breaking change is detected, it creates a proposal, notifies all registered consumers, and blocks publication until each consumer explicitly acknowledges. Non-breaking changes still auto-publish immediately.

### What schema formats does Tessera support?

Tessera supports JSON Schema, Avro, OpenAPI, and GraphQL. All formats are normalized to JSON Schema internally for diffing and compatibility checking.

### Is Tessera open source?

Yes. Tessera is released under the MIT License.

### Does Tessera replace my data warehouse or ETL tool?

No. Tessera sits alongside your existing stack. It doesn't move, transform, or store data — it coordinates the *contracts* that describe your service interfaces and data models so that changes are communicated before they break downstream consumers.

---

## Schemas and Compatibility

### What counts as a breaking change?

It depends on the compatibility mode configured for the asset:

| Mode | Breaking if... |
|------|----------------|
| **backward** | Remove field, add required field, narrow type, remove enum value, tighten constraint, remove default, remove nullable |
| **forward** | Add field, remove required field, widen type, add enum value, relax constraint, add default, add nullable |
| **full** | Any schema change at all |
| **none** | Nothing — changes are logged but never blocked |

### What happens when I publish a non-breaking change?

The new contract auto-publishes immediately with an appropriate version bump, and the previous contract is deprecated. No proposal is created.

### What happens when I publish a breaking change?

Tessera creates a **Proposal** instead of publishing. All registered consumers are notified (via webhooks, if configured). Each consumer must acknowledge the proposal — with a response of APPROVED, BLOCKED, or MIGRATING — before it can be published. Alternatively, an admin can force-publish.

### How does schema diffing work?

Tessera compares the incoming schema against the current published contract. It detects 18 types of changes including property additions/removals, type narrowing/widening, required field changes, enum value changes, constraint changes, nullability changes, and default value changes. Each change is classified as breaking or non-breaking based on the asset's compatibility mode.

### Can I force-publish a breaking change without waiting for acknowledgments?

Yes, but only admins can do this. A reason is required, and the action is recorded in the audit log. Use this for emergencies, not as a routine workaround.

---

## Teams and Ownership

### Why are assets owned by teams instead of users?

Teams provide organizational responsibility that survives personnel changes. If an individual leaves, the team still owns the asset. Users can optionally be assigned as stewards for individual accountability, but the team is always the authoritative owner.

### What roles are available?

- **ADMIN** — Full system access, including user management and force-publish
- **TEAM_ADMIN** — Manage team membership and team-scoped resources
- **USER** — Standard operations: publish contracts, register as consumer, acknowledge proposals

---

## Consumer Registration and Dependencies

### How do I register as a consumer?

Call `POST /api/v1/registrations` with the contract ID and your team ID. You can also auto-register via dbt sync by adding `consumers` to your model's `meta.tessera` block, or by enabling `infer_consumers_from_refs` during dbt manifest upload.

### What is the difference between CONSUMES, REFERENCES, and TRANSFORMS?

These are asset-to-asset dependency types used for lineage and impact analysis:

- **CONSUMES** — Direct data consumption (e.g., a dashboard reading from a table)
- **REFERENCES** — A foreign key or lookup relationship
- **TRANSFORMS** — A dbt model transforming an upstream source

### How does impact analysis work?

When a breaking change is proposed, Tessera recursively traverses the dependency graph to identify all downstream assets and the teams that own them. You can preview this before publishing via the `/impact-preview` endpoint.

---

## Proposals and Acknowledgments

### What are the possible acknowledgment responses?

- **APPROVED** — The consumer is ready for the change
- **BLOCKED** — The consumer cannot accept the change (visible to the producer, but does not hard-block force-publish)
- **MIGRATING** — The consumer needs more time; can include a migration deadline

### What happens if a proposal is never acknowledged?

Proposals expire after a configurable period (30 days by default). Expired proposals are not published.

### Can a producer withdraw a proposal?

Yes. The producer can withdraw a pending proposal, which cancels it without publishing the change.

---

## Integrations

### How does the dbt integration work?

The dbt integration is one of several sync adapters (alongside OpenAPI, GraphQL, and gRPC). Upload your `manifest.json` to `POST /api/v1/sync/dbt/upload`. Tessera extracts models, sources, seeds, and snapshots; converts dbt column types to JSON Schema; maps dbt tests to data quality guarantees; and optionally auto-publishes contracts. Configure behavior via your model's `meta.tessera` YAML block (owner, consumers, freshness, volume, compatibility mode).

### Can I use Tessera with OpenAPI or GraphQL?

Yes — these are first-class sync adapters. Upload an OpenAPI 3.x spec to `/api/v1/sync/openapi` or a GraphQL introspection result to `/api/v1/sync/graphql`. Tessera creates one asset per endpoint or operation and extracts schemas from request/response definitions. All schemas are normalized to JSON Schema internally, so the same diffing, compatibility checking, and proposal workflow applies regardless of source.

### Does Tessera support Avro schemas?

Yes. Set `schema_format: "avro"` when publishing a contract. Tessera applies the same diffing and compatibility checking as it does for JSON Schema.

### Is there a Python SDK?

Yes. Install [`tessera-sdk`](https://pypi.org/project/tessera-sdk/) from PyPI. It provides sync and async clients with typed Pydantic models for all API resources. See the [SDK guide](guides/python-sdk.md) for usage examples.

### Can AI agents use Tessera?

Yes — AI agents are first-class citizens. They can register as consumers, check contracts before modifying schemas, acknowledge proposals, and receive webhook notifications. See the [AI Agent Integration guide](guides/ai-agent-integration.md).

---

## Deployment and Operations

### What database does Tessera require?

PostgreSQL with the `asyncpg` driver for production. SQLite (via `aiosqlite`) works for local development and testing.

### How do I deploy Tessera?

The quickest path is `docker compose up -d`, which starts PostgreSQL and the Tessera server on port 8000. For production, configure `DATABASE_URL`, set a strong `SESSION_SECRET_KEY`, and optionally connect Redis for caching. See the [Docker guide](guides/docker.md) for details.

### What health check endpoints are available?

- `GET /health` — Basic health check
- `GET /health/ready` — Readiness probe (database connected)
- `GET /health/live` — Liveness probe

### Does Tessera support webhooks?

Yes. Register webhook endpoints via the API, and Tessera will deliver signed (HMAC-SHA256) event payloads for contract publications, proposal creation, acknowledgments, and other events. Delivery attempts are tracked for observability.

### Is there rate limiting?

Yes, enabled by default. Default limits: 1000 reads/min, 100 writes/min, 50 admin operations/min, and 5000 requests/min per IP globally. These are configurable via environment variables.

---

## Data Quality

### What guarantees can I attach to a contract?

- **Not-null** and **unique** constraints on specific columns
- **Accepted values** — enumerated allowed values for a column
- **Freshness** — maximum staleness in minutes, with a measured column
- **Volume** — minimum row count and maximum row delta percentage
- **Custom** — arbitrary guarantees from dbt tests (standard, third-party, and singular tests)

### What are guarantee modes?

- **STRICT** — Removing or weakening a guarantee is treated as a breaking change
- **NOTIFY** — Guarantee changes are logged but don't block publication
- **IGNORE** — Guarantee changes are not tracked

### What is Write-Audit-Publish?

An optional workflow that blocks contract publication until data quality audits pass. This ensures that published contracts reflect data that actually meets its stated guarantees.
