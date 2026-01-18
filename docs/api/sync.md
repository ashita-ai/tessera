# Sync API

Import schemas from external sources: dbt, OpenAPI, and GraphQL.

## dbt Sync

### Upload Manifest

```http
POST /api/v1/sync/dbt/upload
```

Full manifest sync with automation options.

#### Request Body

```json
{
  "manifest": { /* manifest.json contents */ },
  "owner_team_id": "uuid",
  "conflict_mode": "overwrite",
  "auto_publish_contracts": true,
  "auto_create_proposals": true,
  "auto_register_consumers": true,
  "infer_consumers_from_refs": true,
  "auto_delete": false
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `manifest` | object | required | Contents of manifest.json |
| `owner_team_id` | UUID | required | Default team for new assets |
| `conflict_mode` | string | `"ignore"` | How to handle existing assets |
| `auto_publish_contracts` | boolean | `false` | Auto-publish contracts |
| `auto_create_proposals` | boolean | `false` | Create proposals for breaking changes |
| `auto_register_consumers` | boolean | `false` | Register consumers from meta |
| `infer_consumers_from_refs` | boolean | `false` | Infer consumers from ref() |
| `auto_delete` | boolean | `false` | Soft-delete dbt-managed assets missing from manifest |

#### Response

```json
{
  "status": "success",
  "assets": { "created": 10, "updated": 5, "skipped": 2, "deleted": 1, "deleted_fqns": ["db.schema.old_model"] },
  "contracts": { "published": 8 },
  "proposals": { "created": 2 },
  "registrations": { "created": 15 }
}
```

### Legacy Sync

```http
POST /api/v1/sync/dbt
```

Simple manifest upload (backwards compatibility).

### Impact Analysis

```http
POST /api/v1/sync/dbt/impact
```

Preview impact without applying changes.

### Diff

```http
POST /api/v1/sync/dbt/diff
```

Dry-run for CI/CD pipelines. Detects:
- New models (not in Tessera)
- Modified models (schema changes)
- Deleted models (in Tessera but missing from manifest)
- Breaking changes

Response includes `summary.deleted` count and models with `change_type: "deleted"`.

See [dbt Integration Guide](../guides/dbt-integration.md) for full documentation.

---

## OpenAPI Sync

Import API schemas from OpenAPI specifications.

### Import Spec

```http
POST /api/v1/sync/openapi
```

#### Request Body

```json
{
  "spec": { /* OpenAPI 3.x spec */ },
  "owner_team_id": "uuid",
  "environment": "production",
  "auto_publish_contracts": true,
  "dry_run": false,
  "default_guarantees": {
    "freshness": { "max_staleness_minutes": 60 }
  }
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `spec` | object | required | OpenAPI 3.x specification |
| `owner_team_id` | UUID | required | Team to own created assets |
| `environment` | string | `"production"` | Environment for assets |
| `auto_publish_contracts` | boolean | `true` | Auto-publish contracts for new assets |
| `dry_run` | boolean | `false` | Preview changes without persisting |
| `default_guarantees` | object | `null` | Default guarantees to apply to all endpoints |

#### Response

```json
{
  "api_title": "Users API",
  "api_version": "1.0.0",
  "endpoints_found": 18,
  "assets_created": 15,
  "assets_updated": 3,
  "assets_skipped": 0,
  "contracts_published": 15,
  "endpoints": [
    {
      "fqn": "api.users_api.get_users_id",
      "path": "/users/{id}",
      "method": "GET",
      "action": "created",
      "asset_id": "uuid",
      "contract_id": "uuid"
    }
  ],
  "parse_errors": []
}
```

### Impact Analysis

```http
POST /api/v1/sync/openapi/impact
```

Check what would change against existing contracts.

#### Request Body

```json
{
  "spec": { /* OpenAPI 3.x spec */ },
  "environment": "production"
}
```

#### Response

```json
{
  "status": "success",
  "api_title": "Users API",
  "api_version": "1.0.0",
  "total_endpoints": 10,
  "endpoints_with_contracts": 8,
  "breaking_changes_count": 2,
  "results": [
    {
      "fqn": "api.users_api.get_users_id",
      "path": "/users/{id}",
      "method": "GET",
      "has_contract": true,
      "safe_to_publish": false,
      "change_type": "major",
      "breaking_changes": [
        { "type": "property_removed", "path": "$.response.email" }
      ]
    }
  ],
  "parse_errors": []
}
```

### Diff (CI/CD)

```http
POST /api/v1/sync/openapi/diff
```

Dry-run for CI pipelines with blocking support.

#### Request Body

```json
{
  "spec": { /* OpenAPI 3.x spec */ },
  "environment": "production",
  "fail_on_breaking": true
}
```

#### Response

```json
{
  "status": "breaking_changes_detected",
  "api_title": "Users API",
  "api_version": "1.0.0",
  "summary": { "new": 2, "modified": 3, "unchanged": 5, "breaking": 1 },
  "blocking": true,
  "endpoints": [
    {
      "fqn": "api.users_api.get_users_id",
      "path": "/users/{id}",
      "method": "GET",
      "change_type": "modified",
      "has_schema": true,
      "schema_change_type": "breaking",
      "breaking_changes": []
    }
  ],
  "parse_errors": []
}
```

### What Gets Synced

For each OpenAPI path/operation:

- Creates an asset with FQN: `api.<api_title>.<method>_<path>`
- Extracts request/response schemas
- Converts to JSON Schema for contracts

Example:

```yaml
# OpenAPI spec with title "Users API"
paths:
  /users/{id}:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
```

Becomes asset: `api.users_api.get_users_id`

---

## GraphQL Sync

Import operations from GraphQL introspection responses.

### Import Schema

```http
POST /api/v1/sync/graphql
```

#### Request Body

```json
{
  "introspection": { /* GraphQL introspection response */ },
  "schema_name": "Users API",
  "owner_team_id": "uuid",
  "environment": "production",
  "auto_publish_contracts": true,
  "dry_run": false,
  "default_guarantees": null
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `introspection` | object | required | GraphQL introspection response (`__schema` or `data.__schema`) |
| `schema_name` | string | `"GraphQL API"` | Name for the schema (used in FQN generation) |
| `owner_team_id` | UUID | required | Team to own created assets |
| `environment` | string | `"production"` | Environment for assets |
| `auto_publish_contracts` | boolean | `true` | Auto-publish contracts for new assets |
| `dry_run` | boolean | `false` | Preview changes without persisting |
| `default_guarantees` | object | `null` | Default guarantees to apply to all operations |

To get an introspection response, run the standard introspection query:

```graphql
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind name description
      fields { name description args { name type { ...TypeRef } } type { ...TypeRef } }
      inputFields { name type { ...TypeRef } }
      enumValues { name description }
    }
  }
}

fragment TypeRef on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name } } }
}
```

#### Response

```json
{
  "schema_name": "Users API",
  "operations_found": 10,
  "assets_created": 8,
  "assets_updated": 2,
  "assets_skipped": 0,
  "contracts_published": 8,
  "operations": [
    {
      "fqn": "graphql.users_api.query_get_user",
      "operation_name": "getUser",
      "operation_type": "query",
      "action": "created",
      "asset_id": "uuid",
      "contract_id": "uuid"
    }
  ],
  "parse_errors": []
}
```

### Impact Analysis

```http
POST /api/v1/sync/graphql/impact
```

Check what would change against existing contracts.

#### Request Body

```json
{
  "introspection": { /* GraphQL introspection response */ },
  "schema_name": "Users API",
  "environment": "production"
}
```

#### Response

```json
{
  "status": "success",
  "schema_name": "Users API",
  "total_operations": 10,
  "operations_with_contracts": 8,
  "breaking_changes_count": 0,
  "results": [
    {
      "fqn": "graphql.users_api.query_get_user",
      "operation_name": "getUser",
      "operation_type": "query",
      "has_contract": true,
      "safe_to_publish": true,
      "change_type": "none",
      "breaking_changes": []
    }
  ],
  "parse_errors": []
}
```

### Diff (CI/CD)

```http
POST /api/v1/sync/graphql/diff
```

Dry-run for CI pipelines with blocking support.

#### Request Body

```json
{
  "introspection": { /* GraphQL introspection response */ },
  "schema_name": "Users API",
  "environment": "production",
  "fail_on_breaking": true
}
```

#### Response

```json
{
  "status": "clean",
  "schema_name": "Users API",
  "summary": { "new": 0, "modified": 1, "unchanged": 9, "breaking": 0 },
  "blocking": false,
  "operations": [
    {
      "fqn": "graphql.users_api.query_get_user",
      "operation_name": "getUser",
      "operation_type": "query",
      "change_type": "unchanged",
      "has_schema": true,
      "schema_change_type": "none",
      "breaking_changes": []
    }
  ],
  "parse_errors": []
}
```

### What Gets Synced

For each GraphQL query/mutation:

- Creates an asset with FQN: `graphql.<schema_name>.<type>_<operation_name>`
- Extracts argument and return type schemas
- Converts to JSON Schema for contracts

Example:

```graphql
# Schema named "Users API"
type Query {
  getUser(id: ID!): User
  listUsers(limit: Int): [User!]!
}

type Mutation {
  createUser(input: CreateUserInput!): User!
}
```

Becomes:
- `graphql.users_api.query_get_user`
- `graphql.users_api.query_list_users`
- `graphql.users_api.mutation_create_user`

---

## Conflict Modes

The dbt sync endpoints support `conflict_mode`:

| Mode | Behavior |
|------|----------|
| `ignore` | Skip existing assets (default, safe) |
| `overwrite` | Update existing assets |
| `fail` | Error if any asset exists |

OpenAPI and GraphQL endpoints handle existing assets by updating metadata (no skip/fail modes).
