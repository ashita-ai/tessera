# dbt Integration

Tessera integrates deeply with dbt to automatically extract and publish contracts from your dbt project.

## Overview

The integration:

1. Parses your `manifest.json` after `dbt compile` or `dbt run`
2. Creates assets for each model, source, seed, and snapshot
3. Extracts column schemas from your YAML definitions
4. Converts dbt tests into contract guarantees
5. Publishes contracts with version tracking
6. Detects breaking changes in CI/CD pipelines
7. Auto-registers consumers from `ref()` dependencies

## Quick Start

```bash
# 1. Compile your dbt project
dbt compile

# 2. Upload manifest to Tessera
curl -X POST http://localhost:8000/api/v1/sync/dbt/upload \
  -H "Content-Type: application/json" \
  -d "{
    \"manifest\": $(cat target/manifest.json),
    \"owner_team_id\": \"your-team-uuid\",
    \"auto_publish_contracts\": true
  }"
```

## Endpoints

### Upload Manifest

**POST /api/v1/sync/dbt/upload**

The primary integration endpoint. Syncs assets from a dbt manifest with full automation options.

```json
{
  "manifest": { /* manifest.json contents */ },
  "owner_team_id": "uuid",
  "conflict_mode": "overwrite",
  "auto_publish_contracts": true,
  "auto_create_proposals": true,
  "auto_register_consumers": true,
  "infer_consumers_from_refs": true
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `manifest` | object | required | Contents of manifest.json |
| `owner_team_id` | UUID | required | Default team for assets without `meta.tessera.owner_team` |
| `conflict_mode` | string | `"ignore"` | How to handle existing assets: `ignore`, `overwrite`, `fail` |
| `auto_publish_contracts` | boolean | `false` | Automatically publish contracts for synced assets |
| `auto_create_proposals` | boolean | `false` | Create proposals for breaking changes instead of failing |
| `auto_register_consumers` | boolean | `false` | Register consumers from `meta.tessera.consumers` |
| `infer_consumers_from_refs` | boolean | `false` | Infer consumer relationships from dbt `ref()` calls |
| `auto_delete` | boolean | `false` | Soft-delete dbt-managed assets missing from manifest (removed models) |

**Response:**

```json
{
  "status": "success",
  "assets": {
    "created": 10,
    "updated": 5,
    "skipped": 2,
    "deleted": 1,
    "deleted_fqns": ["warehouse.staging.stg_legacy"]
  },
  "contracts": {
    "published": 8
  },
  "proposals": {
    "created": 2,
    "details": [
      {
        "proposal_id": "uuid",
        "asset_fqn": "warehouse.analytics.dim_customers",
        "change_type": "major",
        "breaking_changes_count": 3
      }
    ]
  },
  "registrations": {
    "created": 15
  },
  "guarantees_extracted": 12
}
```

### Impact Analysis

**POST /api/v1/sync/dbt/impact**

Check impact of dbt model changes against existing contracts without applying changes.

```json
{
  "manifest": { /* manifest.json contents */ },
  "owner_team_id": "uuid"
}
```

**Response:**

```json
{
  "status": "success",
  "total_models": 15,
  "models_with_contracts": 8,
  "breaking_changes_count": 2,
  "results": [
    {
      "fqn": "warehouse.analytics.dim_customers",
      "node_id": "model.project.dim_customers",
      "has_contract": true,
      "safe_to_publish": false,
      "change_type": "major",
      "breaking_changes": [
        {
          "type": "property_removed",
          "property": "email",
          "message": "Required property 'email' was removed"
        }
      ]
    }
  ]
}
```

### CI/CD Diff

**POST /api/v1/sync/dbt/diff**

Dry-run preview for CI/CD pipelines. Shows what would change without applying.

```json
{
  "manifest": { /* manifest.json contents */ },
  "fail_on_breaking": true
}
```

**Response:**

```json
{
  "status": "breaking_changes_detected",
  "summary": {
    "new": 3,
    "modified": 5,
    "deleted": 1,
    "unchanged": 7,
    "breaking": 1
  },
  "blocking": true,
  "models": [
    {
      "fqn": "warehouse.analytics.dim_customers",
      "change_type": "modified",
      "schema_change_type": "breaking",
      "breaking_changes": ["Removed required field 'email'"]
    },
    {
      "fqn": "warehouse.staging.stg_legacy",
      "node_id": "model.project.stg_legacy",
      "change_type": "deleted",
      "consumers_declared": 2,
      "has_schema": false
    }
  ],
  "warnings": [
    "warehouse.staging.stg_legacy: Model removed but has 2 registered consumer(s)"
  ]
}
```

Use `blocking: true` in CI to fail the build on breaking changes.

**Deleted Model Detection**: The diff endpoint detects models that exist in Tessera but are missing from the manifest. These appear with `change_type: "deleted"` and include a count of registered consumers. Use this to identify models that may have downstream dependencies before removing them.

---

## Tessera Metadata Tags

Configure Tessera behavior using the `meta.tessera` block in your dbt YAML files.

### Full Example

```yaml
models:
  - name: dim_customers
    description: Customer dimension table
    meta:
      tessera:
        # Ownership
        owner_team: data-platform
        owner_user: alice@company.com

        # Consumer declarations
        consumers:
          - team: ml-platform
            purpose: Model training dataset
          - team: analytics
            purpose: Dashboard metrics

        # SLA guarantees
        freshness:
          max_staleness_minutes: 60
          measured_by: _loaded_at

        volume:
          min_rows: 10000
          max_row_delta_pct: 50

        # Contract settings
        compatibility_mode: backward

    columns:
      - name: customer_id
        data_type: integer
        tests:
          - not_null
          - unique
      - name: email
        data_type: string
        tests:
          - not_null
```

### Available Fields

| Field | Type | Description |
|-------|------|-------------|
| `owner_team` | string | Team name that owns this asset (overrides `owner_team_id`) |
| `owner_user` | string | Email of the user who owns this asset |
| `consumers` | list | Array of consumer team declarations |
| `consumers[].team` | string | Team name to register as consumer |
| `consumers[].purpose` | string | Optional description of how the team uses this data |
| `freshness` | object | Data freshness SLA configuration |
| `freshness.max_staleness_minutes` | integer | Maximum allowed data staleness |
| `freshness.measured_by` | string | Column used to measure freshness |
| `volume` | object | Data volume guarantees |
| `volume.min_rows` | integer | Minimum expected row count |
| `volume.max_row_delta_pct` | integer | Maximum allowed row count change percentage |
| `compatibility_mode` | string | Contract compatibility: `backward`, `forward`, `full`, `none` |

### Compatibility Modes

| Mode | Description |
|------|-------------|
| `backward` | New schema must be compatible with old (can add optional fields, can't remove) |
| `forward` | Old consumers must be able to read new data (can remove fields, can't add required) |
| `full` | Any schema change requires acknowledgment |
| `none` | No compatibility checking (notify only) |

---

## What Gets Synced

### Resource Types

| dbt Resource | Synced | Resource Type | Notes |
|--------------|--------|---------------|-------|
| Models | Yes | `model` | Full schema and metadata |
| Sources | Yes | `source` | External data sources |
| Seeds | Yes | `seed` | CSV reference data |
| Snapshots | Yes | `snapshot` | Type-2 slowly changing dimensions |
| Tests | Extracted | - | Converted to guarantees |
| Macros | No | - | Not applicable |
| Exposures | No | - | Not applicable |

### Asset Metadata

For each synced resource, Tessera captures:

```json
{
  "dbt_node_id": "model.my_project.dim_customers",
  "resource_type": "model",
  "description": "Customer dimension table",
  "tags": ["core", "pii"],
  "dbt_fqn": ["my_project", "marts", "core", "dim_customers"],
  "path": "models/marts/core/dim_customers.sql",
  "depends_on": [
    "warehouse.staging.stg_customers",
    "warehouse.staging.stg_orders"
  ],
  "columns": {
    "customer_id": {
      "data_type": "integer",
      "description": "Primary key"
    }
  },
  "guarantees": {
    "nullability": {"customer_id": "never"},
    "accepted_values": {}
  },
  "tessera_meta": {
    "owner_team": "data-platform",
    "consumers": [{"team": "analytics"}]
  }
}
```

---

## Test Extraction

Tessera automatically converts dbt tests into contract guarantees.

### Standard Tests

| dbt Test | Guarantee Type | Example |
|----------|---------------|---------|
| `not_null` | `nullability` | `{"customer_id": "never"}` |
| `accepted_values` | `accepted_values` | `{"status": ["active", "inactive"]}` |
| `unique` | `custom` | Stored with test config |
| `relationships` | `custom` | Stored with foreign key info |

### Third-Party Tests

Tests from `dbt_expectations`, `dbt_utils`, and other packages are stored as custom guarantees:

```yaml
columns:
  - name: email
    tests:
      - dbt_expectations.expect_column_values_to_match_regex:
          regex: "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
```

Becomes:

```json
{
  "guarantees": {
    "custom": [
      {
        "type": "dbt_expectations.expect_column_values_to_match_regex",
        "column": "email",
        "config": {
          "regex": "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
        }
      }
    ]
  }
}
```

### Singular Tests

SQL-based singular tests are also captured:

```sql
-- tests/assert_positive_revenue.sql
select *
from {{ ref('fct_orders') }}
where total_revenue < 0
```

Becomes:

```json
{
  "guarantees": {
    "custom": [
      {
        "type": "singular",
        "name": "assert_positive_revenue",
        "sql": "select * from {{ ref('fct_orders') }} where total_revenue < 0"
      }
    ]
  }
}
```

---

## Type Mapping

dbt column types are mapped to JSON Schema types:

| dbt Type | JSON Schema Type |
|----------|-----------------|
| `string`, `text`, `varchar`, `char` | `string` |
| `integer`, `int`, `bigint`, `smallint` | `integer` |
| `float`, `double`, `numeric`, `decimal` | `number` |
| `boolean`, `bool` | `boolean` |
| `date` | `string` (format: date) |
| `datetime`, `timestamp` | `string` (format: date-time) |
| `json`, `jsonb`, `variant`, `object` | `object` |
| `array` | `array` |

---

## Consumer Auto-Registration

### From Meta Tags

Declare consumers in your model YAML:

```yaml
models:
  - name: fct_orders
    meta:
      tessera:
        consumers:
          - team: analytics
            purpose: Daily revenue dashboard
          - team: ml-platform
            purpose: Churn prediction model
```

With `auto_register_consumers: true`, these teams are automatically registered.

### From Refs

With `infer_consumers_from_refs: true`, Tessera analyzes dbt `ref()` calls:

```sql
-- models/marts/fct_revenue.sql
select * from {{ ref('fct_orders') }}
```

If `fct_revenue` is owned by team `finance`, they're registered as a consumer of `fct_orders`.

---

## CI/CD Integration

### GitHub Actions - Check Breaking Changes

```yaml
name: Check Contracts

on:
  pull_request:
    paths:
      - 'models/**'
      - 'dbt_project.yml'

jobs:
  contract-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dbt
        run: pip install dbt-core dbt-postgres

      - name: Compile dbt
        run: dbt compile
        env:
          DBT_PROFILES_DIR: .

      - name: Check contract impact
        run: |
          RESULT=$(curl -s -X POST ${{ secrets.TESSERA_URL }}/api/v1/sync/dbt/diff \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d "{\"manifest\": $(cat target/manifest.json), \"fail_on_breaking\": true}")

          echo "$RESULT" | jq .

          if [ "$(echo $RESULT | jq -r '.blocking')" = "true" ]; then
            echo "::error::Breaking changes detected!"
            exit 1
          fi
```

### GitHub Actions - Sync on Merge

```yaml
name: Sync to Tessera

on:
  push:
    branches: [main]
    paths:
      - 'models/**'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Compile dbt
        run: dbt compile

      - name: Sync to Tessera
        run: |
          curl -X POST ${{ secrets.TESSERA_URL }}/api/v1/sync/dbt/upload \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"manifest\": $(cat target/manifest.json),
              \"owner_team_id\": \"${{ secrets.TESSERA_TEAM_ID }}\",
              \"conflict_mode\": \"overwrite\",
              \"auto_publish_contracts\": true,
              \"auto_register_consumers\": true,
              \"infer_consumers_from_refs\": true
            }"
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: tessera-check
        name: Check Tessera contracts
        entry: bash -c 'dbt compile && curl -s -X POST $TESSERA_URL/api/v1/sync/dbt/diff -d "{\"manifest\": $(cat target/manifest.json)}" | jq -e ".blocking == false"'
        language: system
        files: ^models/.*\.yml$
        pass_filenames: false
```

---

## Conflict Resolution

The `conflict_mode` parameter controls how existing assets are handled:

| Mode | Behavior |
|------|----------|
| `ignore` | Skip assets that already exist (default, safe) |
| `overwrite` | Update existing assets with new metadata |
| `fail` | Return error if any asset already exists |

---

## Model Deletion Lifecycle

Tessera uses soft deletes for assets. When a dbt model is removed, the asset is marked with a `deleted_at` timestamp rather than being physically deleted. This preserves audit history and allows recovery.

### Detecting Deleted Models

Use the `/dbt/diff` endpoint to preview which models would be deleted:

```bash
curl -X POST http://localhost:8000/api/v1/sync/dbt/diff \
  -H "Content-Type: application/json" \
  -d "{\"manifest\": $(cat target/manifest.json)}"
```

Models in Tessera but missing from the manifest appear with `change_type: "deleted"` along with their consumer count.

### Enabling Auto-Delete

By default, `/dbt/upload` does not delete assets. Enable with `auto_delete: true`:

```bash
curl -X POST http://localhost:8000/api/v1/sync/dbt/upload \
  -H "Content-Type: application/json" \
  -d "{
    \"manifest\": $(cat target/manifest.json),
    \"owner_team_id\": \"your-team-uuid\",
    \"auto_delete\": true
  }"
```

Only dbt-managed assets (those with `dbt_node_id` or `dbt_source_id` in metadata) are deleted. Manually-created assets are never affected.

### What Gets Deleted

| Asset Type | Deleted by auto_delete |
|------------|------------------------|
| Models synced from dbt | Yes |
| Sources synced from dbt | Yes |
| Seeds synced from dbt | Yes |
| Snapshots synced from dbt | Yes |
| Manually-created assets | No |
| Assets from other sync sources | No |

### Recovery

Soft-deleted assets can be restored by re-syncing a manifest that includes the model. The asset's `deleted_at` will be cleared.

---

## Troubleshooting

### No columns extracted

Ensure your YAML has `data_type` definitions:

```yaml
columns:
  - name: id
    data_type: integer  # Required for schema extraction
```

### Model not synced

Check that the model:
- Is in the manifest (run `dbt compile`)
- Has a valid unique_id
- Matches any filter you've applied

### Team not found

If you get `owner_team 'xyz' not found`:
- Create the team first via the API or UI
- Use the team name exactly as it appears in Tessera
- Or remove `meta.tessera.owner_team` to use the default `owner_team_id`

### Breaking changes not detected

Ensure the asset has an existing contract:
- Check `/api/v1/assets/{id}` for `current_contract_id`
- Contracts are only published with `auto_publish_contracts: true`

---

## Python SDK

Use the [Tessera Python SDK](https://github.com/ashita-ai/tessera-python) for programmatic access:

```python
from tessera_sdk import TesseraClient
import json

client = TesseraClient(base_url="http://localhost:8000")

# Load manifest
with open("target/manifest.json") as f:
    manifest = json.load(f)

# Sync with options
result = client.sync.dbt_upload(
    manifest=manifest,
    owner_team_id="your-team-uuid",
    auto_publish_contracts=True,
    auto_register_consumers=True
)

print(f"Created {result.assets.created} assets")
print(f"Published {result.contracts.published} contracts")
```
