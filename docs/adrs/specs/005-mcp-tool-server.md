# Spec 005: MCP Tool Server

**ADR**: 001-ai-enablement, 014-service-contract-pivot
**Priority**: Phase 3 (depends on specs 001, 003, 004, 006, 007)
**Status**: Not Yet Implemented (updated 2026-04-02 for service contract pivot)

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

---

## Service Contract Pivot Additions (ADR-014)

The following tools are added for the service-first workflow. Existing tools remain unchanged — they work for both data warehouse and service contract use cases.

### tessera_register_repo

Register a git repository for Tessera to monitor.

```typescript
{
  name: "tessera_register_repo",
  description: "Register a git repo in Tessera. Points Tessera at a repo containing API specs (OpenAPI, protobuf, GraphQL). Tessera will monitor the repo for changes, discover services within it, and automatically detect breaking changes. Use this when onboarding a new codebase.",
  inputSchema: {
    type: "object",
    properties: {
      name: { type: "string", description: "Repo name (e.g., 'order-service' or 'platform-monorepo')" },
      git_url: { type: "string", description: "Git repository URL" },
      spec_paths: { type: "array", items: { type: "string" }, description: "Paths to API specs in the repo (e.g., ['api/openapi.yaml', 'proto/'])" },
      owner_team_name: { type: "string", description: "Owning team name" },
      default_branch: { type: "string", description: "Branch to track (default: main)" }
    },
    required: ["name", "git_url", "spec_paths", "owner_team_name"]
  }
}
```

Maps to: `POST /api/v1/repos`

### tessera_register_service

Register a service within a repo.

```typescript
{
  name: "tessera_register_service",
  description: "Register a service within a repo. A service is a deployable unit — in a single-service repo this is the whole repo, in a monorepo it's one service directory. Tessera auto-discovers services during sync, but you can also register them explicitly.",
  inputSchema: {
    type: "object",
    properties: {
      name: { type: "string", description: "Service name (e.g., 'order-service')" },
      repo_name: { type: "string", description: "Parent repo name" },
      root_path: { type: "string", description: "Path within repo (e.g., 'services/orders/' or '/')" },
      otel_service_name: { type: "string", description: "OTEL service.name for auto-dependency discovery (optional)" }
    },
    required: ["name", "repo_name"]
  }
}
```

Maps to: `POST /api/v1/services`

### tessera_sync_repo

Trigger an immediate sync of a repo's API specs.

```typescript
{
  name: "tessera_sync_repo",
  description: "Trigger an immediate sync of a repo's API specs from git. Tessera will clone/pull the repo, discover services, parse specs, and detect any schema changes since the last sync. Use this after pushing API spec changes.",
  inputSchema: {
    type: "object",
    properties: {
      repo_name: { type: "string", description: "Repo name (resolved to repo ID)" },
      repo_id: { type: "string", description: "Repo UUID (alternative to repo_name)" }
    }
  }
}
```

Maps to: `POST /api/v1/repos/{id}/sync`

### tessera_discover_dependencies

Trigger an OTEL-based dependency scan to auto-discover which services call which.

```typescript
{
  name: "tessera_discover_dependencies",
  description: "Trigger dependency discovery from OTEL traces. Queries the configured trace backend (Jaeger/Tempo) to find service-to-service call edges. Creates dependency records with confidence scores. Use this to populate the dependency graph from real traffic data.",
  inputSchema: {
    type: "object",
    properties: {
      config_name: { type: "string", description: "OTEL config name (e.g., 'production-jaeger')" },
      config_id: { type: "string", description: "OTEL config UUID (alternative)" }
    }
  }
}
```

Maps to: `POST /api/v1/otel/configs/{id}/sync`

### tessera_check_api_compat

Check compatibility of a local API spec against the current contract without publishing.

```typescript
{
  name: "tessera_check_api_compat",
  description: "Check if a local API spec is compatible with the current contract in Tessera. Use this before committing API changes to verify they won't break consumers. Pass the spec content directly — Tessera will parse it (OpenAPI, protobuf, or GraphQL) and diff against the active contract.",
  inputSchema: {
    type: "object",
    properties: {
      service_name: { type: "string", description: "Service name" },
      asset_fqn: { type: "string", description: "Asset FQN to check against" },
      spec_content: { type: "string", description: "The API spec content (YAML, JSON, proto, or GraphQL SDL)" },
      spec_format: { type: "string", enum: ["openapi", "protobuf", "graphql"], description: "Spec format" }
    },
    required: ["spec_content", "spec_format"]
  }
}
```

Maps to: parse spec → extract schema → `POST /api/v1/assets/{asset_id}/impact-preview`

### tessera_get_dependency_graph

Get the service dependency graph for understanding the system topology.

```typescript
{
  name: "tessera_get_dependency_graph",
  description: "Get the service-to-service dependency graph. Shows which services depend on which, with dependency types and confidence scores. Use this to understand the blast radius of a change before making it.",
  inputSchema: {
    type: "object",
    properties: {
      team_name: { type: "string", description: "Filter to a team's services and their neighbors (optional)" },
      min_confidence: { type: "number", description: "Minimum confidence for OTEL-discovered edges (0.0-1.0, default 0.5)" }
    }
  }
}
```

Maps to: `GET /api/v1/graph/services`

### tessera_reconcile_dependencies

Compare declared vs observed dependencies to find gaps.

```typescript
{
  name: "tessera_reconcile_dependencies",
  description: "Compare manually declared dependencies against OTEL-observed traffic. Shows undeclared dependencies (services calling each other without registration), stale dependencies (declared but not observed), and confirmed dependencies. Use this to audit dependency completeness.",
  inputSchema: {
    type: "object",
    properties: {}
  }
}
```

Maps to: `GET /api/v1/dependencies/reconciliation`

## Updated Tool Count

Original tools: 9 (search, context, impact, publish, register asset, register consumer, pending proposals, get proposal, acknowledge)

Added tools: 7 (register repo, register service, sync repo, discover dependencies, check API compat, dependency graph, reconcile dependencies)

Total: 16 tools

## Updated Testing

Additional test cases for new tools:

| Test case | Assertion |
|-----------|-----------|
| Register repo | Creates repo, returns repo ID and name |
| Register repo (invalid git URL) | Clear error about URL format |
| Register service | Creates service within repo, returns service ID |
| Sync repo | Returns sync result with service/asset counts |
| Sync repo (not found) | Clear error about repo name |
| Discover dependencies | Returns discovered edge count |
| Check API compat (compatible) | Returns is_breaking=false |
| Check API compat (breaking) | Returns breaking changes list with migration suggestions |
| Dependency graph | Returns nodes and edges in graph format |
| Reconcile dependencies | Returns declared_only, observed_only, and confirmed lists |
