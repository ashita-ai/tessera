# Spec 005: MCP Tool Server

**ADR**: 001-ai-enablement
**Priority**: 5 (depends on specs 001-004)
**Status**: Draft

## Overview

A TypeScript sidecar process that exposes Tessera's capabilities as MCP (Model Context Protocol) tools. Any MCP-compatible AI agent can discover and call these tools without hand-wiring HTTP clients.

## Architecture

```
┌──────────────┐     MCP (stdio/SSE)     ┌──────────────────┐     HTTP/REST     ┌──────────────┐
│  AI Agent    │ ◄──────────────────────► │  MCP Sidecar     │ ───────────────► │  Tessera     │
│  (Claude,    │                          │  (TypeScript)     │                  │  (Python)    │
│   Cursor,    │                          │                   │                  │              │
│   etc.)      │                          │  Port 3100        │                  │  Port 8000   │
└──────────────┘                          └──────────────────┘                  └──────────────┘
```

The sidecar:
- Runs as a separate process alongside the Tessera Python server
- Speaks MCP over stdio (for local agents) and SSE (for remote agents)
- Calls Tessera's REST API using an agent API key
- Is stateless — all state lives in Tessera
- Can be scaled independently

## Technology

- **Runtime**: Node.js 20+
- **Language**: TypeScript 5.x
- **MCP SDK**: `@modelcontextprotocol/sdk`
- **HTTP client**: `fetch` (native)
- **Build**: `tsup` or `tsc`
- **Package**: Published as `@tessera/mcp-server` on npm

## Configuration

Environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TESSERA_URL` | yes | — | Tessera server URL (e.g., `http://localhost:8000`) |
| `TESSERA_API_KEY` | yes | — | API key for authenticating with Tessera |
| `MCP_TRANSPORT` | no | `stdio` | Transport: `stdio` or `sse` |
| `MCP_PORT` | no | `3100` | Port for SSE transport |
| `LOG_LEVEL` | no | `info` | Logging level |

## Tools

### tessera_search_assets

Find assets by name, team, type, or tags.

```typescript
{
  name: "tessera_search_assets",
  description: "Search for data assets in Tessera by name, team, type, or tags. Use this to find assets before checking contracts or impact.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "Search term (matches asset FQN, description)" },
      team: { type: "string", description: "Filter by owner team name" },
      resource_type: { type: "string", description: "Filter by type: MODEL, SOURCE, SEED, API_ENDPOINT, etc." },
      tags: { type: "array", items: { type: "string" }, description: "Filter by tags (all must match)" }
    }
  }
}
```

Maps to: `GET /api/v1/search?q={query}&...` and `GET /api/v1/assets?...`

### tessera_get_asset_context

Get everything about an asset: contract, consumers, lineage, audit status.

```typescript
{
  name: "tessera_get_asset_context",
  description: "Get full context for a data asset: current contract schema, consumers, upstream/downstream lineage, and recent audit results. Call this before modifying any data asset.",
  inputSchema: {
    type: "object",
    properties: {
      asset_id: { type: "string", description: "Asset UUID" },
      asset_fqn: { type: "string", description: "Asset fully qualified name (alternative to asset_id)" }
    }
  }
}
```

Maps to: `GET /api/v1/assets/{asset_id}/context`

If `asset_fqn` is provided instead of `asset_id`, the tool first resolves it via search.

### tessera_check_impact

Pre-flight check: what would break if this schema changed?

```typescript
{
  name: "tessera_check_impact",
  description: "Check the impact of a proposed schema change BEFORE making it. Returns breaking changes, affected consumers, downstream impact, and migration suggestions. Always call this before publishing a new contract version.",
  inputSchema: {
    type: "object",
    properties: {
      asset_id: { type: "string", description: "Asset UUID" },
      asset_fqn: { type: "string", description: "Asset FQN (alternative to asset_id)" },
      proposed_schema: { type: "object", description: "The new schema to evaluate" },
      proposed_guarantees: { type: "object", description: "New guarantees (optional)" }
    },
    required: ["proposed_schema"]
  }
}
```

Maps to: `POST /api/v1/assets/{asset_id}/impact-preview`

### tessera_publish_contract

Publish a new contract version for an asset.

```typescript
{
  name: "tessera_publish_contract",
  description: "Publish a new contract version. For non-breaking changes, publishes immediately. For breaking changes, creates a proposal that consumers must acknowledge. Always call tessera_check_impact first.",
  inputSchema: {
    type: "object",
    properties: {
      asset_id: { type: "string" },
      asset_fqn: { type: "string" },
      schema_def: { type: "object", description: "The contract schema" },
      version: { type: "string", description: "Semantic version (optional, auto-incremented if omitted)" },
      compatibility_mode: { type: "string", description: "backward, forward, full, or none" },
      guarantees: { type: "object" },
      field_descriptions: { type: "object" },
      force: { type: "boolean", description: "Force publish even if breaking (creates audit record)" }
    },
    required: ["schema_def"]
  }
}
```

Maps to: `POST /api/v1/assets/{asset_id}/publish`

### tessera_register_asset

Create a new data asset in Tessera. Use this when building a new dbt model, API endpoint, or any data asset that should be tracked.

```typescript
{
  name: "tessera_register_asset",
  description: "Register a new data asset in Tessera. Call this when creating a new dbt model, table, API endpoint, or other data asset. Sets up the asset for contract publishing and consumer registration.",
  inputSchema: {
    type: "object",
    properties: {
      fqn: { type: "string", description: "Fully qualified name (e.g., 'prod.analytics.dim_customers')" },
      environment: { type: "string", description: "Environment (e.g., 'production', 'staging')", default: "production" },
      resource_type: { type: "string", enum: ["MODEL", "SOURCE", "SEED", "SNAPSHOT", "API_ENDPOINT", "GRAPHQL_QUERY", "KAFKA_TOPIC", "EVENT_STREAM", "OTHER"], description: "Type of data asset" },
      owner_team_id: { type: "string", description: "UUID of the owning team" },
      owner_team_name: { type: "string", description: "Team name (alternative to owner_team_id, resolved via lookup)" },
      description: { type: "string", description: "Human-readable description of what this asset represents" },
      tags: { type: "array", items: { type: "string" }, description: "Labels (e.g., ['pii', 'financial', 'sla:p1'])" },
      compatibility_mode: { type: "string", enum: ["backward", "forward", "full", "none"], default: "backward" }
    },
    required: ["fqn", "resource_type"]
  }
}
```

Maps to: `POST /api/v1/assets`

If `owner_team_name` is provided instead of `owner_team_id`, the tool resolves it via `GET /api/v1/teams?name={name}`.

### tessera_register_consumer

Declare that an asset depends on (consumes) another asset's contract. Use this when an agent starts reading from or depending on a data asset.

```typescript
{
  name: "tessera_register_consumer",
  description: "Register as a consumer of a data asset's contract. This ensures you'll be notified of breaking changes and must acknowledge them before they publish. Call this when your asset reads from or depends on another asset.",
  inputSchema: {
    type: "object",
    properties: {
      contract_id: { type: "string", description: "UUID of the contract to consume" },
      asset_fqn: { type: "string", description: "FQN of the asset to consume (alternative — resolves to current active contract)" },
      consumer_team_id: { type: "string", description: "UUID of the consuming team" },
      consumer_team_name: { type: "string", description: "Team name (alternative to consumer_team_id)" },
      pinned_version: { type: "string", description: "Pin to a specific version (optional, defaults to tracking latest)" }
    }
  }
}
```

Maps to: `POST /api/v1/registrations?contract_id={contract_id}`

If `asset_fqn` is provided, resolves to the current active contract for that asset.

### tessera_list_pending_proposals

The agent's inbox: what proposals need my team's attention?

```typescript
{
  name: "tessera_list_pending_proposals",
  description: "List breaking change proposals that are waiting for your team's acknowledgment. This is how a consumer agent discovers that an upstream producer wants to make a breaking change. Call this periodically or before starting work to check for pending coordination requests.",
  inputSchema: {
    type: "object",
    properties: {
      team_id: { type: "string", description: "UUID of the team to check proposals for" },
      team_name: { type: "string", description: "Team name (alternative to team_id)" },
      status: { type: "string", enum: ["PENDING", "APPROVED", "PUBLISHED", "REJECTED", "WITHDRAWN", "EXPIRED"], default: "PENDING", description: "Filter by proposal status" }
    }
  }
}
```

Maps to: `GET /api/v1/proposals/pending/{team_id}` (defined in Spec 001).

If `team_name` is provided instead of `team_id`, the tool resolves it via `GET /api/v1/teams?name={name}`.

### tessera_get_proposal

Check the status of a specific proposal: who's acknowledged, who's pending, is it ready to publish?

```typescript
{
  name: "tessera_get_proposal",
  description: "Get the full status of a breaking change proposal. Shows which consumers have acknowledged (and their response), which are still pending, and whether the proposal is ready to publish. Use this after publishing a breaking change to track progress toward resolution.",
  inputSchema: {
    type: "object",
    properties: {
      proposal_id: { type: "string", description: "UUID of the proposal" }
    },
    required: ["proposal_id"]
  }
}
```

Maps to: `GET /api/v1/proposals/{proposal_id}`

### tessera_acknowledge_proposal

Respond to a breaking change proposal on behalf of a consumer team.

```typescript
{
  name: "tessera_acknowledge_proposal",
  description: "Acknowledge a breaking change proposal. Response can be 'APPROVED' (ready for the change), 'BLOCKED' (cannot accept), or 'MIGRATING' (will be ready by deadline).",
  inputSchema: {
    type: "object",
    properties: {
      proposal_id: { type: "string" },
      response: { type: "string", enum: ["APPROVED", "BLOCKED", "MIGRATING"] },
      notes: { type: "string", description: "Explanation for the response" },
      migration_deadline: { type: "string", description: "ISO 8601 date, required if MIGRATING" }
    },
    required: ["proposal_id", "response"]
  }
}
```

Maps to: `POST /api/v1/proposals/{proposal_id}/acknowledge`

## MCP Resources (Read-Only Context)

In addition to tools, expose MCP resources for agents that want to browse:

| Resource URI | Description |
|-------------|-------------|
| `tessera://assets` | List of all assets (paginated) |
| `tessera://assets/{id}` | Asset detail with current contract |
| `tessera://proposals/pending` | Open proposals awaiting acknowledgment |

## Error Handling

The sidecar translates Tessera HTTP errors into MCP tool errors:

| HTTP Status | MCP Error |
|------------|-----------|
| 401, 403 | "Authentication failed. Check TESSERA_API_KEY." |
| 404 | "Asset not found: {fqn or id}" |
| 422 | Pass through validation error details |
| 429 | "Rate limited. Retry after {n} seconds." |
| 500+ | "Tessera server error. Check server logs." |

## Project Structure

```
packages/mcp-server/
├── src/
│   ├── index.ts          # Entry point, MCP server setup
│   ├── tools/            # One file per tool
│   │   ├── search.ts
│   │   ├── context.ts
│   │   ├── impact.ts
│   │   ├── publish.ts
│   │   ├── register-asset.ts
│   │   ├── register-consumer.ts
│   │   ├── pending-proposals.ts
│   │   ├── proposal.ts
│   │   └── acknowledge.ts
│   ├── resources/        # MCP resource handlers
│   ├── client.ts         # Tessera REST API client
│   └── config.ts         # Environment config
├── package.json
├── tsconfig.json
└── README.md
```

## Deployment

### Docker Compose (alongside Tessera)

```yaml
services:
  tessera:
    # ... existing config

  tessera-mcp:
    build: ./packages/mcp-server
    environment:
      TESSERA_URL: http://tessera:8000
      TESSERA_API_KEY: ${MCP_AGENT_API_KEY}
      MCP_TRANSPORT: sse
      MCP_PORT: 3100
    ports:
      - "3100:3100"
    depends_on:
      - tessera
```

### Local Development (stdio)

```bash
cd packages/mcp-server
TESSERA_URL=http://localhost:8000 TESSERA_API_KEY=tsk_... npx tsx src/index.ts
```

Agents configure in their MCP settings (e.g., Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tessera": {
      "command": "npx",
      "args": ["tsx", "/path/to/packages/mcp-server/src/index.ts"],
      "env": {
        "TESSERA_URL": "http://localhost:8000",
        "TESSERA_API_KEY": "tsk_..."
      }
    }
  }
}
```

## Testing

| Test case | Assertion |
|-----------|-----------|
| Tool discovery | All 9 tools listed in MCP tool list |
| FQN resolution | `asset_fqn` resolves to `asset_id` before API call |
| Team name resolution | `owner_team_name` / `team_name` resolves to UUID before API call |
| Register asset | Creates asset, returns asset ID and FQN |
| Register consumer | Creates registration, returns registration ID |
| Impact check | Calls impact-preview endpoint, returns formatted result |
| Publish (non-breaking) | Calls publish endpoint, returns new version |
| Publish (breaking) | Returns proposal ID, explains acknowledgment needed |
| List pending proposals | Returns only proposals missing this team's ack |
| List pending proposals (none) | Returns empty list when all proposals are acknowledged |
| Get proposal status | Shows per-consumer ack status, ready-to-publish flag |
| Acknowledge proposal | Records response, returns updated proposal status |
| Auth error | Clear error message about API key |
| Server down | Graceful error, no crash |
| Rate limited | Returns retry-after information |
