# Spec 003: MCP Resources and Subscriptions

**Strategy doc**: [Agent Opportunity](../strategy/agent-opportunity.md)
**Depends on**: [MCP Tool Server (ADR-001 Spec 005)](../adrs/specs/005-mcp-tool-server.md)
**Priority**: 3 (ship alongside or shortly after the MCP tool server)
**Status**: Draft
**Estimated effort**: 1 week (additive to the MCP server build)

## Overview

The existing MCP tool server spec (ADR-001/005) defines 9 tools and 3 basic resources. This spec extends the resource layer with subscribable, typed resources that let agents reference contract schemas without tool calls and receive change notifications without polling.

**Tools vs Resources:**
- **Tools** are actions: "search for an asset", "publish a contract", "acknowledge a proposal". They require the agent to decide to call them.
- **Resources** are data: "the current schema for orders", "guarantees for dim_customers". They're available in the agent's context window automatically if subscribed. When the underlying data changes, the agent is notified.

Resources make Tessera invisible infrastructure. An agent doesn't need to "use Tessera" — it just has schema context available and gets notified when it changes.

## Resource URIs

### Asset Schema

```
tessera://assets/{fqn}/schema
```

Returns the current active contract's schema for the asset. This is what an agent needs to generate correct SQL or validate its assumptions.

**Response format:**
```json
{
  "uri": "tessera://assets/warehouse.analytics.orders/schema",
  "mimeType": "application/json",
  "text": "{\"type\":\"object\",\"properties\":{\"order_id\":{\"type\":\"integer\"},\"customer_id\":{\"type\":\"integer\"},\"total_amount\":{\"type\":\"number\"},\"status\":{\"type\":\"string\",\"enum\":[\"pending\",\"shipped\",\"delivered\",\"cancelled\"]}},\"required\":[\"order_id\",\"customer_id\",\"total_amount\",\"status\"]}"
}
```

The `text` field contains the JSON Schema as a string. This is per MCP spec — resource contents are text.

**Changes trigger notification:** When a new contract is published for this asset (via webhook or polling the Tessera API), the MCP server emits a `notifications/resources/updated` message for subscribers.

### Asset Guarantees

```
tessera://assets/{fqn}/guarantees
```

Returns quality guarantees and freshness SLA for the asset.

**Response format:**
```json
{
  "uri": "tessera://assets/warehouse.analytics.orders/guarantees",
  "mimeType": "application/json",
  "text": "{\"freshness\":{\"max_stale_hours\":12},\"not_null\":[\"order_id\",\"customer_id\"],\"unique\":[\"order_id\"],\"accepted_values\":{\"status\":[\"pending\",\"shipped\",\"delivered\",\"cancelled\"]}}"
}
```

Agents use this to validate assumptions. An agent generating SQL that filters on `status = 'returned'` can check against accepted_values and realize that value doesn't exist.

### Asset Context (Full)

```
tessera://assets/{fqn}/context
```

Returns the full context blob from `GET /assets/{id}/context`: schema, guarantees, field descriptions, field tags, consumers, lineage, proposals, audits. This is the heavyweight resource for agents that need everything.

Most agents should use `/schema` or `/guarantees` instead. This resource exists for orchestration agents that need the complete picture.

### Team Pending Proposals

```
tessera://teams/{team_name}/pending
```

Returns pending proposals awaiting this team's acknowledgment. This is the agent's inbox.

**Response format:**
```json
{
  "uri": "tessera://teams/ml-features/pending",
  "mimeType": "application/json",
  "text": "[{\"proposal_id\":\"uuid\",\"asset_fqn\":\"warehouse.analytics.orders\",\"breaking_changes_summary\":[\"Removed column: discount_code\"],\"proposed_by\":\"core-data\",\"proposed_at\":\"2026-03-28T14:00:00Z\",\"expires_at\":\"2026-04-04T14:00:00Z\",\"your_team_status\":\"AWAITING_RESPONSE\"}]"
}
```

**Changes trigger notification:** When a new proposal is created that affects this team, or when a proposal's status changes, the MCP server emits `notifications/resources/updated`.

## Resource Templates

MCP supports resource templates — parameterized URIs that agents can fill in:

```typescript
server.setRequestHandler(ListResourceTemplatesRequestSchema, async () => ({
  resourceTemplates: [
    {
      uriTemplate: "tessera://assets/{fqn}/schema",
      name: "Asset Schema",
      description: "Current contract schema for a data asset. Use the fully qualified name (e.g., warehouse.analytics.orders).",
      mimeType: "application/json",
    },
    {
      uriTemplate: "tessera://assets/{fqn}/guarantees",
      name: "Asset Guarantees",
      description: "Data quality guarantees (freshness, not-null, unique, accepted_values) for a data asset.",
      mimeType: "application/json",
    },
    {
      uriTemplate: "tessera://assets/{fqn}/context",
      name: "Asset Full Context",
      description: "Complete context: schema, guarantees, field descriptions, consumers, lineage, proposals, and audit history.",
      mimeType: "application/json",
    },
    {
      uriTemplate: "tessera://teams/{team_name}/pending",
      name: "Team Pending Proposals",
      description: "Breaking change proposals awaiting this team's acknowledgment.",
      mimeType: "application/json",
    },
  ],
}));
```

## Subscription / Change Notification

### How It Works

1. Agent subscribes to a resource (e.g., `tessera://assets/warehouse.analytics.orders/schema`).
2. MCP server registers the subscription in memory.
3. MCP server polls Tessera's REST API at a configurable interval (default: 30 seconds) for changes. Alternatively, registers a Tessera webhook that pushes change events.
4. When a change is detected, MCP server sends `notifications/resources/updated` with the resource URI.
5. Agent re-reads the resource to get the new content.

### Change Detection Strategy

**Option A: Polling (simpler, default)**

The MCP server maintains an in-memory cache of `{resource_uri: last_known_version}`. On each poll interval:
- For schema resources: `GET /assets/{id}/contracts?status=ACTIVE` and compare version string.
- For pending proposals: `GET /proposals/pending/{team_id}` and compare response hash.

Poll interval is configurable via `MCP_POLL_INTERVAL_SECONDS` (default 30).

**Option B: Webhook-driven (lower latency)**

On startup, the MCP server registers a Tessera webhook for relevant events:
- `contract.published` → triggers update for `tessera://assets/{fqn}/schema` and `/guarantees`
- `proposal.created` → triggers update for `tessera://teams/{team}/pending`
- `proposal.acknowledged` → triggers update for `tessera://teams/{team}/pending`

This requires the MCP server to have an HTTP endpoint for receiving webhooks, which is only possible in SSE transport mode (not stdio). Fall back to polling for stdio.

**Recommendation:** Start with polling (Option A). Add webhook support when the MCP server runs in SSE mode.

## Implementation in MCP Server

### New Files

```
packages/mcp-server/
├── src/
│   ├── resources/
│   │   ├── schema.ts         # tessera://assets/{fqn}/schema
│   │   ├── guarantees.ts     # tessera://assets/{fqn}/guarantees
│   │   ├── context.ts        # tessera://assets/{fqn}/context
│   │   ├── pending.ts        # tessera://teams/{team}/pending
│   │   └── subscriptions.ts  # Subscription manager + polling loop
```

### Subscription Manager

```typescript
class SubscriptionManager {
  private subscriptions: Map<string, { lastHash: string; interval: NodeJS.Timer }>;
  private pollIntervalMs: number;

  subscribe(uri: string): void;
  unsubscribe(uri: string): void;

  // Called by poll loop
  private async checkForUpdates(uri: string): Promise<boolean>;

  // Emits MCP notification
  private notifyChanged(uri: string): void;
}
```

### Resource Handler Registration

```typescript
// In index.ts, after tool registration:

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;

  if (uri.startsWith("tessera://assets/") && uri.endsWith("/schema")) {
    return handleSchemaResource(uri);
  }
  if (uri.startsWith("tessera://assets/") && uri.endsWith("/guarantees")) {
    return handleGuaranteesResource(uri);
  }
  if (uri.startsWith("tessera://assets/") && uri.endsWith("/context")) {
    return handleContextResource(uri);
  }
  if (uri.startsWith("tessera://teams/") && uri.endsWith("/pending")) {
    return handlePendingResource(uri);
  }

  throw new McpError(ErrorCode.InvalidRequest, `Unknown resource: ${uri}`);
});

server.setRequestHandler(SubscribeRequestSchema, async (request) => {
  subscriptionManager.subscribe(request.params.uri);
  return {};
});

server.setRequestHandler(UnsubscribeRequestSchema, async (request) => {
  subscriptionManager.unsubscribe(request.params.uri);
  return {};
});
```

## Testing

| Test case | Assertion |
|-----------|-----------|
| Read schema resource | Returns active contract schema as JSON string |
| Read schema for unknown asset | Returns MCP error (resource not found) |
| Read guarantees resource | Returns guarantee object from active contract |
| Read context resource | Returns full context blob |
| Read pending resource | Returns pending proposals for team |
| Resource template listing | All 4 templates returned with correct URIs |
| Subscription + poll detects change | After contract publish, subscriber receives `notifications/resources/updated` |
| Subscription + no change | No notification emitted when resource unchanged |
| Unsubscribe stops notifications | No notification after unsubscribe |
| FQN parsing | Correctly extracts FQN from `tessera://assets/a.b.c/schema` |
| Team name parsing | Correctly extracts team name from `tessera://teams/my-team/pending` |
| Asset with no contract | Schema resource returns empty/null with explanatory message |

## Relationship to Spec 005

This spec extends, not replaces, the existing MCP tool server spec (ADR-001/005). Spec 005 defines:
- 9 tools (search, context, impact, publish, register, proposals)
- 3 basic resources (asset list, asset detail, pending proposals)
- Error handling and project structure

This spec adds:
- 4 typed resource templates with parameterized URIs
- Subscription support with change notification
- Polling-based change detection (with webhook upgrade path)

The implementation lives in the same `packages/mcp-server/` project. The resource handlers are registered alongside the tool handlers in `index.ts`.
