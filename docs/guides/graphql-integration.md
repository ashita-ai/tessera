# GraphQL Integration

Tessera can import contracts from GraphQL schemas via introspection, creating assets for each query and mutation.

## Overview

The integration:

1. Parses a GraphQL introspection response
2. Creates assets for each query and mutation
3. Extracts argument and return type schemas as contracts
4. Tracks schema changes across versions

## Endpoint

**POST /api/v1/sync/graphql**

Requires `admin` scope.

## Request

```json
{
  "introspection": { /* GraphQL introspection response */ },
  "schema_name": "My GraphQL API",
  "owner_team_id": "uuid",
  "environment": "production",
  "auto_publish_contracts": true,
  "dry_run": false
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `introspection` | object | required | GraphQL introspection response (`__schema` or `data.__schema`) |
| `schema_name` | string | `"GraphQL API"` | Name for the schema (used in FQN generation) |
| `owner_team_id` | UUID | required | Team that will own the imported assets |
| `environment` | string | `"production"` | Environment for assets |
| `auto_publish_contracts` | boolean | `true` | Automatically publish contracts for new assets |
| `dry_run` | boolean | `false` | Preview changes without creating assets |

## Response

```json
{
  "schema_name": "My GraphQL API",
  "operations_found": 12,
  "assets_created": 8,
  "assets_updated": 4,
  "assets_skipped": 0,
  "contracts_published": 8,
  "operations": [
    {
      "fqn": "graphql.production.my_graphql_api.query.users",
      "operation_name": "users",
      "operation_type": "query",
      "action": "created",
      "asset_id": "uuid",
      "contract_id": "uuid"
    }
  ],
  "parse_errors": []
}
```

## Getting the Introspection Response

Run the standard introspection query against your GraphQL endpoint:

```graphql
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind name description
      fields {
        name description
        args { name type { ...TypeRef } }
        type { ...TypeRef }
      }
      inputFields { name type { ...TypeRef } }
      enumValues { name description }
      possibleTypes { name }
    }
  }
}

fragment TypeRef on __Type {
  kind name
  ofType {
    kind name
    ofType {
      kind name
      ofType { kind name }
    }
  }
}
```

Save the response and use it with Tessera:

```bash
# Get introspection from your GraphQL endpoint
curl -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { queryType { name } mutationType { name } types { kind name fields { name args { name type { kind name ofType { kind name } } } type { kind name ofType { kind name } } } } } }"}' \
  > introspection.json
```

## Quick Start

```bash
# Import from GraphQL introspection
curl -X POST http://localhost:8000/api/v1/sync/graphql \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"introspection\": $(cat introspection.json),
    \"schema_name\": \"Users API\",
    \"owner_team_id\": \"$TEAM_ID\",
    \"auto_publish_contracts\": true
  }"
```

## Dry Run

Preview what would be imported without creating assets:

```bash
curl -X POST http://localhost:8000/api/v1/sync/graphql \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"introspection\": $(cat introspection.json),
    \"schema_name\": \"Users API\",
    \"owner_team_id\": \"$TEAM_ID\",
    \"dry_run\": true
  }"
```

## What Gets Imported

### Asset FQN Format

Each query/mutation becomes an asset with FQN:

```
graphql.{environment}.{schema_name}.{type}.{operation_name}
```

Examples:
- `graphql.production.users_api.query.users`
- `graphql.production.users_api.query.user`
- `graphql.production.users_api.mutation.createUser`
- `graphql.staging.orders_api.mutation.cancelOrder`

### Contract Schema

The contract schema captures arguments and return types:

```json
{
  "type": "object",
  "properties": {
    "arguments": {
      "type": "object",
      "properties": {
        "id": { "type": "string" },
        "limit": { "type": "integer" }
      },
      "required": ["id"]
    },
    "return_type": {
      "type": "object",
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" },
        "email": { "type": "string" }
      }
    }
  }
}
```

### Resource Type

All imported assets have `resource_type: "graphql_query"`.

## Python SDK

```python
from tessera_sdk import TesseraClient
import json

client = TesseraClient(base_url="http://localhost:8000")

# Load introspection response
with open("introspection.json") as f:
    introspection = json.load(f)

# Import to Tessera
result = client.sync.graphql(
    introspection=introspection,
    schema_name="Users API",
    owner_team_id="your-team-uuid",
    auto_publish_contracts=True
)

print(f"Created {result.assets_created} assets")
print(f"Published {result.contracts_published} contracts")
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Sync GraphQL Schema to Tessera

on:
  push:
    branches: [main]
    paths:
      - 'schema.graphql'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get introspection
        run: |
          curl -X POST ${{ secrets.GRAPHQL_ENDPOINT }} \
            -H "Content-Type: application/json" \
            -d '{"query": "{ __schema { queryType { name } mutationType { name } types { kind name fields { name args { name type { kind name ofType { kind name } } } type { kind name ofType { kind name } } } } } }"}' \
            > introspection.json

      - name: Sync to Tessera
        run: |
          curl -X POST ${{ secrets.TESSERA_URL }}/api/v1/sync/graphql \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"introspection\": $(cat introspection.json),
              \"schema_name\": \"My API\",
              \"owner_team_id\": \"${{ secrets.TESSERA_TEAM_ID }}\",
              \"auto_publish_contracts\": true
            }"
```

## Limitations

- Only queries and mutations are imported (subscriptions are not yet supported)
- The introspection must include type details (not just type names)
- No dedicated impact/diff endpoints yet (use `dry_run: true` to preview)
