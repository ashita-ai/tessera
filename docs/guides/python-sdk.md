# Python SDK

The official Python SDK for Tessera provides a type-safe client for interacting with the Tessera API.

**Repository:** [github.com/ashita-ai/tessera-python](https://github.com/ashita-ai/tessera-python)
**PyPI:** [pypi.org/project/tessera-sdk](https://pypi.org/project/tessera-sdk/)

## Installation

```bash
pip install tessera-sdk
```

Or with uv:

```bash
uv add tessera-sdk
```

**Note:** The package is installed as `tessera-sdk` but imported as `tessera_sdk`.

## Quick Start

```python
from tessera_sdk import TesseraClient

client = TesseraClient(base_url="http://localhost:8000")

# Create a team
team = client.teams.create(name="data-platform")

# Create an asset
asset = client.assets.create(
    fqn="warehouse.analytics.dim_customers",
    owner_team_id=team.id
)

# Publish a contract (JSON Schema - default for dbt models)
result = client.assets.publish_contract(
    asset_id=asset.id,
    schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"}
        }
    },
    version="1.0.0"
)

# Publish with explicit schema format (for non-dbt assets)
result = client.assets.publish_contract(
    asset_id=asset.id,
    schema={"type": "record", "name": "User", "fields": [...]},
    schema_format="avro",  # or "openapi", "graphql"
    version="1.0.0"
)
```

## Features

- **Sync and async clients** - Use `TesseraClient` or `AsyncTesseraClient`
- **Type-safe** - Full Pydantic model support with type hints
- **Error handling** - Typed exceptions for API errors
- **Flexible configuration** - Environment variables or explicit config

## Configuration

### Explicit URL

```python
client = TesseraClient(base_url="http://localhost:8000")
```

### Environment Variable

```python
# Uses TESSERA_URL or defaults to localhost:8000
client = TesseraClient()
```

### With Authentication

```python
client = TesseraClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
    timeout=30.0
)
```

## Resources

The client provides the following resource classes:

| Resource | Description |
|----------|-------------|
| `client.teams` | Team management |
| `client.assets` | Asset and contract management |
| `client.contracts` | Contract lookup and comparison |
| `client.registrations` | Consumer registration |
| `client.proposals` | Breaking change proposals |

## Async Support

For async applications, use `AsyncTesseraClient`:

```python
import asyncio
from tessera_sdk import AsyncTesseraClient

async def main():
    async with AsyncTesseraClient() as client:
        team = await client.teams.create(name="data-platform")
        print(f"Created team: {team.name}")

asyncio.run(main())
```

## Impact Analysis

Before making schema changes, check the impact on consumers:

```python
impact = client.assets.check_impact(
    asset_id=asset.id,
    proposed_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},  # Changed type!
            "name": {"type": "string"}
        }
    }
)

if not impact.safe_to_publish:
    print(f"Breaking changes detected: {impact.breaking_changes}")
    print(f"Affected consumers: {impact.affected_consumers}")
```

## Error Handling

The SDK provides typed exceptions for different error scenarios:

```python
from tessera_sdk import TesseraClient, NotFoundError, ValidationError

client = TesseraClient()

try:
    team = client.teams.get("non-existent-id")
except NotFoundError:
    print("Team not found")
except ValidationError as e:
    print(f"Validation error: {e.message}")
```

## Airflow Integration

Use the SDK in Airflow DAGs for CI/CD contract validation:

```python
from airflow.decorators import task
from tessera_sdk import TesseraClient

@task
def validate_schema():
    client = TesseraClient()
    impact = client.assets.check_impact(
        asset_id="your-asset-id",
        proposed_schema=load_schema("./schema.json")
    )
    if not impact.safe_to_publish:
        raise ValueError(f"Breaking changes: {impact.breaking_changes}")

@task
def publish_contract():
    client = TesseraClient()
    client.assets.publish_contract(
        asset_id="your-asset-id",
        schema=load_schema("./schema.json"),
        version=get_version()
    )
```

## dbt Integration

Combine the SDK with dbt for schema extraction:

```python
import json
from tessera_sdk import TesseraClient

# Load dbt manifest
with open("target/manifest.json") as f:
    manifest = json.load(f)

client = TesseraClient()

# Sync models as contracts
for node_id, node in manifest["nodes"].items():
    if node["resource_type"] == "model":
        # Extract schema from dbt metadata
        schema = extract_schema_from_node(node)

        # Publish to Tessera
        client.assets.publish_contract(
            asset_id=find_or_create_asset(node["unique_id"]),
            schema=schema,
            version=node.get("version", "1.0.0")
        )
```

!!! tip "Use the built-in dbt sync endpoint"
    For most use cases, the `/sync/dbt` endpoint is easier than manual integration.
    See the [dbt Integration](./dbt-integration.md) guide for details.

## Requirements

- Python 3.10+
- httpx >= 0.25.0
- pydantic >= 2.0.0

## Related

- [SDK Repository](https://github.com/ashita-ai/tessera-python)
- [PyPI Package](https://pypi.org/project/tessera-sdk/)
- [API Reference](../api/overview.md)
