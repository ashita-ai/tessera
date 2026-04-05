# Assets API

Manage data assets in Tessera.

## List Assets

```http
GET /api/v1/assets
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `owner` | uuid | Filter by owner team ID |
| `owner_user` | uuid | Filter by owner user ID |
| `unowned` | bool | Filter to assets without a user owner (default: false) |
| `fqn` | string | Filter by FQN pattern (case-insensitive substring match) |
| `environment` | string | Filter by environment |
| `resource_type` | string | Filter by resource type |
| `sort_by` | string | Sort by field (`fqn`, `owner`, `owner_user`, `created_at`) |
| `sort_order` | string | Sort order: `asc` (default) or `desc` |
| `limit` | int | Results per page (default: 50, max: 100) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "asset-uuid",
      "fqn": "warehouse.analytics.users",
      "owner_team_id": "team-uuid",
      "owner_team_name": "Data Platform",
      "owner_user_id": "user-uuid",
      "owner_user_name": "John Doe",
      "owner_user_email": "john@example.com",
      "environment": "production",
      "resource_type": "model",
      "guarantee_mode": "notify",
      "semver_mode": "auto",
      "metadata": {},
      "tags": ["pii", "core"],
      "created_at": "2025-01-15T10:00:00Z",
      "active_contract_version": "1.2.0"
    }
  ],
  "total": 50,
  "limit": 50,
  "offset": 0
}
```

## Search Assets

```http
GET /api/v1/assets/search
```

Full-text search for assets by FQN (case-insensitive substring match).

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | **Required.** Search query (1-100 characters) |
| `owner` | uuid | Filter by owner team ID |
| `environment` | string | Filter by environment |
| `limit` | int | Results per page (default: 50, max: 100) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "asset-uuid",
      "fqn": "warehouse.analytics.users",
      "owner_team_id": "team-uuid",
      "owner_team_name": "Data Platform",
      "environment": "production"
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

## Get Asset

```http
GET /api/v1/assets/{asset_id}
```

Returns an asset with owner team/user names. Requires read scope.

### Response

```json
{
  "id": "asset-uuid",
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "owner_team_name": "Data Platform",
  "owner_user_id": "user-uuid",
  "owner_user_name": "John Doe",
  "owner_user_email": "john@example.com",
  "environment": "production",
  "resource_type": "model",
  "guarantee_mode": "notify",
  "semver_mode": "auto",
  "metadata": {
    "description": "Core users table"
  },
  "tags": ["pii", "core"],
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z"
}
```

## Create Asset

```http
POST /api/v1/assets
```

Requires write scope. Resource-level auth: must own the target team or use an admin key.

### Request Body

```json
{
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "owner_user_id": "user-uuid",
  "environment": "production",
  "resource_type": "model",
  "guarantee_mode": "notify",
  "semver_mode": "auto",
  "metadata": {
    "description": "Core users table"
  },
  "tags": ["pii"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fqn` | string | Yes | Fully qualified name (dot-separated, e.g., `db.schema.table`) |
| `owner_team_id` | uuid | Yes | Owning team ID |
| `owner_user_id` | uuid | No | Owning user ID (must belong to owner team) |
| `environment` | string | No | Environment (default: `production`) |
| `resource_type` | string | No | Resource type (default: `other`) |
| `guarantee_mode` | string | No | Guarantee mode (default: `notify`) |
| `semver_mode` | string | No | Semver mode (default: `auto`) |
| `metadata` | object | No | Arbitrary key-value metadata |
| `tags` | string[] | No | Free-form labels |

### Response (201 Created)

```json
{
  "id": "new-asset-uuid",
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "owner_user_id": "user-uuid",
  "environment": "production",
  "resource_type": "model",
  "guarantee_mode": "notify",
  "semver_mode": "auto",
  "metadata": {},
  "tags": ["pii"],
  "created_at": "2025-01-15T10:00:00Z"
}
```

## Update Asset

```http
PATCH /api/v1/assets/{asset_id}
```

Requires write scope. Resource-level auth: must own the asset's team or use an admin key. All fields are optional; only provided fields are updated.

### Request Body

```json
{
  "owner_user_id": "new-user-uuid",
  "metadata": {
    "description": "Updated description"
  },
  "tags": ["pii", "financial"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `fqn` | string | Updated FQN |
| `owner_team_id` | uuid | New owner team |
| `owner_user_id` | uuid | New owner user (must belong to owner team) |
| `environment` | string | Updated environment |
| `resource_type` | string | Updated resource type |
| `guarantee_mode` | string | Updated guarantee mode |
| `semver_mode` | string | Updated semver mode |
| `metadata` | object | Updated metadata |
| `tags` | string[] | Updated tags |

## Delete Asset

```http
DELETE /api/v1/assets/{asset_id}
```

Soft deletes an asset. Requires write scope. Resource-level auth: must own the asset's team or use an admin key.

Returns `204 No Content` on success.

## Restore Asset

```http
POST /api/v1/assets/{asset_id}/restore
```

Restores a soft-deleted asset. Requires admin scope.

### Response

Returns the restored asset (same shape as Create Asset response).

## Bulk Assign Owner

```http
POST /api/v1/assets/bulk-assign
```

Bulk assign or unassign a user owner for multiple assets. Requires admin scope.

### Request Body

```json
{
  "asset_ids": ["asset-uuid-1", "asset-uuid-2"],
  "owner_user_id": "user-uuid"
}
```

Set `owner_user_id` to `null` to unassign user ownership.

### Response

```json
{
  "updated": 2,
  "not_found": [],
  "owner_user_id": "user-uuid"
}
```

## Get Asset Contracts

```http
GET /api/v1/assets/{asset_id}/contracts
```

Returns all contracts (active, deprecated, archived) for the asset with publisher info.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Results per page (default: 50, max: 100) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "contract-uuid",
      "asset_id": "asset-uuid",
      "version": "1.2.0",
      "status": "active",
      "compatibility_mode": "backward",
      "published_at": "2025-01-15T10:00:00Z",
      "published_by": "team-uuid",
      "published_by_team_name": "Data Platform",
      "published_by_user_name": "John Doe"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

## Publish Contract

```http
POST /api/v1/assets/{asset_id}/contracts
```

### Request Body

```json
{
  "schema": {
    "type": "object",
    "properties": {
      "id": {"type": "integer"},
      "name": {"type": "string"}
    },
    "required": ["id"]
  },
  "compatibility_mode": "backward",
  "guarantees": {
    "freshness": {
      "max_staleness_minutes": 60
    }
  }
}
```

### Response (Non-breaking)

```json
{
  "action": "published",
  "contract": {
    "id": "contract-uuid",
    "version": "1.1.0",
    "status": "active"
  },
  "change_type": "minor",
  "breaking_changes": []
}
```

### Response (Breaking)

```json
{
  "action": "proposal.created",
  "proposal": {
    "id": "proposal-uuid",
    "status": "pending"
  },
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "properties.email"
    }
  ]
}
```

## Contract History

```http
GET /api/v1/assets/{asset_id}/contracts/history
```

Get the complete contract version history for an asset with change type annotations.

### Response

```json
{
  "asset_id": "uuid",
  "asset_fqn": "warehouse.schema.table",
  "contracts": [
    {
      "id": "uuid",
      "version": "2.0.0",
      "status": "active",
      "published_at": "2024-02-01T00:00:00Z",
      "published_by": "uuid",
      "compatibility_mode": "backward",
      "change_type": "major",
      "breaking_changes_count": 1
    }
  ]
}
```

## Contract Diff

```http
GET /api/v1/assets/{asset_id}/contracts/diff?from_version=1.0.0&to_version=2.0.0
```

Compare two contract versions for the same asset. Returns the schema diff between `from_version` and `to_version`.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from_version` | string | Yes | Base version (e.g., `1.0.0`) |
| `to_version` | string | Yes | Target version (e.g., `2.0.0`) |

### Response

```json
{
  "asset_id": "uuid",
  "asset_fqn": "warehouse.schema.table",
  "from_version": "1.0.0",
  "to_version": "2.0.0",
  "change_type": "major",
  "is_compatible": false,
  "breaking_changes": [...],
  "all_changes": [...],
  "compatibility_mode": "backward"
}
```

## Version Suggestion

```http
POST /api/v1/assets/{asset_id}/version-suggestion
```

Preview what version would be suggested for a new schema without actually publishing. Useful for CI dry-run checks. Requires read scope.

### Request Body

```json
{
  "schema": {
    "type": "object",
    "properties": {
      "id": {"type": "integer"},
      "name": {"type": "string"}
    }
  },
  "schema_format": "json_schema"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema` | object | Yes | JSON Schema or Avro schema definition |
| `schema_format` | string | No | `json_schema` (default) or `avro` |

### Response

```json
{
  "suggested_version": "2.0.0",
  "current_version": "1.5.0",
  "change_type": "major",
  "reason": "Breaking changes detected: 1 incompatible modification(s)",
  "is_first_contract": false,
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "properties.email"
    }
  ]
}
```
