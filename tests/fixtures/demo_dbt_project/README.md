# Tessera Demo dbt Project

A minimal but realistic dbt project for testing and demonstrating Tessera's dbt integration.

## Project Structure

```
demo_dbt_project/
├── dbt_project.yml          # Project config with tessera vars
├── profiles.yml             # DuckDB profile (no external DB needed)
├── models/
│   ├── staging/
│   │   ├── stg_orders.sql
│   │   ├── stg_customers.sql
│   │   └── _staging.yml     # Generic tests (not_null, unique)
│   └── marts/
│       ├── fct_orders.sql
│       ├── dim_customers.sql
│       └── _marts.yml       # Generic tests + tessera metadata
├── tests/
│   ├── assert_positive_revenue.sql      # Singular test
│   └── assert_customers_have_valid_email.sql
└── seeds/
    ├── raw_orders.csv
    └── raw_customers.csv
```

## Running the Project

```bash
cd tests/fixtures/demo_dbt_project

# Build everything (seeds, models, tests)
dbt build --profiles-dir .

# Just compile (no execution)
dbt compile --profiles-dir .
```

## Generated Artifacts

After running `dbt build`:

- `target/manifest.json` - Model metadata, test definitions, dependencies
- `target/run_results.json` - Test execution results (pass/fail)

## Tessera Integration

### 1. Sync dbt models to Tessera

```bash
# POST manifest.json to Tessera
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Content-Type: application/json" \
  -d @target/manifest.json
```

This creates:
- Assets for each model (fqn: `tessera_demo.stg_orders`, etc.)
- Contracts with JSON schemas derived from column definitions
- Test definitions as contract guarantees

### 2. Report test results (WAP)

After `dbt test` runs, report results to Tessera:

```bash
# Using the provided script
python scripts/report_to_tessera.py \
  --target-path target/ \
  --tessera-url http://localhost:8000

# Or manually POST to the audit endpoint
curl -X POST "http://localhost:8000/api/v1/assets/{asset_id}/audit-results" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "passed",
    "triggered_by": "dbt_test",
    "guarantees_checked": 5,
    "guarantees_passed": 5,
    "guarantees_failed": 0
  }'
```

## Tessera Metadata in schema.yml

Models can include Tessera-specific metadata:

```yaml
models:
  - name: fct_orders
    meta:
      tessera:
        owner_team: data-platform
        compatibility_mode: backward
        consumers:
          - team: analytics
          - team: finance
```

This metadata is used when syncing to Tessera to:
- Assign model ownership
- Set breaking change detection mode
- Pre-register consumer dependencies
