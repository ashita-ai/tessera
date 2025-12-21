"""
BigQuery Staging Table Validation Example
==========================================

Demonstrates how to validate BigQuery staging tables against Tessera contracts
before deploying to production.

Prerequisites:
- Google Cloud credentials configured (ADC or service account)
- tessera[bigquery] installed: pip install tessera[bigquery]
- A BigQuery dataset with tables to validate

Run with: uv run python examples/bigquery_validation.py
"""

import asyncio
from typing import Any

# This example shows the BigQuery connector API
# In production, you would use: from tessera.connectors.bigquery import BigQueryConnector

# Sample contract schema for comparison
PRODUCTION_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "integer"},
        "email": {"type": "string", "format": "email"},
        "name": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
    },
    "required": ["customer_id", "email"],
}


async def example_1_get_table_schema():
    """
    EXAMPLE 1: Get BigQuery Table Schema as JSON Schema
    ---------------------------------------------------
    Fetch a BigQuery table's schema and convert it to JSON Schema format.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Get BigQuery Table Schema")
    print("=" * 70)

    print("""
To fetch a BigQuery table schema:

    from tessera.connectors.bigquery import BigQueryConnector

    # Initialize connector
    connector = BigQueryConnector(
        project="my-gcp-project",
        location="US"
    )

    # Get table schema as JSON Schema
    schema = await connector.get_table_schema(
        "my-project.staging.customers"
    )

    print(json.dumps(schema, indent=2))

Example output:

    {
      "type": "object",
      "properties": {
        "customer_id": {"type": "integer"},
        "email": {"type": "string"},
        "name": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"}
      },
      "required": ["customer_id", "email"],
      "$comment": "Schema for my-project.staging.customers"
    }
""")


async def example_2_validate_staging():
    """
    EXAMPLE 2: Validate Staging Table Against Contract
    --------------------------------------------------
    Compare a staging table's schema against the production contract.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Validate Staging Table Against Contract")
    print("=" * 70)

    print("""
To validate a staging table against a contract:

    from tessera.connectors.bigquery import BigQueryConnector, validate_staging_table

    # Option 1: Using the convenience function
    result = await validate_staging_table(
        staging_ref="my-project.staging.customers_v2",
        contract_schema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
                "email": {"type": "string"},
                "name": {"type": "string"}
            },
            "required": ["customer_id", "email"]
        }
    )

    if result["is_compatible"]:
        print("Staging table matches contract!")
    else:
        print("Breaking changes detected:")
        for change in result["breaking_changes"]:
            print(f"  - {change['message']}")

    # Option 2: Using the connector directly
    connector = BigQueryConnector(project="my-project")
    result = await connector.compare_with_contract(
        table_ref="my-project.staging.customers_v2",
        contract_schema=contract_schema
    )

Example output when compatible:

    {
      "table_ref": "my-project.staging.customers_v2",
      "is_compatible": true,
      "breaking_changes": [],
      "table_schema": {...}
    }

Example output with breaking changes:

    {
      "table_ref": "my-project.staging.customers_v2",
      "is_compatible": false,
      "breaking_changes": [
        {
          "kind": "type_changed",
          "path": "properties.customer_id.type",
          "message": "Type changed from 'integer' to 'string'"
        },
        {
          "kind": "field_removed",
          "path": "properties.email",
          "message": "Required field 'email' was removed"
        }
      ],
      "table_schema": {...}
    }
""")


async def example_3_cicd_integration():
    """
    EXAMPLE 3: CI/CD Integration
    ----------------------------
    Use BigQuery validation in your CI/CD pipeline.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: CI/CD Integration")
    print("=" * 70)

    print("""
Integrate BigQuery staging validation into your CI/CD pipeline:

```python
# scripts/validate_staging.py
import asyncio
import sys
import httpx
from tessera.connectors.bigquery import BigQueryConnector

async def main():
    # Get the contract from Tessera
    client = httpx.Client()
    resp = client.get(
        f"{TESSERA_URL}/api/v1/contracts/{CONTRACT_ID}",
        headers={"Authorization": f"Bearer {API_KEY}"}
    )
    contract = resp.json()

    # Validate staging table
    connector = BigQueryConnector(project=GCP_PROJECT)
    result = await connector.compare_with_contract(
        table_ref=f"{GCP_PROJECT}.staging.{TABLE_NAME}",
        contract_schema=contract["schema_def"]
    )

    if not result["is_compatible"]:
        print("VALIDATION FAILED: Breaking changes detected!")
        for bc in result["breaking_changes"]:
            print(f"  - {bc['message']}")
        sys.exit(1)

    print("Staging table validated successfully!")

asyncio.run(main())
```

GitHub Actions workflow:

```yaml
name: Validate Staging Tables

on:
  push:
    branches: [staging]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_CREDENTIALS }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - run: pip install tessera[bigquery]

      - name: Validate staging tables
        env:
          TESSERA_URL: ${{ vars.TESSERA_URL }}
          TESSERA_API_KEY: ${{ secrets.TESSERA_API_KEY }}
          GCP_PROJECT: ${{ vars.GCP_PROJECT }}
        run: python scripts/validate_staging.py
```
""")


async def example_4_list_tables():
    """
    EXAMPLE 4: List Tables in a Dataset
    -----------------------------------
    Discover tables in a BigQuery dataset.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: List Tables in a Dataset")
    print("=" * 70)

    print("""
List all tables in a BigQuery dataset:

    from tessera.connectors.bigquery import BigQueryConnector

    connector = BigQueryConnector(project="my-project")

    # List tables in the staging dataset
    tables = await connector.list_tables("my-project.staging")

    print("Tables in staging dataset:")
    for table in tables:
        print(f"  - {table}")

Example output:

    Tables in staging dataset:
      - customers_v2
      - orders_v2
      - products_v2

This is useful for discovering which tables need validation
or for automating schema extraction.
""")


async def example_5_type_mapping():
    """
    EXAMPLE 5: BigQuery to JSON Schema Type Mapping
    -----------------------------------------------
    How BigQuery types are converted to JSON Schema types.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 5: BigQuery to JSON Schema Type Mapping")
    print("=" * 70)

    print("""
BigQuery types are mapped to JSON Schema types as follows:

| BigQuery Type    | JSON Schema Type | Notes                    |
|------------------|------------------|--------------------------|
| INT64, INTEGER   | integer          |                          |
| FLOAT64, FLOAT   | number           |                          |
| NUMERIC, DECIMAL | number           |                          |
| STRING           | string           |                          |
| BOOL, BOOLEAN    | boolean          |                          |
| DATE             | string           | format: "date"           |
| DATETIME         | string           | format: "date-time"      |
| TIMESTAMP        | string           | format: "date-time"      |
| TIME             | string           | format: "time"           |
| BYTES            | string           |                          |
| GEOGRAPHY        | object           |                          |
| JSON             | object           |                          |
| STRUCT, RECORD   | object           | with nested properties   |
| ARRAY            | array            | with items schema        |

Nested STRUCT example:

    BigQuery:
        address STRUCT<
            street STRING,
            city STRING,
            zip STRING
        >

    JSON Schema:
        "address": {
            "type": "object",
            "properties": {
                "street": {"type": "string"},
                "city": {"type": "string"},
                "zip": {"type": "string"}
            }
        }

REPEATED fields become arrays:

    BigQuery:
        tags ARRAY<STRING>

    JSON Schema:
        "tags": {
            "type": "array",
            "items": {"type": "string"}
        }
""")


async def main():
    """Run all BigQuery validation examples."""
    print("\n" + "=" * 70)
    print("  BIGQUERY STAGING TABLE VALIDATION EXAMPLES")
    print("=" * 70)

    await example_1_get_table_schema()
    await example_2_validate_staging()
    await example_3_cicd_integration()
    await example_4_list_tables()
    await example_5_type_mapping()

    print("\n" + "=" * 70)
    print("For actual usage, install BigQuery support:")
    print("  pip install tessera[bigquery]")
    print("\nThen import the connector:")
    print("  from tessera.connectors.bigquery import BigQueryConnector")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
