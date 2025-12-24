# Assets & Contracts

## Assets

An asset represents any data object you want to track contracts for.

### Creating Assets

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "warehouse.analytics.users",
    "owner_team_id": "team-uuid",
    "environment": "production",
    "metadata": {
      "description": "Core users table",
      "tags": ["pii", "core"]
    }
  }'
```

### Asset Properties

| Property | Required | Description |
|----------|----------|-------------|
| `fqn` | Yes | Unique identifier (e.g., `project.dataset.table`) |
| `owner_team_id` | Yes | UUID of the owning team |
| `environment` | No | Environment name (default: `production`) |
| `metadata` | No | Arbitrary metadata object |

### Metadata from dbt

When syncing from dbt, metadata includes:

- `resource_type`: model, seed, source, snapshot
- `dbt_fqn`: Original dbt FQN array
- `path`: File path in the project
- `tags`: dbt tags
- `depends_on`: Upstream dependencies

## Contracts

A contract is a versioned schema definition for an asset.

### Publishing Contracts

```bash
curl -X POST http://localhost:8000/api/v1/assets/{asset_id}/contracts \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "schema": {
      "type": "object",
      "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "email": {"type": "string", "format": "email"}
      },
      "required": ["id", "name"]
    },
    "compatibility_mode": "backward"
  }'
```

### Contract Properties

| Property | Required | Description |
|----------|----------|-------------|
| `schema` | Yes | JSON Schema definition |
| `compatibility_mode` | No | How changes are evaluated (default: `backward`) |
| `version` | No | Semantic version (auto-incremented if not provided) |
| `guarantees` | No | SLAs and data quality rules |

### Versioning

Tessera auto-increments versions based on change type:

| Change Type | Version Bump |
|-------------|--------------|
| Patch (metadata only) | `1.0.0` → `1.0.1` |
| Minor (compatible change) | `1.0.0` → `1.1.0` |
| Major (breaking change) | `1.0.0` → `2.0.0` |

### Contract Status

| Status | Description |
|--------|-------------|
| `active` | Current live contract |
| `deprecated` | Previous version, still valid |
| `archived` | No longer valid |

## Guarantees

Contracts can include SLA guarantees:

```json
{
  "guarantees": {
    "freshness": {
      "max_staleness_minutes": 60
    },
    "volume": {
      "min_rows": 1,
      "max_row_delta_pct": 50
    }
  }
}
```

These are validated by dbt tests and reported to Tessera.
