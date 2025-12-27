# OpenAPI Integration

Tessera can import API contracts from OpenAPI 3.x specifications. Each endpoint in your OpenAPI spec becomes a Tessera asset with a contract.

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/sync/openapi` | POST | Import assets from OpenAPI spec |
| `/api/v1/sync/openapi/impact` | POST | Check impact of spec changes |
| `/api/v1/sync/openapi/diff` | POST | Preview changes (CI/CD dry-run) |

## Import OpenAPI Spec

Import your OpenAPI specification to create assets and contracts:

```bash
curl -X POST "$TESSERA_URL/api/v1/sync/openapi" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "spec": '"$(cat openapi.json)"',
    "owner_team_id": "your-team-uuid",
    "auto_publish_contracts": true,
    "dry_run": false
  }'
```

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spec` | object | Yes | OpenAPI 3.x specification as JSON |
| `owner_team_id` | UUID | Yes | Team that will own the imported assets |
| `environment` | string | No | Environment for assets (default: "production") |
| `auto_publish_contracts` | boolean | No | Auto-publish contracts for new assets (default: true) |
| `dry_run` | boolean | No | Preview changes without persisting (default: false) |

### Response

```json
{
  "api_title": "My API",
  "api_version": "1.0.0",
  "endpoints_found": 5,
  "assets_created": 3,
  "assets_updated": 2,
  "assets_skipped": 0,
  "contracts_published": 3,
  "endpoints": [
    {
      "fqn": "api.my_api.get_users",
      "path": "/users",
      "method": "GET",
      "action": "created",
      "asset_id": "...",
      "contract_id": "..."
    }
  ],
  "parse_errors": []
}
```

## Impact Analysis

Check the impact of schema changes before deploying:

```bash
curl -X POST "$TESSERA_URL/api/v1/sync/openapi/impact" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "spec": '"$(cat openapi.json)"',
    "environment": "production"
  }'
```

### Response

```json
{
  "status": "success",
  "api_title": "My API",
  "api_version": "1.0.0",
  "total_endpoints": 5,
  "endpoints_with_contracts": 3,
  "breaking_changes_count": 0,
  "results": [
    {
      "fqn": "api.my_api.get_users",
      "path": "/users",
      "method": "GET",
      "has_contract": true,
      "safe_to_publish": true,
      "change_type": "none",
      "breaking_changes": []
    }
  ]
}
```

Status values:
- `success`: No breaking changes detected
- `breaking_changes_detected`: Breaking changes found

## Diff (CI/CD Integration)

Preview what would change before applying. Ideal for CI/CD pipelines:

```bash
curl -X POST "$TESSERA_URL/api/v1/sync/openapi/diff" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "spec": '"$(cat openapi.json)"',
    "environment": "production",
    "fail_on_breaking": true
  }'
```

### Response

```json
{
  "status": "changes_detected",
  "api_title": "My API",
  "api_version": "2.0.0",
  "summary": {
    "new": 1,
    "modified": 2,
    "unchanged": 2,
    "breaking": 0
  },
  "blocking": false,
  "endpoints": [
    {
      "fqn": "api.my_api.get_users",
      "path": "/users",
      "method": "GET",
      "change_type": "unchanged",
      "schema_change_type": "none",
      "breaking_changes": []
    }
  ]
}
```

### CI/CD Example

```yaml
# GitHub Actions
- name: Check API Contract Impact
  run: |
    RESPONSE=$(curl -s -X POST "$TESSERA_URL/api/v1/sync/openapi/diff" \
      -H "Authorization: Bearer $TESSERA_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"spec": '"$(cat openapi.json)"', "fail_on_breaking": true}')

    BLOCKING=$(echo "$RESPONSE" | jq -r '.blocking')
    if [ "$BLOCKING" = "true" ]; then
      echo "Breaking changes detected!"
      echo "$RESPONSE" | jq '.endpoints[] | select(.schema_change_type == "breaking")'
      exit 1
    fi
```

## FQN Format

Assets are named using this format:
```
api.<api_title>.<method>_<path>
```

Examples:
- `api.my_api.get_users` (GET /users)
- `api.my_api.post_users_id` (POST /users/{id})

## Schema Extraction

Tessera extracts schemas from:

1. **Request body**: From `requestBody.content.application/json.schema`
2. **Response**: From `responses.200.content.application/json.schema` (or 201, default)

The combined schema becomes:
```json
{
  "type": "object",
  "properties": {
    "request": { ... },
    "response": { ... }
  }
}
```
