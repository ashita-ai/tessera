# OpenAPI Integration

Tessera can import contracts from OpenAPI 3.x specifications, creating assets for each API endpoint.

## Overview

The integration:

1. Parses your OpenAPI spec (JSON or YAML converted to JSON)
2. Creates assets for each endpoint (method + path)
3. Extracts request/response schemas as contracts
4. Tracks schema changes across versions

## Endpoint

**POST /api/v1/sync/openapi**

Requires `admin` scope.

## Request

```json
{
  "spec": { /* OpenAPI 3.x specification */ },
  "owner_team_id": "uuid",
  "environment": "production",
  "auto_publish_contracts": true,
  "dry_run": false
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `spec` | object | required | OpenAPI 3.x specification as JSON |
| `owner_team_id` | UUID | required | Team that will own the imported assets |
| `environment` | string | `"production"` | Environment for assets |
| `auto_publish_contracts` | boolean | `true` | Automatically publish contracts for new assets |
| `dry_run` | boolean | `false` | Preview changes without creating assets |

## Response

```json
{
  "api_title": "My API",
  "api_version": "1.0.0",
  "endpoints_found": 15,
  "assets_created": 10,
  "assets_updated": 5,
  "assets_skipped": 0,
  "contracts_published": 10,
  "endpoints": [
    {
      "fqn": "api.production.GET./users",
      "path": "/users",
      "method": "GET",
      "action": "created",
      "asset_id": "uuid",
      "contract_id": "uuid"
    }
  ],
  "parse_errors": []
}
```

## Quick Start

```bash
# Import from OpenAPI spec
curl -X POST http://localhost:8000/api/v1/sync/openapi \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"spec\": $(cat openapi.json),
    \"owner_team_id\": \"$TEAM_ID\",
    \"auto_publish_contracts\": true
  }"
```

## Dry Run

Preview what would be imported without creating assets:

```bash
curl -X POST http://localhost:8000/api/v1/sync/openapi \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"spec\": $(cat openapi.json),
    \"owner_team_id\": \"$TEAM_ID\",
    \"dry_run\": true
  }"
```

The response will show `action: "would_create"` or `action: "would_update"` instead of actually making changes.

## What Gets Imported

### Asset FQN Format

Each endpoint becomes an asset with FQN:

```
api.{environment}.{METHOD}.{path}
```

Examples:
- `api.production.GET./users`
- `api.production.POST./users/{id}`
- `api.staging.DELETE./orders/{orderId}`

### Contract Schema

The contract schema combines request and response schemas:

```json
{
  "type": "object",
  "properties": {
    "request": {
      "parameters": { /* path, query, header params */ },
      "body": { /* request body schema */ }
    },
    "response": {
      "200": { /* success response schema */ },
      "400": { /* error response schema */ }
    }
  }
}
```

### Resource Type

All imported assets have `resource_type: "api_endpoint"`.

## Example OpenAPI Spec

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Users API",
    "version": "1.0.0"
  },
  "paths": {
    "/users": {
      "get": {
        "summary": "List users",
        "responses": {
          "200": {
            "description": "Success",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "id": { "type": "integer" },
                      "name": { "type": "string" },
                      "email": { "type": "string" }
                    },
                    "required": ["id", "name"]
                  }
                }
              }
            }
          }
        }
      },
      "post": {
        "summary": "Create user",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "name": { "type": "string" },
                  "email": { "type": "string" }
                },
                "required": ["name", "email"]
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Created"
          }
        }
      }
    }
  }
}
```

## Python SDK

```python
from tessera_sdk import TesseraClient
import json

client = TesseraClient(base_url="http://localhost:8000")

# Load OpenAPI spec
with open("openapi.json") as f:
    spec = json.load(f)

# Import to Tessera
result = client.sync.openapi(
    spec=spec,
    owner_team_id="your-team-uuid",
    auto_publish_contracts=True
)

print(f"Created {result.assets_created} assets")
print(f"Published {result.contracts_published} contracts")
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Sync OpenAPI to Tessera

on:
  push:
    branches: [main]
    paths:
      - 'openapi.json'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Sync to Tessera
        run: |
          curl -X POST ${{ secrets.TESSERA_URL }}/api/v1/sync/openapi \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"spec\": $(cat openapi.json),
              \"owner_team_id\": \"${{ secrets.TESSERA_TEAM_ID }}\",
              \"auto_publish_contracts\": true
            }"
```

## Limitations

- Only OpenAPI 3.x is supported (not Swagger 2.0)
- The spec must be provided as JSON (convert YAML first)
- No dedicated impact/diff endpoints yet (use `dry_run: true` to preview)
