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
  "schema_format": "json_schema",
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

### Schema Format

The `schema_format` field indicates the format of the `schema_def`:

| Format | Description |
|--------|-------------|
| `json_schema` | JSON Schema (default) |
| `avro` | Apache Avro schema (Kafka topics) |

Note: OpenAPI and GraphQL imports are converted to JSON Schema internally.

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

## Update Guarantees

```http
PATCH /api/v1/contracts/{contract_id}/guarantees
```

Update the guarantees on an existing contract without changing the schema.

### Request Body

```json
{
  "guarantees": {
    "freshness": {
      "max_staleness_minutes": 120
    },
    "volume": {
      "min_rows": 1000
    }
  }
}
```

### Response

Returns the updated contract.

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

## Bulk Publish Contracts

```http
POST /api/v1/contracts/bulk
```

Publish multiple contracts in a single request. Useful for CI/CD pipelines.

### Request Body

```json
{
  "contracts": [
    {
      "asset_fqn": "warehouse.analytics.users",
      "schema": {...},
      "version": "1.0.0"
    },
    {
      "asset_fqn": "warehouse.analytics.orders",
      "schema": {...},
      "version": "2.1.0"
    }
  ],
  "published_by": "team-uuid"
}
```

### Response

```json
{
  "results": [
    {
      "asset_fqn": "warehouse.analytics.users",
      "status": "published",
      "contract_id": "uuid"
    },
    {
      "asset_fqn": "warehouse.analytics.orders",
      "status": "proposal_created",
      "proposal_id": "uuid"
    }
  ],
  "summary": {
    "published": 1,
    "proposals_created": 1,
    "failed": 0
  }
}
```
