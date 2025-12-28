# API Keys

Manage API keys for authentication.

## Create API Key

```http
POST /api/v1/api-keys
```

### Request Body

```json
{
  "name": "CI Pipeline Key",
  "team_id": "team-uuid",
  "scopes": ["read", "write"]
}
```

### Response

```json
{
  "id": "key-uuid",
  "name": "CI Pipeline Key",
  "key": "tsk_abc123...",
  "key_prefix": "tsk_abc1",
  "team_id": "team-uuid",
  "scopes": ["read", "write"],
  "created_at": "2025-01-15T10:00:00Z"
}
```

!!! warning
    The full `key` is only returned once on creation. Store it securely.

## List API Keys

```http
GET /api/v1/api-keys
```

Returns API keys for the current user/team (without full key values).

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `team_id` | uuid | Filter by team |

### Response

```json
{
  "results": [
    {
      "id": "key-uuid",
      "name": "CI Pipeline Key",
      "key_prefix": "tsk_abc1",
      "team_id": "team-uuid",
      "scopes": ["read", "write"],
      "created_at": "2025-01-15T10:00:00Z",
      "last_used_at": "2025-01-20T15:30:00Z"
    }
  ]
}
```

## Get API Key

```http
GET /api/v1/api-keys/{key_id}
```

### Response

```json
{
  "id": "key-uuid",
  "name": "CI Pipeline Key",
  "key_prefix": "tsk_abc1",
  "team_id": "team-uuid",
  "scopes": ["read", "write"],
  "created_at": "2025-01-15T10:00:00Z",
  "last_used_at": "2025-01-20T15:30:00Z"
}
```

## Revoke API Key

```http
DELETE /api/v1/api-keys/{key_id}
```

### Response

Returns the revoked API key details.

## Scopes

| Scope | Permissions |
|-------|-------------|
| `read` | Read assets, contracts, proposals, registrations |
| `write` | Create/update assets, publish contracts, manage registrations |
| `admin` | Manage teams, users, API keys |

## Authentication

Include the API key in the `Authorization` header:

```bash
curl -H "Authorization: Bearer tsk_abc123..." \
  http://localhost:8000/api/v1/assets
```
