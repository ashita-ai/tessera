# Registrations API

Manage consumer registrations for contracts.

## Create Registration

```http
POST /api/v1/registrations
```

Register a team as a consumer of a contract.

### Request Body

```json
{
  "contract_id": "contract-uuid",
  "consumer_team_id": "team-uuid",
  "notes": "Used for analytics dashboard"
}
```

### Response

```json
{
  "id": "registration-uuid",
  "contract_id": "contract-uuid",
  "consumer_team_id": "team-uuid",
  "consumer_team_name": "Analytics",
  "notes": "Used for analytics dashboard",
  "status": "active",
  "created_at": "2025-01-15T10:00:00Z"
}
```

## List Registrations

```http
GET /api/v1/registrations
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `contract_id` | uuid | Filter by contract |
| `consumer_team_id` | uuid | Filter by consumer team |
| `status` | string | Filter by status: `active`, `inactive` |
| `page` | int | Page number |
| `page_size` | int | Results per page |

### Response

```json
{
  "results": [
    {
      "id": "registration-uuid",
      "contract_id": "contract-uuid",
      "asset_fqn": "warehouse.analytics.users",
      "contract_version": "1.2.0",
      "consumer_team_id": "team-uuid",
      "consumer_team_name": "Analytics",
      "status": "active",
      "created_at": "2025-01-15T10:00:00Z"
    }
  ],
  "total": 25
}
```

## Get Registration

```http
GET /api/v1/registrations/{registration_id}
```

### Response

```json
{
  "id": "registration-uuid",
  "contract_id": "contract-uuid",
  "asset_id": "asset-uuid",
  "asset_fqn": "warehouse.analytics.users",
  "contract_version": "1.2.0",
  "consumer_team_id": "team-uuid",
  "consumer_team_name": "Analytics",
  "notes": "Used for analytics dashboard",
  "status": "active",
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

## Update Registration

```http
PATCH /api/v1/registrations/{registration_id}
```

### Request Body

```json
{
  "notes": "Updated usage notes",
  "status": "inactive"
}
```

### Response

Returns the updated registration.

## Delete Registration

```http
DELETE /api/v1/registrations/{registration_id}
```

Returns `204 No Content` on success.

## Why Register?

Registering as a consumer:

1. **Breaking change notifications** - You'll be notified when the producer wants to make breaking changes
2. **Acknowledgment workflow** - Breaking changes require your acknowledgment before publishing
3. **Impact analysis** - Producers can see who depends on their data
4. **Audit trail** - Track your team's data dependencies
