# dbt Integration

Tessera integrates deeply with dbt to automatically extract and publish contracts from your dbt project.

## Overview

The integration:

1. Parses your `manifest.json` after `dbt compile` or `dbt run`
2. Creates assets for each model, source, seed, and snapshot
3. Extracts column schemas from your YAML definitions
4. Publishes contracts with the extracted schemas
5. Tracks dependencies between models

## Quick Start

```bash
# 1. Compile your dbt project
dbt compile

# 2. Upload manifest to Tessera
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d @target/manifest.json
```

## What Gets Synced

### Models

Each dbt model becomes a Tessera asset. If you have column definitions in your YAML, they become the contract schema:

```yaml
# models/marts/_marts.yml
models:
  - name: dim_customers
    description: Customer dimension table
    columns:
      - name: customer_id
        description: Primary key
        data_type: integer
        tests:
          - not_null
          - unique
      - name: email
        description: Customer email
        data_type: string
```

This creates a contract with:

```json
{
  "type": "object",
  "properties": {
    "customer_id": {
      "type": "integer",
      "description": "Primary key"
    },
    "email": {
      "type": "string",
      "description": "Customer email"
    }
  },
  "required": ["customer_id"]
}
```

### Sources

External sources are synced as assets:

```yaml
# models/staging/_sources.yml
sources:
  - name: raw
    tables:
      - name: customers
        columns:
          - name: id
            data_type: integer
```

### Seeds

Seed files (CSV) are synced as assets with `resource_type: seed`. They typically don't have schema definitions.

### Tests

dbt tests are extracted as guarantees:

| dbt Test | Tessera Guarantee |
|----------|-------------------|
| `not_null` | `nullability: {column: "not_null"}` |
| `accepted_values` | `accepted_values: {column: [...]}` |
| `relationships` | Stored in metadata |
| Singular tests | `custom: [{type: "singular", sql: ...}]` |

## Sync Options

### Full Sync (Default)

Creates or updates all assets from the manifest:

```bash
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -d @manifest.json
```

### Dry Run

Preview what would be synced without making changes:

```bash
curl -X POST "http://localhost:8000/api/v1/sync/dbt?dry_run=true" \
  -d @manifest.json
```

### Specific Models

Sync only specific models:

```bash
curl -X POST "http://localhost:8000/api/v1/sync/dbt?models=dim_customers,fct_orders" \
  -d @manifest.json
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Sync dbt to Tessera

on:
  push:
    branches: [main]
    paths:
      - 'models/**'
      - 'dbt_project.yml'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dbt
        run: pip install dbt-core dbt-postgres

      - name: Compile dbt
        run: dbt compile
        env:
          DBT_PROFILES_DIR: .

      - name: Sync to Tessera
        run: |
          curl -X POST ${{ secrets.TESSERA_URL }}/api/v1/sync/dbt \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d @target/manifest.json
```

### Pre-commit Hook

Check for breaking changes before committing:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: tessera-check
        name: Check Tessera contracts
        entry: scripts/check-contracts.sh
        language: script
        files: ^models/.*\.yml$
```

## Reporting Test Results

Report dbt test results to Tessera for audit tracking:

```bash
# After dbt test
python scripts/report_to_tessera.py \
  --manifest target/manifest.json \
  --run-results target/run_results.json \
  --tessera-url http://localhost:8000 \
  --api-key $TESSERA_API_KEY
```

This updates the audit history shown in the asset detail page.

## Troubleshooting

### No columns extracted

Make sure your YAML has `data_type` or type definitions:

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

### Schema mismatch

Tessera uses JSON Schema types. The mapping from dbt types:

| dbt type | JSON Schema type |
|----------|------------------|
| `integer`, `int` | `integer` |
| `string`, `text`, `varchar` | `string` |
| `boolean`, `bool` | `boolean` |
| `float`, `numeric`, `decimal` | `number` |
| `date` | `string` (format: date) |
| `timestamp` | `string` (format: date-time) |
