# Teams API

Manage teams in Tessera.

## List Teams

```http
GET /api/v1/teams
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Filter by name pattern (case-insensitive) |
| `limit` | int | Results per page (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "team-uuid",
      "name": "data-platform",
      "metadata": {},
      "created_at": "2025-01-01T10:00:00Z",
      "asset_count": 25
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## Get Team

```http
GET /api/v1/teams/{team_id}
```

### Response

Returns a Team object.

```json
{
  "id": "team-uuid",
  "name": "data-platform",
  "metadata": {},
  "created_at": "2025-01-01T10:00:00Z"
}
```

## Create Team

```http
POST /api/v1/teams
```

Requires admin scope.

### Request Body

```json
{
  "name": "analytics",
  "metadata": {}
}
```

`metadata` is optional and defaults to `{}`.

### Response (201)

```json
{
  "id": "new-team-uuid",
  "name": "analytics",
  "metadata": {},
  "created_at": "2025-01-15T10:00:00Z"
}
```

## Update Team

```http
PATCH /api/v1/teams/{team_id}
PUT /api/v1/teams/{team_id}
```

Requires admin scope. Both PATCH and PUT are supported with the same behavior.

### Request Body

All fields are optional.

```json
{
  "name": "analytics-team",
  "metadata": {"cost_center": "eng-42"}
}
```

### Response

Returns the updated Team object.

## Delete Team

```http
DELETE /api/v1/teams/{team_id}
```

Soft-deletes a team. Requires admin scope.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `force` | bool | Force delete even if team has assets (default: false) |

Returns `204 No Content` on success.

!!! warning
    If the team owns assets and `force` is not set, the request will fail with `409 Conflict`. Use the reassign-assets endpoint to move assets first, or pass `force=true`.

## Restore Team

```http
POST /api/v1/teams/{team_id}/restore
```

Restores a soft-deleted team. Requires admin scope. If the team is not deleted, returns it unchanged.

### Response

Returns the restored Team object.

## List Team Members

```http
GET /api/v1/teams/{team_id}/members
```

List all active (non-deactivated) users belonging to a team. Requires read scope.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Results per page (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "user-uuid",
      "username": "jdoe",
      "email": "john@example.com",
      "name": "John Doe",
      "user_type": "human",
      "role": "user",
      "team_id": "team-uuid",
      "metadata": {}
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## Reassign Assets

```http
POST /api/v1/teams/{team_id}/reassign-assets
```

Reassign assets from this team to another team. Requires admin scope. Can reassign all assets or specific ones by ID.

### Request Body

```json
{
  "target_team_id": "target-team-uuid",
  "asset_ids": ["asset-uuid-1", "asset-uuid-2"]
}
```

`asset_ids` is optional. If omitted, all assets owned by the source team are reassigned.

### Response

```json
{
  "reassigned": 2,
  "source_team": {"id": "team-uuid", "name": "old-team"},
  "target_team": {"id": "target-team-uuid", "name": "new-team"},
  "asset_ids": ["asset-uuid-1", "asset-uuid-2"]
}
```

## API Keys

API keys are managed via the dedicated [API Keys endpoint](api-keys.md).

Create keys with the team ID:

```http
POST /api/v1/api-keys
```

```json
{
  "name": "CI Pipeline Key",
  "team_id": "team-uuid",
  "scopes": ["read", "write"]
}
```

See [API Keys](api-keys.md) for full documentation.
