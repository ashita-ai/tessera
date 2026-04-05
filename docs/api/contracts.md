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
| `version` | string | Filter by version pattern (substring match) |
| `limit` | int | Results per page (default: 50, max: 100) |
| `offset` | int | Pagination offset (default: 0) |

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
      "publisher_name": "Data Platform"
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0
}
```

## Get Contract

```http
GET /api/v1/contracts/{contract_id}
```

Returns a contract with asset FQN and publisher team name. Requires read scope.

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
  "field_descriptions": {},
  "field_tags": {},
  "guarantees": {
    "freshness": {
      "max_staleness_minutes": 60
    },
    "nullability": {
      "id": "not_null"
    }
  },
  "published_at": "2025-01-15T10:00:00Z",
  "published_by": "team-uuid",
  "published_by_user_id": null,
  "publisher_name": "Data Platform"
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

List all consumer registrations for a contract. Requires read scope.

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
      "id": "registration-uuid",
      "consumer_team_id": "team-uuid",
      "consumer_team_name": "Analytics",
      "registered_at": "2025-01-10T10:00:00Z"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

## Update Guarantees

```http
PATCH /api/v1/contracts/{contract_id}/guarantees
```

Update the guarantees on an existing contract without changing the schema. Requires write scope. Only active contracts can be updated. Resource-level auth: must own the asset's team or use an admin key.

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

Compare two existing contracts by ID and return the schema differences. Requires read scope.

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

## Bulk Publish Contracts

```http
POST /api/v1/contracts/bulk
```

Publish multiple contracts in a single request. Supports a two-phase workflow. Requires write scope.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `dry_run` | bool | Preview mode -- no changes made (default: true) |
| `create_proposals_for_breaking` | bool | Auto-create proposals for breaking changes when `dry_run=false` (default: false) |

### Request Body

```json
{
  "contracts": [
    {
      "asset_id": "asset-uuid-1",
      "schema": {
        "type": "object",
        "properties": {
          "id": {"type": "integer"}
        }
      },
      "compatibility_mode": "backward",
      "guarantees": null,
      "field_descriptions": {},
      "field_tags": {}
    }
  ],
  "published_by": "team-uuid",
  "published_by_user_id": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `contracts` | array | Yes | List of contracts to publish (max 100) |
| `contracts[].asset_id` | uuid | Yes | Target asset ID |
| `contracts[].schema` | object | Yes | JSON Schema definition |
| `contracts[].compatibility_mode` | string | No | Override compatibility mode |
| `contracts[].guarantees` | object | No | Contract guarantees |
| `contracts[].field_descriptions` | object | No | Map of JSON path to description |
| `contracts[].field_tags` | object | No | Map of JSON path to tag list |
| `published_by` | uuid | Yes | Publisher team ID |
| `published_by_user_id` | uuid | No | Publisher user ID |

### Response

```json
{
  "preview": true,
  "total": 2,
  "published": 1,
  "skipped": 0,
  "proposals_created": 1,
  "failed": 0,
  "results": [
    {
      "asset_id": "asset-uuid-1",
      "asset_fqn": "warehouse.analytics.users",
      "status": "published",
      "contract_id": "contract-uuid",
      "suggested_version": "1.1.0",
      "current_version": "1.0.0",
      "reason": "Compatible change",
      "breaking_changes": []
    },
    {
      "asset_id": "asset-uuid-2",
      "asset_fqn": "warehouse.analytics.orders",
      "status": "proposal.created",
      "proposal_id": "proposal-uuid",
      "suggested_version": "2.0.0",
      "current_version": "1.5.0",
      "reason": "Breaking changes detected",
      "breaking_changes": [
        {
          "type": "property_removed",
          "path": "properties.email"
        }
      ]
    }
  ]
}
```
