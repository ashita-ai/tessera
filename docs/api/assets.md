# Assets API

Manage data assets in Tessera.

## List Assets

```http
GET /api/v1/assets
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `fqn` | string | Filter by FQN (exact or prefix match) |
| `owner_team_id` | uuid | Filter by owner team |
| `environment` | string | Filter by environment |
| `page` | int | Page number (default: 1) |
| `page_size` | int | Results per page (default: 20, max: 100) |

### Response

```json
{
  "results": [
    {
      "id": "asset-uuid",
      "fqn": "warehouse.analytics.users",
      "owner_team_id": "team-uuid",
      "owner_team_name": "Data Platform",
      "environment": "production",
      "created_at": "2025-01-15T10:00:00Z",
      "active_contract_id": "contract-uuid",
      "active_contract_version": "1.2.0"
    }
  ],
  "total": 50,
  "page": 1,
  "page_size": 20
}
```

## Get Asset

```http
GET /api/v1/assets/{asset_id}
```

### Response

```json
{
  "id": "asset-uuid",
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "owner_team_name": "Data Platform",
  "owner_user_id": "user-uuid",
  "owner_user_name": "John Doe",
  "environment": "production",
  "metadata": {
    "resource_type": "model",
    "description": "Core users table",
    "tags": ["pii", "core"]
  },
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z"
}
```

## Create Asset

```http
POST /api/v1/assets
```

### Request Body

```json
{
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "environment": "production",
  "metadata": {
    "description": "Core users table",
    "tags": ["pii"]
  }
}
```

### Response

```json
{
  "id": "new-asset-uuid",
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "team-uuid",
  "environment": "production",
  "created_at": "2025-01-15T10:00:00Z"
}
```

## Update Asset

```http
PATCH /api/v1/assets/{asset_id}
```

### Request Body

```json
{
  "owner_user_id": "new-user-uuid",
  "metadata": {
    "description": "Updated description"
  }
}
```

## Delete Asset

```http
DELETE /api/v1/assets/{asset_id}
```

Returns `204 No Content` on success.

## Get Asset Contracts

```http
GET /api/v1/assets/{asset_id}/contracts
```

Returns all contracts (active, deprecated, archived) for the asset.

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
  "changes": [
    {
      "type": "property_added",
      "path": "$.properties.email"
    }
  ]
}
```

### Response (Breaking)

```json
{
  "action": "proposal_created",
  "proposal": {
    "id": "proposal-uuid",
    "status": "pending",
    "breaking_changes": [...]
  }
}
```

## Impact Analysis

```http
POST /api/v1/assets/{asset_id}/impact
```

Preview what would happen if you published a schema change.

### Request Body

```json
{
  "proposed_schema": {
    "type": "object",
    "properties": {...}
  }
}
```

### Response

```json
{
  "is_breaking": true,
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "$.properties.email",
      "description": "Property 'email' was removed"
    }
  ],
  "affected_consumers": [
    {
      "team_id": "team-uuid",
      "team_name": "Analytics"
    }
  ]
}
```

## Get Dependencies

```http
GET /api/v1/assets/{asset_id}/dependencies
```

Returns upstream dependencies for the asset.

## Get Audit History

```http
GET /api/v1/assets/{asset_id}/audit-history
```

Returns data quality audit runs for the asset.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status (passed, failed) |
| `triggered_by` | string | Filter by source (dbt_test, etc.) |
| `limit` | int | Number of results (default: 20) |
