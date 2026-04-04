# Tessera

**Service contract coordination — stop breaking each other's APIs.**

Tessera helps teams coordinate schema changes across service boundaries. When a producer wants to make a breaking API change, consumers are notified and must acknowledge before the change goes live.

## Why Tessera?

Teams face a common problem: **breaking changes break other teams' services**. Dependencies between services are invisible unless someone manually documents them.

- A team removes a field from their REST API
- Three other services that depend on that field break in production
- The team that made the change only finds out when another team's oncall pages at 2 AM
- Everyone scrambles to fix it

Tessera solves this by making dependencies explicit and breaking changes coordinated:

1. **Producers publish contracts** - JSON Schema definitions of their API endpoints, gRPC methods, GraphQL operations, or data models
2. **Consumers register dependencies** - Teams declare which contracts they depend on
3. **Breaking changes require acknowledgment** - Before a breaking change goes live, all consumers must acknowledge

## Key Features

- **Schema Diffing** - Automatically detect breaking vs non-breaking changes across any JSON Schema source
- **Consumer Registration** - Track who depends on what
- **Proposal Workflow** - Coordinate breaking changes across teams
- **Sync Adapters** - Import contracts from OpenAPI specs, GraphQL introspection, gRPC/protobuf definitions, and dbt manifests
- **Audit Logging** - Track all contract changes and data quality events
- **Web UI** - Visual interface for managing contracts and proposals

## Quick Example

```python
import httpx

# Publish a contract for your asset
response = httpx.post(
    "http://localhost:8000/api/v1/assets/my-asset-id/contracts",
    params={"published_by": "your-team-id"},
    json={
        "schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "email": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"}
            },
            "required": ["user_id", "email"]
        },
        "compatibility_mode": "backward"
    }
)
```

If you later try to remove `email` (a breaking change), Tessera will:

1. Create a **Proposal** instead of publishing immediately
2. Notify all registered consumers
3. Wait for acknowledgments before allowing the change

## Getting Started

<div class="grid cards" markdown>

-   :material-clock-fast:{ .lg .middle } **Quickstart**

    ---

    Get up and running in 5 minutes with Docker

    [:octicons-arrow-right-24: Quickstart](getting-started/quickstart.md)

-   :material-download:{ .lg .middle } **Installation**

    ---

    Install Tessera in your environment

    [:octicons-arrow-right-24: Installation](getting-started/installation.md)

-   :material-robot:{ .lg .middle } **AI Agent Integration**

    ---

    Give your AI agents contract-aware guardrails

    [:octicons-arrow-right-24: Agent Guide](guides/ai-agent-integration.md)

-   :material-book-open-variant:{ .lg .middle } **Concepts**

    ---

    Understand how Tessera works

    [:octicons-arrow-right-24: Concepts](concepts/overview.md)

-   :material-api:{ .lg .middle } **API Reference**

    ---

    Complete API documentation

    [:octicons-arrow-right-24: API Reference](api/overview.md)

</div>

## Architecture

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  OpenAPI Spec   │  │ GraphQL Schema  │  │  gRPC/Protobuf  │  │  dbt Manifest   │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │                    │
         └────────────────────┼────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │    Tessera      │
                    │    Server       │
                    │  (JSON Schema)  │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌───────────────┐
│   Producer    │  │    Consumer     │  │   Consumer    │
│   Team A      │  │    Team B       │  │   Team C      │
└───────────────┘  └─────────────────┘  └───────────────┘
```

## License

Tessera is open source under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
