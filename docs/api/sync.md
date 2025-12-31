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

### Upload Spec

```http
POST /api/v1/sync/openapi
```

#### Request Body

```json
{
  "spec": { /* OpenAPI 3.x spec */ },
  "owner_team_id": "uuid",
  "prefix": "api",
  "auto_publish_contracts": true
}
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `spec` | object | required | OpenAPI 3.x specification |
| `owner_team_id` | UUID | required | Team to own created assets |
| `prefix` | string | `"api"` | Prefix for asset FQNs |
| `auto_publish_contracts` | boolean | `false` | Auto-publish contracts |

#### Response

```json
{
  "status": "success",
  "assets": { "created": 15, "updated": 3 },
  "contracts": { "published": 12 },
  "endpoints_processed": 18
}
```

### Impact Analysis

```http
POST /api/v1/sync/openapi/impact
```

Preview what would change.

### Diff

```http
POST /api/v1/sync/openapi/diff
```

CI/CD dry-run.

### What Gets Synced

For each OpenAPI path/operation:

- Creates an asset with FQN: `{prefix}.{path}.{method}`
- Extracts request/response schemas
- Converts to JSON Schema for contracts

Example:

```yaml
# OpenAPI
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

Becomes asset: `api.users.{id}.get`

---

## GraphQL Sync

Import types from GraphQL schemas.

### Upload Schema

```http
POST /api/v1/sync/graphql
```

#### Request Body

```json
{
  "schema": "type User { id: ID! name: String! }",
  "owner_team_id": "uuid",
  "prefix": "graphql",
  "auto_publish_contracts": true
}
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema` | string | required | GraphQL SDL |
| `owner_team_id` | UUID | required | Team to own created assets |
| `prefix` | string | `"graphql"` | Prefix for asset FQNs |
| `auto_publish_contracts` | boolean | `false` | Auto-publish contracts |

#### Response

```json
{
  "status": "success",
  "assets": { "created": 8, "updated": 2 },
  "contracts": { "published": 6 },
  "types_processed": 10
}
```

### Impact Analysis

```http
POST /api/v1/sync/graphql/impact
```

Preview what would change.

### Diff

```http
POST /api/v1/sync/graphql/diff
```

CI/CD dry-run.

### What Gets Synced

For each GraphQL type:

- Creates an asset with FQN: `{prefix}.{TypeName}`
- Converts GraphQL type to JSON Schema
- Handles: Object types, Input types, Enums

Example:

```graphql
type User {
  id: ID!
  name: String!
  email: String
  role: Role!
}

enum Role {
  ADMIN
  USER
}
```

Becomes:
- Asset: `graphql.User` with schema for User type
- Asset: `graphql.Role` with enum schema

---

## Conflict Modes

All sync endpoints support `conflict_mode`:

| Mode | Behavior |
|------|----------|
| `ignore` | Skip existing assets (default, safe) |
| `overwrite` | Update existing assets |
| `fail` | Error if any asset exists |
