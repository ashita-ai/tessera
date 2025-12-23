# Tessera Demo dbt Projects

A realistic multi-project dbt setup for demonstrating Tessera's data contract coordination.

## Key Features Demonstrated

### Multi-Project Support
Tessera manages contracts across multiple dbt projects, each owned by different teams:
- **core/** - Data Platform team's foundational models (orders, customers, products)
- **marketing/** - Marketing Analytics team's campaign and attribution models
- **finance/** - Finance Analytics team's invoicing and budgeting models

### Generic WAP (Write-Audit-Publish) Integration
Tessera's WAP integration is **tool-agnostic** - it works with any data quality framework:
- dbt tests (generic and singular)
- dbt-utils audit tests
- Great Expectations
- Soda
- Custom SQL checks
- Any tool that produces pass/fail results

The key insight: Tessera doesn't care *how* you run your tests, only *what* the results are.

### Test Types Included
Each project includes a variety of test types:
- **Generic tests**: unique, not_null, accepted_values, relationships
- **dbt-utils tests**: accepted_range, unique_combination_of_columns
- **Singular SQL tests**: Custom business logic validation

## Project Structure

```
demo_dbt_projects/
├── core/                           # Data Platform Team
│   ├── models/staging/             # 5 staging models
│   ├── models/intermediate/        # 3 intermediate models
│   ├── models/marts/               # 5 mart models
│   └── tests/                      # 6 singular tests
├── marketing/                      # Marketing Analytics Team
│   ├── models/staging/             # 4 staging models
│   ├── models/intermediate/        # 2 intermediate models
│   ├── models/marts/               # 4 mart models
│   └── tests/                      # 3 singular tests
└── finance/                        # Finance Analytics Team
    ├── models/staging/             # 4 staging models
    ├── models/intermediate/        # 3 intermediate models
    ├── models/marts/               # 5 mart models
    └── tests/                      # 3 singular tests
```

**Total: 35 models, 70+ tests**

## Running Individual Projects

Each project uses DuckDB (in-memory) for fast, zero-setup execution:

```bash
# Core project
cd core && dbt deps && dbt build --profiles-dir .

# Marketing project
cd marketing && dbt deps && dbt build --profiles-dir .

# Finance project
cd finance && dbt deps && dbt build --profiles-dir .
```

## Tessera Integration

### 1. Sync Each Project to Its Team

```bash
# Sync core models to data-platform team
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Content-Type: application/json" \
  -d @core/target/manifest.json

# Sync marketing models to marketing-analytics team
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Content-Type: application/json" \
  -d @marketing/target/manifest.json

# Sync finance models to finance-analytics team
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Content-Type: application/json" \
  -d @finance/target/manifest.json
```

### 2. Report Test Results (WAP Pattern)

After running `dbt test`, report results to Tessera:

```bash
# Report results from any dbt project
curl -X POST "http://localhost:8000/api/v1/assets/{asset_id}/audit-results" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "passed",
    "triggered_by": "dbt_test",
    "guarantees_checked": 15,
    "guarantees_passed": 15,
    "guarantees_failed": 0
  }'
```

### 3. Cross-Team Dependencies

The projects demonstrate realistic cross-team dependencies:
- Marketing models depend on Core's `dim_customers` and `fct_orders`
- Finance models report on Core's revenue data
- Breaking changes in Core require acknowledgment from Marketing and Finance teams

## Tessera Metadata

Each model includes Tessera-specific metadata in schema.yml:

```yaml
models:
  - name: dim_customers
    meta:
      tessera:
        owner_team: data-platform
        compatibility_mode: backward
        consumers:
          - team: marketing-analytics
          - team: finance-analytics
```

## Compatibility Modes

| Mode | Description |
|------|-------------|
| backward | New schema must be readable by old consumers (default) |
| forward | Old schema must be readable by new consumers |
| full | Both backward and forward compatible |
| none | No compatibility checking (notify only) |
