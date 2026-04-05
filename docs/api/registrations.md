# Registrations API

Manage consumer registrations for contracts.

## Create Registration

```http
POST /api/v1/registrations?contract_id={contract_id}
```

Register a team as a consumer of a contract. Requires write scope.

The `contract_id` is passed as a query parameter, not in the request body. The caller's team must match `consumer_team_id` unless the caller has admin scope.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `contract_id` | uuid | yes | Contract to register for |

### Request Body

```json
{
  "consumer_team_id": "team-uuid",
  "pinned_version": "1.2.0"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `consumer_team_id` | uuid | yes | Team registering as consumer |
| `pinned_version` | string | no | Semver to pin to (null = track latest compatible) |

### Response

```json
{
  "id": "registration-uuid",
  "contract_id": "contract-uuid",
  "consumer_team_id": "team-uuid",
  "pinned_version": "1.2.0",
  "status": "active",
  "registered_at": "2025-01-15T10:00:00Z",
  "acknowledged_at": null,
  "updated_at": null
}
```

## List Registrations

```http
GET /api/v1/registrations
```

Requires read scope. Returns `X-Total-Count` header with total count.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `contract_id` | uuid | Filter by contract |
| `consumer_team_id` | uuid | Filter by consumer team |
| `status` | string | Filter by status: `active`, `migrating`, `inactive` |
| `limit` | int | Results per page (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "registration-uuid",
      "contract_id": "contract-uuid",
      "consumer_team_id": "team-uuid",
      "pinned_version": null,
      "status": "active",
      "registered_at": "2025-01-15T10:00:00Z",
      "acknowledged_at": null,
      "updated_at": null
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0
}
```

## Get Registration

```http
GET /api/v1/registrations/{registration_id}
```

Requires read scope.

### Response

```json
{
  "id": "registration-uuid",
  "contract_id": "contract-uuid",
  "consumer_team_id": "team-uuid",
  "pinned_version": "1.2.0",
  "status": "active",
  "registered_at": "2025-01-15T10:00:00Z",
  "acknowledged_at": null,
  "updated_at": "2025-01-15T12:00:00Z"
}
```

## Update Registration

```http
PATCH /api/v1/registrations/{registration_id}
```

Requires write scope. The caller's team must own the registration or have admin scope.

### Request Body

```json
{
  "pinned_version": "2.0.0",
  "status": "inactive"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `pinned_version` | string | Semver to pin to |
| `status` | string | `active`, `migrating`, or `inactive` |

### Response

Returns the updated registration.

## Delete Registration

```http
DELETE /api/v1/registrations/{registration_id}
```

Requires write scope. The caller's team must own the registration or have admin scope. Performs a soft delete.

Returns `204 No Content` on success.

## Why Register?

Registering as a consumer:

1. **Breaking change notifications** - You'll be notified when the producer wants to make breaking changes
2. **Acknowledgment workflow** - Breaking changes require your acknowledgment before publishing
3. **Impact analysis** - Producers can see who depends on their data
4. **Audit trail** - Track your team's data dependencies
