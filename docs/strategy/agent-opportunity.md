# Agent Opportunity

**Status:** Draft
**Date:** 2026-03-29
**Author:** Evan Volgas

## Thesis

AI agents are the fastest-growing category of data consumer. They interact with warehouses, APIs, and event streams — and they have zero tolerance for schema ambiguity. A human analyst can look at a column called `status` and infer meaning from context. An agent can't. An agent needs a contract.

Data contracts were conceived as a coordination mechanism between human teams. But the problem they solve — "tell me exactly what this data looks like, what it guarantees, and whether it's safe to use right now" — is the same problem every AI agent faces before it generates a SQL query, builds a feature vector, or writes to a downstream table.

**The opportunity: Tessera is already 70% of the way to being the schema intelligence layer that makes AI agents safe to connect to data infrastructure.** The remaining 30% is distribution (MCP), generation (AI-powered migrations), and positioning.

---

## What's Already Built

Tessera has more agent infrastructure than any comparable open-source data tool. This wasn't accidental — ADR-001 specifically targeted AI enablement. Here's the current inventory:

### Agent Identity & Accountability

| Feature | How it works |
|---------|-------------|
| Agent fields on API keys | `agent_name` ("dbt-codegen-agent") and `agent_framework` ("langchain") recorded on every key |
| `is_agent` property | Computed from `agent_name IS NOT NULL` — clean boolean for branching logic |
| Actor type in audit trail | Every audit event records `actor_type: "agent"` or `"human"`. Filterable via `GET /audit/events?actor_type=agent` |
| Agent key listing | `GET /api-keys?is_agent=true` returns only agent keys |

### Agent-Optimized Rate Limiting

Agents make more frequent, smaller requests (check-before-write pattern). Throttling them at human rates would break the preflight workflow.

| Tier | Human | Agent |
|------|-------|-------|
| Read | 1,000/min | 5,000/min |
| Write | 100/min | 500/min |
| Admin | 50/min | 250/min |

### Preflight Checks (`GET /{fqn}/preflight`)

The single most important endpoint for agent consumers. Before an agent queries a dataset, it calls preflight and gets:

```json
{
  "asset_fqn": "warehouse.analytics.orders",
  "contract_version": "2.1.0",
  "fresh": true,
  "freshness_sla": {"max_staleness_minutes": 60, "last_measured_at": "..."},
  "guarantees": {"not_null": ["order_id", "customer_id"], "unique": ["order_id"]},
  "last_audit_status": "PASSED",
  "caveats": []
}
```

An agent can use this to decide: Is this data fresh enough? Are the guarantees sufficient for my use case? Are there caveats I should surface to the user?

### Asset Context (`GET /{asset_id}/context`)

A single-call aggregation of everything an agent needs to understand a dataset: schema, field descriptions, field tags (PII, join-key), consumers, upstream/downstream lineage, active proposals, recent audit results, contract history count.

This is the equivalent of an agent reading the documentation, the schema, and the operational history of a dataset in one API call.

### Semantic Metadata

- **Field descriptions**: `{"$.properties.customer_id": "Unique identifier, matches CRM system ID"}` — machine-readable documentation at the field level.
- **Field tags**: `{"$.properties.email": ["pii", "gdpr-deletable"]}` — labels that let agents apply policy (don't include PII in prompts, flag GDPR-deletable fields for deletion workflows).
- **Asset tags**: `["financial", "sla:p1"]` — asset-level classification.

### Migration Suggester

When a breaking change is detected, the migration suggester generates non-breaking alternatives:
- Property removed → deprecate instead (re-add with `deprecated: true`)
- Required field added → make optional with default value
- Type narrowed → add `{field}_v2` with new type
- Enum values removed → re-add removed values

This is designed for both humans and agents. But agents benefit disproportionately — they can automatically apply the suggestions without human review in many cases.

---

## The Three Agent Roles

The current framing treats agents primarily as consumers. But agents occupy three distinct roles in data ecosystems, and each has different needs from Tessera.

### Role 1: Agent as Consumer

**Who:** Text-to-SQL agents, RAG pipelines, analytics copilots, feature store readers.

**What they need:**
- Know what datasets exist and what they contain (asset search, context endpoint)
- Verify data is fresh and reliable before querying (preflight)
- Understand field semantics to generate correct queries (semantic metadata)
- Be notified when schemas they depend on are changing (proposals via webhook)

**What Tessera already provides:** ~80% coverage. Preflight, context, semantic metadata, webhooks all exist. The gap is passive discovery of what agents actually query (see [Passive Discovery](passive-discovery.md)).

**What's missing:**
- Column-level usage tracking. If an agent generates SQL that uses columns A, B, C — Tessera should know, so impact analysis can report "this agent uses column B, which you're about to drop."
- Query pattern registration. Instead of registering "I consume this asset," register "I use these columns with these filters." Enables precise impact analysis instead of all-or-nothing alerts.

### Role 2: Agent as Producer

**Who:** dbt CI agents, ETL pipeline agents, LLM-powered data transformation agents, code generation agents that output schema definitions.

**What they need:**
- Publish schemas without human intervention (AUTO versioning mode)
- Get rejected when they produce a breaking change (not silently break consumers)
- Receive migration suggestions when their proposed change is breaking
- Full audit trail of what they published and when

**What Tessera already provides:** ~90% coverage. The three-path publishing flow (ADR-009) handles this well. AUTO versioning, breaking change detection, proposal creation, migration suggestions — all built.

**What's missing:**
- Schema validation guardrails. An agent might generate a schema that's technically valid JSON Schema but semantically broken (e.g., a `price` field typed as `string`). Tessera could flag schemas that deviate from conventions established by prior versions.
- Confidence scoring. When an agent publishes, it could declare its confidence in the schema. Low-confidence publishes could trigger additional review.

### Role 3: Agent as Coordinator

**Who:** Orchestration agents (Dagster, Airflow), platform engineering agents, incident response agents.

**What they need:**
- View pending proposals across all teams (team inbox)
- Auto-acknowledge proposals based on policy (e.g., "if the breaking change only affects deprecated columns, auto-approve")
- Trigger impact analysis proactively ("what would break if we dropped this table?")
- Coordinate multi-step migrations across producer and consumer agents

**What Tessera already provides:** ~40% coverage. Pending proposals endpoint exists. Impact preview exists. But there's no policy engine for automatic acknowledgment, no multi-step migration coordination, and no way for an agent to orchestrate a full breaking change lifecycle.

**What's missing:**
- Acknowledgment policies. A team should be able to configure rules like: "auto-approve if the only change is adding a nullable column" or "auto-approve if the affected columns haven't been queried in 90 days."
- Migration orchestration. The migration suggester generates alternatives for individual breaking changes. But coordinating a migration across N consumers — generating per-consumer migration plans, tracking progress, verifying completion — is a higher-order capability that doesn't exist.

---

## MCP as Distribution Channel

The MCP tool server specification (ADR-001, Spec 005) defines 9 tools that expose Tessera's core capabilities through Model Context Protocol. This is the single most important distribution mechanism for the agent opportunity.

### Why MCP Matters

MCP is becoming the standard interface between AI agents and tools. Every major agent framework (Claude Code, Cursor, LangChain, CrewAI) supports or is adopting MCP. A Tessera MCP server means:

1. **Zero integration code.** Any MCP-compatible agent can connect to Tessera by adding a server config. No SDK installation, no custom code.
2. **Invisible adoption.** A platform team deploys the MCP server once. Every agent that connects to their MCP hub gets Tessera capabilities without knowing Tessera exists. The schema metadata becomes a resource, not a product.
3. **Natural discovery.** When an agent asks "what data is available?", the MCP server responds with Tessera's asset catalog. When the agent says "I want to query orders," the server can automatically run preflight. Tessera becomes part of the agent's environment, not a tool it has to learn to use.

### Current State

Spec 005 defines the MCP server but it's not yet built. The 9 tools map directly to existing REST endpoints:

| MCP Tool | REST Endpoint |
|----------|--------------|
| `tessera_search_assets` | `GET /assets/search` |
| `tessera_get_asset_context` | `GET /assets/{id}/context` |
| `tessera_check_impact` | `POST /assets/{id}/impact-preview` |
| `tessera_publish_contract` | `POST /assets/{id}/contracts` |
| `tessera_register_asset` | `POST /assets` |
| `tessera_register_consumer` | `POST /registrations` |
| `tessera_list_pending_proposals` | `GET /pending-proposals` |
| `tessera_get_proposal` | `GET /proposals/{id}` |
| `tessera_acknowledge_proposal` | `POST /proposals/{id}/acknowledge` |

### MCP Resources (Not Yet Specified)

Beyond tools, MCP supports **resources** — data that agents can read without calling a tool. Tessera should expose:

- `tessera://assets/{fqn}/schema` — Current schema for an asset (agents reference this when generating queries)
- `tessera://assets/{fqn}/guarantees` — Quality guarantees (agents use this to validate their assumptions)
- `tessera://assets/{fqn}/lineage` — Upstream and downstream graph (agents use this for planning)
- `tessera://teams/{team}/pending` — Pending proposals for a team (agents use this as an inbox)

Resources are cacheable and subscriptable. An agent could subscribe to `tessera://assets/warehouse.analytics.orders/schema` and get notified when the schema changes — without polling.

---

## AI-Powered Migration Generation

The migration suggester (ADR-001, Spec 003) uses rule-based strategies. This is a foundation to build on, not the end state.

### The Vision

When a breaking change is detected, Tessera generates **per-consumer migration plans** using an LLM that understands:
- The old schema and the new schema
- Each consumer's dependency type (CONSUMES, REFERENCES, TRANSFORMS)
- Each consumer's known query patterns (if available from passive discovery)
- The consumer's technology stack (dbt model? dashboard? Python script?)

**Example scenario:**

Producer wants to rename `orders.status` to `orders.order_status` and change its type from `varchar` to an enum.

Tessera generates:
- For **Consumer A** (dbt model that transforms orders): a modified SQL model with the column rename and a case statement to handle the type change.
- For **Consumer B** (dashboard that filters on status): a migration note that the filter values have changed from free-text to enum values, with the valid enum list.
- For **Consumer C** (LangChain agent that generates queries): an updated field description and enum constraint that the agent's next preflight call will pick up automatically.

### Implementation Path

1. **Phase 1 (current):** Rule-based suggestions. Generic strategies that don't know about specific consumers.
2. **Phase 2:** Consumer-aware suggestions. Use dependency type and registration metadata to generate targeted migration advice.
3. **Phase 3:** LLM-generated migrations. Use an LLM to generate actual migration code (SQL, dbt YAML, Python) tailored to each consumer's stack. Requires knowing what the consumer looks like (passive discovery provides this).

### Why This Matters for Agents

Human teams can negotiate migration paths in meetings. Agents can't. If an agent receives a breaking change notification with no guidance on how to adapt, it fails. If it receives a breaking change notification with a concrete migration plan it can apply, it continues operating.

**The migration plan is the difference between "agents are notified of changes" and "agents automatically adapt to changes."** The first is monitoring. The second is infrastructure.

---

## Risks

### Risk 1: Registration cold-start kills adoption

If the dependency graph is empty, impact analysis is useless, and the coordination workflow notifies no one. Agents won't register voluntarily. **Mitigation:** Passive discovery (see [Passive Discovery](passive-discovery.md)) and dbt sync (automatic dependency extraction from manifests) are the two paths to bootstrap the graph without requiring manual registration.

---

## Recommended Actions

### Build Now (Q2 2026)

1. **Ship the MCP server.** Spec 005 is written. The REST endpoints exist. This is a TypeScript wrapper that unlocks distribution to every MCP-compatible agent. Highest ROI action available.

2. **Add MCP resources.** Expose schemas, guarantees, and lineage as MCP resources (not just tools). This enables agents to subscribe to schema changes and reference contracts without tool calls.

3. **Column-level dependency tracking.** Extend registrations to optionally specify which columns a consumer uses. This makes impact analysis precise enough to be trusted. Start with dbt (column lineage from manifests) and manual registration.

### Build Next (Q3 2026)

4. **Acknowledgment policies.** Let teams configure auto-acknowledgment rules. This enables the "agent as coordinator" role and reduces manual toil for routine changes.

5. **Consumer-aware migration suggestions.** Extend the migration suggester to generate per-consumer advice based on dependency type and known usage patterns.

6. **Passive discovery prototype.** Start with one warehouse (Snowflake or BigQuery query logs). Extract which tables and columns are queried, by whom, and how often. Map to Tessera assets. See [Passive Discovery](passive-discovery.md).

### Build Later (Q4 2026+)

7. **LLM-powered migration generation.** Use an LLM to generate actual migration code tailored to each consumer's stack.

8. **Agent confidence scoring.** Let agent publishers declare confidence in their schemas. Low-confidence triggers additional review.

9. **Schema convention enforcement.** Flag agent-generated schemas that deviate from conventions established by prior versions of the same asset.
