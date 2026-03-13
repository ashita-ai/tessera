# ADR-001: AI Enablement

**Status**: Draft
**Date**: 2026-03-12
**Authors**: Evan Volgas

## Context

AI agents that interact with data infrastructure — writing SQL, building dbt models, designing APIs, generating pipeline code — are proliferating. These agents modify schemas, add fields, change types, and restructure data assets. Today, they do this without guardrails: an agent can break downstream consumers silently because it has no way to discover who depends on what, or what changes are safe.

Tessera already solves the coordination problem for humans: producers publish contracts, consumers register dependencies, breaking changes require acknowledgment. But the interface is designed for human workflows — REST APIs called from dashboards and CLIs, Slack notifications read by people, proposals acknowledged by team leads.

AI agents need the same coordination, but shaped differently:

- **Discovery**: Agents need to find Tessera's capabilities without hand-wiring HTTP clients. MCP (Model Context Protocol) is the emerging standard for tool discovery.
- **Pre-flight checks**: Before modifying a schema, an agent needs a single call that answers "what would break if I made this change?" Today this requires composing 3-4 API calls.
- **Actionable feedback**: When a change is breaking, agents need machine-readable migration alternatives, not just a rejection.
- **Identity**: Agents act on behalf of teams but need their own audit identity so humans can distinguish agent actions from human actions.
- **Semantic context**: Schemas have field names and types but no descriptions or business meaning. Agents can't reason about what `dim_cust_ltv_adj` means without this.

## Decision

We will make Tessera a first-class tool for AI agents through four workstreams:

### 1. MCP Tool Server (TypeScript sidecar)

A TypeScript sidecar process that exposes Tessera's capabilities as MCP tools. It calls the Tessera REST API internally.

**Why TypeScript**: The MCP SDK has first-class TypeScript support. The Python server is solid and well-tested — rewriting it would be waste. A sidecar keeps concerns separated: Tessera owns data contract logic, the MCP layer owns agent-facing tool definitions.

**Why sidecar, not embedded**: The MCP server has different scaling characteristics (stateless, lightweight, horizontally scalable) and a different release cadence (tool definitions change as agent patterns emerge). Decoupling deployment lets us iterate on the agent interface without risking the core server.

Tools exposed (initial set):

| Tool | Purpose |
|------|---------|
| `tessera_search_assets` | Find assets by name, team, or type |
| `tessera_get_asset_context` | Full picture: contract, consumers, lineage, audit status |
| `tessera_register_asset` | Create a new data asset (dbt model, API endpoint, etc.) |
| `tessera_register_consumer` | Declare a dependency on another asset's contract |
| `tessera_check_impact` | "If I change this schema, what breaks?" |
| `tessera_publish_contract` | Publish a new contract version |
| `tessera_list_pending_proposals` | "What proposals need my team's acknowledgment?" |
| `tessera_get_proposal` | Check proposal status: who's acked, who's pending |
| `tessera_acknowledge_proposal` | Respond to a breaking change proposal |

### 2. New REST Endpoints

New endpoints that serve both agents (via MCP sidecar) and existing SDK/UI consumers:

#### `POST /api/v1/assets/{asset_id}/impact-preview`

Single-call pre-flight check. Accepts a proposed schema, returns:
- Whether the change is breaking (and for which compatibility mode)
- List of affected consumers with team, asset, and registration details
- List of affected downstream assets (full lineage traversal)
- Suggested version bump
- If breaking: machine-readable migration suggestions

```json
{
  "proposed_schema": { ... },
  "proposed_guarantees": { ... }
}
```

Response:
```json
{
  "is_breaking": true,
  "breaking_changes": [ ... ],
  "affected_consumers": [
    { "team": "analytics", "asset_fqn": "prod.analytics.user_metrics", "registration_id": "..." }
  ],
  "affected_downstream": [
    { "asset_fqn": "prod.reporting.daily_users", "depth": 2, "owner_team": "reporting" }
  ],
  "suggested_version": "3.0.0",
  "migration_suggestions": [
    {
      "strategy": "additive",
      "description": "Add new field alongside old, deprecate old field",
      "suggested_schema": { ... }
    }
  ]
}
```

#### `GET /api/v1/proposals/pending/{team_id}`

The agent's inbox. Returns proposals awaiting a specific team's acknowledgment. Composes proposal listing, registration lookup, and acknowledgment checking into a single query. This is the consumer-side entry point to the coordination workflow — without it, agents can't discover that upstream producers want to make breaking changes.

#### `GET /api/v1/assets/{asset_id}/context`

Returns everything an agent needs to understand an asset: current contract, schema with semantic annotations, consumers, upstream/downstream lineage, recent audit results, active proposals. One call replaces 5+ individual lookups.

### 3. Agent Identity

Extend the API key model to support agent identity:

- New field `agent_name` on `APIKeyDB` (nullable). When set, this key represents an agent rather than a human.
- New field `agent_framework` (nullable). Values like `"claude-code"`, `"cursor"`, `"codegen"`, `"custom"`. For observability and analytics.
- Audit events include `actor_type` (`human` | `agent`) derived from the API key.
- Agent keys can be scoped to specific assets or teams (narrower than current team-wide scoping).
- Rate limits can differ for agent vs. human keys.

This is deliberately lightweight. We don't create a separate `AgentDB` model — agents are identified by their API key metadata. This keeps the auth model simple while giving full audit trail visibility.

### 4. Schema Migration Suggestions (Rule-Based)

A new service that generates non-breaking migration alternatives for common breaking change patterns:

| Breaking change | Suggested migration |
|----------------|-------------------|
| Field removed | Mark field deprecated + nullable, keep in schema |
| Field type narrowed | Add new field with new type, deprecate old |
| Required field added | Add as optional with default value |
| Enum values removed | Keep old values, mark deprecated in description |
| Type changed | Add new field, deprecate old, document mapping |

Implementation: deterministic rules in `services/migration_suggester.py`. Each rule takes a `BreakingChange` and the old/new schemas, returns a `MigrationSuggestion` with a modified schema that's backward-compatible.

**Future**: Optional LLM enhancement for complex cases (field renames, structural reorganization). This would be an opt-in feature behind a flag, calling an external LLM API. The rule-based engine handles the common cases and provides the interface that the LLM enhancement plugs into.

### 5. Semantic Metadata

Extend schemas and assets to carry business context that agents can use for reasoning:

- `description` field on assets (already exists but underused)
- `field_descriptions` on contracts: a map of JSON path -> human-readable description
- `tags` on assets: free-form labels like `["pii", "financial", "sla:p1"]`
- `glossary_ref` on fields: optional link to a business glossary entry

This metadata is optional and additive — it doesn't change any existing behavior. Sync endpoints (dbt, OpenAPI, GraphQL) will extract descriptions from source metadata when available (dbt already has column descriptions; OpenAPI has field descriptions).

## Consequences

### Positive
- AI agents get guardrails: they can check before breaking things
- Tessera becomes a dependency for AI-powered data workflows, increasing adoption
- The MCP interface makes Tessera discoverable by any MCP-compatible agent
- Agent audit trail gives teams visibility into what agents are doing
- Semantic metadata improves the experience for humans too (better search, documentation)

### Negative
- TypeScript sidecar adds operational complexity (two processes to deploy, monitor, version)
- Migration suggestions may give agents false confidence if the suggestions are wrong
- Agent traffic patterns differ from human traffic — may need capacity planning
- Semantic metadata is only useful if teams populate it — requires adoption effort

### Risks
- MCP is still evolving — tool interface may change
- Agent key scoping (per-asset, per-team) adds authorization complexity
- Migration suggestions for edge cases may be incorrect — need clear "confidence" signaling

## Implementation Order

1. **Impact preview endpoint** — highest value, no new infrastructure needed
2. **Agent identity on API keys** — small schema change, unlocks audit visibility
3. **Migration suggestion service** — rule-based, pure Python, no external dependencies
4. **Semantic metadata** — schema extension, sync endpoint updates
5. **MCP tool server** — TypeScript sidecar, depends on 1-4 being stable
6. **Asset context endpoint** — aggregation endpoint, useful but not blocking

## Alternatives Considered

### Rewrite Tessera in TypeScript
Rejected. The Python codebase is production-grade with comprehensive tests. Rewriting would take months and risk regressions. The sidecar approach gives us TypeScript where we need it (MCP) without throwing away working code.

### Embed MCP in the Python server
Rejected. Python MCP SDK exists but is less mature. More importantly, coupling the MCP layer to the Python server means they share a release cycle and scaling characteristics. The sidecar is operationally cleaner.

### LLM-powered migration suggestions from day one
Deferred. Rule-based covers ~80% of cases, ships faster, has no external dependencies, and is deterministic. The LLM enhancement can be added later behind a feature flag, using the same interface.

### GraphQL API instead of REST
Rejected for now. The existing API is REST, the SDK is REST, the MCP sidecar will call REST. Adding GraphQL would mean maintaining two API surfaces. If agent query patterns prove too chatty with REST, we can revisit.
