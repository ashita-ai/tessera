# Tessera

**Data contract coordination for data warehouses.**

Tessera helps data teams coordinate schema changes across producers and consumers. When a producer wants to make a breaking change, consumers are notified and must acknowledge before the change goes live.

## Why Tessera?

Data teams face a common problem: **breaking changes break pipelines**.

- A data engineer renames a column
- Downstream dashboards break
- Analysts discover it days later
- Everyone scrambles to fix it

Tessera solves this by making breaking changes explicit:

1. **Producers publish contracts** - JSON Schema definitions of their data assets
2. **Consumers register dependencies** - Teams declare which assets they depend on
3. **Breaking changes require acknowledgment** - Before a breaking change goes live, all consumers must acknowledge

## Key Features

- **Schema Diffing** - Automatically detect breaking vs non-breaking changes
- **Consumer Registration** - Track who depends on what
- **Proposal Workflow** - Coordinate breaking changes across teams
- **dbt Integration** - Sync contracts from your dbt manifest
- **Audit Logging** - Track all contract changes and data quality events
- **Web UI** - Visual interface for managing contracts and proposals

## Quick Example

```python
import httpx

# Publish a contract for your model
response = httpx.post(
    "http://localhost:8000/api/v1/assets/my-asset-id/contracts",
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
    },
    headers={"Authorization": "Bearer your-api-key"}
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
┌─────────────────┐     ┌─────────────────┐
│  dbt Project    │────▶│    Tessera      │
│  (manifest.json)│     │    Server       │
└─────────────────┘     └────────┬────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐      ┌─────────────────┐      ┌───────────────┐
│   Producer    │      │    Consumer     │      │   Consumer    │
│   Team A      │      │    Team B       │      │   Team C      │
└───────────────┘      └─────────────────┘      └───────────────┘
```

## License

Tessera is open source under the MIT License.
