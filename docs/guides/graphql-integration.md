# GraphQL Integration

Tessera can import API contracts from GraphQL schema introspection. Each query and mutation becomes a Tessera asset with a contract.

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/sync/graphql` | POST | Import assets from GraphQL introspection |
| `/api/v1/sync/graphql/impact` | POST | Check impact of schema changes |
| `/api/v1/sync/graphql/diff` | POST | Preview changes (CI/CD dry-run) |

## Getting Introspection Data

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
  ofType { kind name ofType { kind name ofType { kind name } } }
}
```

## Import GraphQL Schema

Import your GraphQL introspection to create assets and contracts:

```bash
# Get introspection
INTROSPECTION=$(curl -s "$GRAPHQL_URL" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { queryType { name } mutationType { name } types { kind name fields { name args { name type { kind name ofType { kind name } } } type { kind name ofType { kind name } } } } } }"}')

# Import to Tessera
curl -X POST "$TESSERA_URL/api/v1/sync/graphql" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"introspection\": $INTROSPECTION,
    \"owner_team_id\": \"your-team-uuid\",
    \"schema_name\": \"my-graphql-api\",
    \"auto_publish_contracts\": true
  }"
```

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `introspection` | object | Yes | GraphQL introspection response |
| `owner_team_id` | UUID | Yes | Team that will own the imported assets |
| `schema_name` | string | No | Name for the schema (default: "GraphQL API") |
| `environment` | string | No | Environment for assets (default: "production") |
| `auto_publish_contracts` | boolean | No | Auto-publish contracts (default: true) |
| `dry_run` | boolean | No | Preview changes without persisting (default: false) |

### Response

```json
{
  "schema_name": "my-graphql-api",
  "operations_found": 5,
  "assets_created": 4,
  "assets_updated": 1,
  "assets_skipped": 0,
  "contracts_published": 4,
  "operations": [
    {
      "fqn": "graphql.my_graphql_api.query_users",
      "operation_name": "users",
      "operation_type": "query",
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
curl -X POST "$TESSERA_URL/api/v1/sync/graphql/impact" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"introspection\": $INTROSPECTION,
    \"schema_name\": \"my-graphql-api\",
    \"environment\": \"production\"
  }"
```

### Response

```json
{
  "status": "success",
  "schema_name": "my-graphql-api",
  "total_operations": 5,
  "operations_with_contracts": 4,
  "breaking_changes_count": 0,
  "results": [
    {
      "fqn": "graphql.my_graphql_api.query_users",
      "operation_name": "users",
      "operation_type": "query",
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
curl -X POST "$TESSERA_URL/api/v1/sync/graphql/diff" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"introspection\": $INTROSPECTION,
    \"schema_name\": \"my-graphql-api\",
    \"fail_on_breaking\": true
  }"
```

### Response

```json
{
  "status": "changes_detected",
  "schema_name": "my-graphql-api",
  "summary": {
    "new": 1,
    "modified": 1,
    "unchanged": 3,
    "breaking": 0
  },
  "blocking": false,
  "operations": [
    {
      "fqn": "graphql.my_graphql_api.query_users",
      "operation_name": "users",
      "operation_type": "query",
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
- name: Check GraphQL Contract Impact
  run: |
    # Get introspection
    INTROSPECTION=$(curl -s "$GRAPHQL_URL" \
      -H "Content-Type: application/json" \
      -d '{"query": "{ __schema { ... } }"}')

    # Check for breaking changes
    RESPONSE=$(curl -s -X POST "$TESSERA_URL/api/v1/sync/graphql/diff" \
      -H "Authorization: Bearer $TESSERA_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"introspection\": $INTROSPECTION, \"schema_name\": \"my-api\", \"fail_on_breaking\": true}")

    BLOCKING=$(echo "$RESPONSE" | jq -r '.blocking')
    if [ "$BLOCKING" = "true" ]; then
      echo "Breaking changes detected!"
      echo "$RESPONSE" | jq '.operations[] | select(.schema_change_type == "breaking")'
      exit 1
    fi
```

## FQN Format

Assets are named using this format:
```
graphql.<schema_name>.<type>_<operation_name>
```

Examples:
- `graphql.my_api.query_users` (Query.users)
- `graphql.my_api.mutation_create_user` (Mutation.createUser)

## Schema Conversion

Tessera converts GraphQL types to JSON Schema:

| GraphQL Type | JSON Schema |
|--------------|-------------|
| `String` | `{"type": "string"}` |
| `Int` | `{"type": "integer"}` |
| `Float` | `{"type": "number"}` |
| `Boolean` | `{"type": "boolean"}` |
| `ID` | `{"type": "string"}` |
| `[Type]` | `{"type": "array", "items": {...}}` |
| `Type!` | Adds to `required` array |

The combined schema for each operation:
```json
{
  "type": "object",
  "properties": {
    "arguments": { ... },
    "response": { ... }
  }
}
```
