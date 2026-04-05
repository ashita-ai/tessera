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

Compare two existing contracts by ID and return the schema differences.

### Request Body

```json
{
  "contract_id_1": "uuid-of-first-contract",
  "contract_id_2": "uuid-of-second-contract",
  "compatibility_mode": "backward"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `contract_id_1` | UUID | Yes | First contract to compare |
| `contract_id_2` | UUID | Yes | Second contract to compare |
| `compatibility_mode` | string | No | Override compatibility mode (`backward`, `forward`, `full`, `none`). Defaults to the first contract's mode. |

### Response

```json
{
  "contract_1": {
    "id": "uuid",
    "version": "1.0.0",
    "published_at": "2024-01-01T00:00:00Z",
    "asset_id": "uuid"
  },
  "contract_2": {
    "id": "uuid",
    "version": "2.0.0",
    "published_at": "2024-02-01T00:00:00Z",
    "asset_id": "uuid"
  },
  "change_type": "major",
  "is_compatible": false,
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "properties.email",
      "message": "Property 'email' was removed",
      "old_value": {"type": "string"},
      "new_value": null
    }
  ],
  "all_changes": [...],
  "compatibility_mode": "backward"
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

Preview what version would be suggested for a new schema without actually publishing. Useful for CI dry-run checks.

### Request Body

```json
{
  "schema": {
    "type": "object",
    "properties": {...}
  }
}
```

### Response

```json
{
  "suggested_version": "2.0.0",
  "current_version": "1.5.0",
  "change_type": "major",
  "reason": "Breaking changes detected: 1 incompatible modification(s)",
  "is_first_contract": false
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

Returns **200** when all items succeed, or **207 Multi-Status** when any items fail.

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
