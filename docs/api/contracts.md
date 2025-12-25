# Contracts API

Manage data contracts in Tessera.

## List Contracts

```http
GET /api/v1/contracts
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `asset_id` | uuid | Filter by asset |
| `status` | string | Filter by status (active, deprecated, archived) |
| `page` | int | Page number |
| `page_size` | int | Results per page |

### Response

```json
{
  "results": [
    {
      "id": "contract-uuid",
      "asset_id": "asset-uuid",
      "asset_fqn": "warehouse.analytics.users",
      "version": "1.2.0",
      "status": "active",
      "compatibility_mode": "backward",
      "published_at": "2025-01-15T10:00:00Z",
      "published_by": "team-uuid",
      "published_by_team_name": "Data Platform"
    }
  ],
  "total": 25
}
```

## Get Contract

```http
GET /api/v1/contracts/{contract_id}
```

### Response

```json
{
  "id": "contract-uuid",
  "asset_id": "asset-uuid",
  "asset_fqn": "warehouse.analytics.users",
  "version": "1.2.0",
  "status": "active",
  "compatibility_mode": "backward",
  "schema_def": {
    "type": "object",
    "properties": {
      "id": {"type": "integer"},
      "name": {"type": "string"}
    },
    "required": ["id"]
  },
  "guarantees": {
    "freshness": {
      "max_staleness_minutes": 60
    },
    "nullability": {
      "id": "not_null"
    }
  },
  "published_at": "2025-01-15T10:00:00Z",
  "published_by": "team-uuid"
}
```

## Get Contract Registrations

```http
GET /api/v1/contracts/{contract_id}/registrations
```

List all consumer registrations for a contract.

### Response

```json
{
  "results": [
    {
      "id": "registration-uuid",
      "consumer_team_id": "team-uuid",
      "consumer_team_name": "Analytics",
      "registered_at": "2025-01-10T10:00:00Z",
      "status": "active"
    }
  ]
}
```

## Compare Contracts

```http
POST /api/v1/contracts/compare
```

Compare two schemas to see differences.

### Request Body

```json
{
  "old_schema": {
    "type": "object",
    "properties": {...}
  },
  "new_schema": {
    "type": "object",
    "properties": {...}
  },
  "compatibility_mode": "backward"
}
```

### Response

```json
{
  "is_compatible": false,
  "changes": [
    {
      "type": "property_removed",
      "path": "$.properties.email",
      "breaking": true,
      "description": "Property 'email' was removed"
    },
    {
      "type": "property_added",
      "path": "$.properties.phone",
      "breaking": false,
      "description": "Optional property 'phone' was added"
    }
  ]
}
```
