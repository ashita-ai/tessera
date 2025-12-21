# Tessera SDK

Python SDK for [Tessera](https://github.com/ashita-ai/tessera) - Data contract coordination for warehouses.

## Installation

```bash
pip install tessera-sdk
```

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

# Publish a contract
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

# Check impact before making changes
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
```

## Async Support

```python
import asyncio
from tessera_sdk import AsyncTesseraClient

async def main():
    async with AsyncTesseraClient() as client:
        team = await client.teams.create(name="data-platform")
        print(f"Created team: {team.name}")

asyncio.run(main())
```

## Airflow Integration

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

## API Reference

### TesseraClient

The main client class with the following resources:

- `client.teams` - Team management
- `client.assets` - Asset and contract management
- `client.contracts` - Contract lookup and comparison
- `client.registrations` - Consumer registration
- `client.proposals` - Breaking change proposals

### Configuration

The client can be configured via:

```python
# Explicit URL
client = TesseraClient(base_url="http://localhost:8000")

# Environment variable (TESSERA_URL)
client = TesseraClient()  # Uses TESSERA_URL or defaults to localhost:8000

# Additional options
client = TesseraClient(
    base_url="http://localhost:8000",
    timeout=30.0,  # Request timeout in seconds
    headers={"Authorization": "Bearer token"}  # Custom headers
)
```

## Error Handling

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

## License

MIT
