# AI Agent Integration

AI agents that write SQL, build dbt models, or generate pipeline code are data consumers. They modify schemas without knowing who depends on what. Tessera gives them the same guardrails humans get: register dependencies, check contracts before making changes, and participate in the proposal workflow when changes are breaking.

## The problem

Without a contract layer, an AI agent can:

- Drop a column that three downstream teams depend on
- Change a field type that breaks a consumer's parser
- Use stale or deprecated data for a high-stakes decision
- Silently introduce breaking changes that surface days later

Tessera prevents this by making the agent a participant in the coordination workflow, not a bystander.

## How it works

Agents interact with Tessera through the same REST API that human-facing tools use. The workflow has three parts:

1. **Register as a consumer** of the assets your agent reads
2. **Check contracts** before modifying schemas
3. **Respond to proposals** when upstream producers make breaking changes

```
Agent: "I want to add a required field to dim_customers"
    |
Tessera API: "That's a breaking change. 2 teams consume this asset."
    |
Agent: "Creating a proposal instead of publishing directly."
    |
Consumers: "Acknowledged."
    |
Agent: "Publishing v2.0.0."
```

## Getting started

### 1. Create an API key

Create an API key scoped to the assets your agent will interact with:

```bash
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ml-pipeline-agent",
    "scope": "write",
    "team_id": "your-team-uuid"
  }'
```

Store the returned key securely. Your agent will pass it as a `Bearer` token in the `Authorization` header.

### 2. Register as a consumer

Before your agent reads from a data asset, register the dependency so Tessera knows to notify you of upstream changes:

```python
import httpx

TESSERA_URL = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer <your-api-key>"}

# Register as a consumer of dim_customers
response = httpx.post(
    f"{TESSERA_URL}/api/v1/registrations",
    headers=HEADERS,
    json={
        "asset_id": "dim-customers-uuid",
        "consumer_team_id": "your-team-uuid",
        "dependency_type": "CONSUMES",
        "purpose": "ML pipeline reads customer features for churn prediction"
    }
)
```

### 3. Check before modifying

Before your agent publishes a schema change, check whether it's breaking:

```python
# Fetch the asset's current contract
asset = httpx.get(
    f"{TESSERA_URL}/api/v1/assets/dim-customers-uuid",
    headers=HEADERS
).json()

# Fetch registered consumers
registrations = httpx.get(
    f"{TESSERA_URL}/api/v1/registrations",
    headers=HEADERS,
    params={"asset_id": "dim-customers-uuid"}
).json()

# If consumers exist, publish the new contract and let Tessera
# handle the coordination — it will create a proposal if the
# change is breaking
response = httpx.post(
    f"{TESSERA_URL}/api/v1/assets/dim-customers-uuid/contracts",
    headers=HEADERS,
    params={"published_by": "your-team-uuid"},
    json={
        "schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "email": {"type": "string"},
                "lifetime_value": {"type": "number"}
            },
            "required": ["user_id"]
        },
        "compatibility_mode": "backward"
    }
)

result = response.json()
if result.get("proposal_id"):
    # Breaking change detected — a proposal was created
    # instead of publishing directly
    print(f"Proposal created: {result['proposal_id']}")
    print("Waiting for consumer acknowledgments before publishing.")
```

### 4. Respond to upstream proposals

When an upstream producer makes a breaking change, your agent's team will have a pending proposal. The agent can check for and respond to these:

```python
# Check for pending proposals affecting your team
proposals = httpx.get(
    f"{TESSERA_URL}/api/v1/proposals",
    headers=HEADERS,
    params={"status": "pending"}
).json()

for proposal in proposals:
    # Evaluate whether the breaking change affects your agent's workflow
    # Then acknowledge
    httpx.post(
        f"{TESSERA_URL}/api/v1/proposals/{proposal['id']}/acknowledgments",
        headers=HEADERS,
        json={
            "team_id": "your-team-uuid",
            "response": "APPROVED",
            "comment": "ML pipeline updated to handle schema change"
        }
    )
```

## Use cases

### Data pipeline agents

Agents that build or modify dbt models should register as consumers of their upstream sources and check contracts before altering schemas. Use the [dbt sync endpoints](dbt-integration.md) to run impact analysis before applying changes:

```python
import json

with open("target/manifest.json") as f:
    manifest = json.load(f)

# Check impact before syncing
impact = httpx.post(
    f"{TESSERA_URL}/api/v1/sync/dbt/impact",
    headers=HEADERS,
    json={
        "manifest": manifest,
        "owner_team_id": "your-team-uuid"
    }
).json()

if impact["breaking_changes_count"] > 0:
    print(f"Breaking changes detected in {impact['breaking_changes_count']} models")
    for result in impact["results"]:
        if not result["safe_to_publish"]:
            print(f"  {result['fqn']}: {result['breaking_changes']}")
```

### RAG and analytics agents

Agents that query warehouse tables for retrieval-augmented generation or analytics should register as consumers so they're notified when upstream schemas change. This prevents the agent from silently using stale column names or deprecated fields.

### Code generation agents

Agents that generate API clients, data models, or type definitions from warehouse schemas should check contracts before regenerating. A contract change may require updating generated code across multiple repositories.

## Webhook integration

For agents that need real-time notifications, configure a [webhook](../api/webhooks.md) to receive events when contracts change or proposals are created:

```bash
curl -X POST http://localhost:8000/api/v1/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -d '{
    "url": "https://your-agent-endpoint.example.com/tessera-events",
    "secret": "your-webhook-secret",
    "events": ["contract.published", "proposal.created", "proposal.resolved"]
  }'
```

Your agent can then react to schema changes as they happen rather than polling.

## What's next

We're building first-class AI agent support into Tessera, including:

- **Impact preview endpoint** — a single API call that answers "what would break if I made this change?" with affected consumers, downstream lineage, and migration suggestions
- **Agent identity on API keys** — distinguish agent actions from human actions in the audit trail
- **MCP tool server** — expose Tessera's capabilities as [Model Context Protocol](https://modelcontextprotocol.io) tools so agents can discover Tessera without hand-wiring HTTP clients
- **Semantic metadata** — field-level descriptions and business glossary references so agents can reason about what data means, not just its type

See [ADR-001: AI Enablement](../adrs/001-ai-enablement.md) for the full design.
