# Teams API

Manage teams in Tessera.

## List Teams

```http
GET /api/v1/teams
```

### Response

```json
{
  "results": [
    {
      "id": "team-uuid",
      "name": "data-platform",
      "created_at": "2025-01-01T10:00:00Z",
      "member_count": 5,
      "asset_count": 25
    }
  ]
}
```

## Get Team

```http
GET /api/v1/teams/{team_id}
```

### Response

```json
{
  "id": "team-uuid",
  "name": "data-platform",
  "created_at": "2025-01-01T10:00:00Z",
  "members": [
    {
      "id": "user-uuid",
      "name": "John Doe",
      "email": "john@example.com",
      "role": "team_admin"
    }
  ]
}
```

## Create Team

```http
POST /api/v1/teams
```

### Request Body

```json
{
  "name": "analytics"
}
```

### Response

```json
{
  "id": "new-team-uuid",
  "name": "analytics",
  "created_at": "2025-01-15T10:00:00Z"
}
```

## Update Team

```http
PATCH /api/v1/teams/{team_id}
```

### Request Body

```json
{
  "name": "analytics-team"
}
```

## Delete Team

```http
DELETE /api/v1/teams/{team_id}
```

Returns `204 No Content` on success.

!!! warning
    Deleting a team will orphan its assets. Reassign assets first.

## Get Team Assets

```http
GET /api/v1/teams/{team_id}/assets
```

List all assets owned by the team.

## Get Team Registrations

```http
GET /api/v1/teams/{team_id}/registrations
```

List all contracts the team is registered as a consumer of.

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
