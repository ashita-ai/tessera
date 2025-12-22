"""
Staging Table Validation Example
================================

Demonstrates validating local Parquet files (simulating staging tables)
against Tessera contracts before promoting to production.

This example:
1. Creates a contract in Tessera for the customers table
2. Validates a compatible staging file (should pass)
3. Validates a breaking staging file (should fail with details)

Prerequisites:
- Tessera server running: docker compose up -d
- Sample data generated: uv run python examples/data/generate_sample_data.py

Run with: uv run python examples/staging_validation.py
"""

import asyncio
import json
import os
from pathlib import Path

import httpx

# Tessera API
BASE_URL = "http://localhost:8000/api/v1"
API_KEY = os.environ.get("TESSERA_API_KEY", "tessera-dev-key")
CLIENT = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {API_KEY}"})

# Sample data directory
DATA_DIR = Path(__file__).parent / "data"

# The contract schema for customers v1.0.0
CUSTOMERS_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "integer"},
        "email": {"type": "string"},
        "name": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
    },
    "required": ["customer_id", "email"],
}


def setup_tessera():
    """Create team, asset, and contract in Tessera."""
    print("Setting up Tessera resources...")

    # Create team
    resp = CLIENT.post(f"{BASE_URL}/teams", json={"name": "data-platform"})
    if resp.status_code == 201:
        team = resp.json()
    else:
        teams_resp = CLIENT.get(f"{BASE_URL}/teams").json()
        teams = teams_resp.get("results", teams_resp)
        team = next((t for t in teams if t["name"] == "data-platform"), None)
        if not team:
            raise Exception("Could not create or find data-platform team")

    # Create asset
    resp = CLIENT.post(
        f"{BASE_URL}/assets",
        json={
            "fqn": "warehouse.staging.customers",
            "owner_team_id": team["id"],
        },
    )
    if resp.status_code == 201:
        asset = resp.json()
    else:
        assets_resp = CLIENT.get(f"{BASE_URL}/assets").json()
        assets = assets_resp.get("results", assets_resp)
        asset = next((a for a in assets if a["fqn"] == "warehouse.staging.customers"), None)
        if not asset:
            raise Exception("Could not create or find asset")

    # Publish contract
    contracts = CLIENT.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json()
    if not any(c["status"] == "active" for c in contracts):
        resp = CLIENT.post(
            f"{BASE_URL}/assets/{asset['id']}/contracts",
            params={"published_by": team["id"]},
            json={
                "version": "1.0.0",
                "schema": CUSTOMERS_CONTRACT_SCHEMA,
                "compatibility_mode": "backward",
            },
        )
        if resp.status_code != 201:
            raise Exception(f"Could not publish contract: {resp.text}")

    print(f"  Team: {team['name']}")
    print(f"  Asset: {asset['fqn']}")
    print(f"  Contract: v1.0.0")
    print()

    return asset


async def validate_staging_file(file_path: Path, contract_schema: dict) -> dict:
    """Validate a local Parquet file against a contract schema.

    This uses DuckDB to read the file and compare schemas.
    """
    from tessera.connectors.duckdb import DuckDBConnector

    connector = DuckDBConnector()
    result = await connector.compare_with_contract(
        str(file_path),
        contract_schema,
    )
    return result


async def example_1_validate_matching_file(asset: dict):
    """
    EXAMPLE 1: Validate a Matching Staging File
    -------------------------------------------
    The staging file matches the contract exactly.
    """
    print("=" * 70)
    print("EXAMPLE 1: Validate Matching Staging File")
    print("=" * 70)

    file_path = DATA_DIR / "customers_v1.parquet"
    print(f"\nValidating: {file_path}")
    print(f"Against contract schema...")

    result = await validate_staging_file(file_path, CUSTOMERS_CONTRACT_SCHEMA)

    print(f"\nResult: {'COMPATIBLE' if result['is_compatible'] else 'BREAKING'}")

    if result["is_compatible"]:
        print("  The staging file matches the contract.")
        print("  Safe to promote to production.")
    else:
        print("  Breaking changes detected:")
        for bc in result["breaking_changes"]:
            print(f"    - {bc['message']}")

    return result


async def example_2_validate_compatible_change(asset: dict):
    """
    EXAMPLE 2: Validate a Backward-Compatible Change
    ------------------------------------------------
    The staging file has a new optional field (loyalty_tier).
    This is backward compatible.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Validate Backward-Compatible Change")
    print("=" * 70)

    file_path = DATA_DIR / "customers_v2_compatible.parquet"
    print(f"\nValidating: {file_path}")
    print("This file adds a new optional 'loyalty_tier' field.")

    result = await validate_staging_file(file_path, CUSTOMERS_CONTRACT_SCHEMA)

    print(f"\nResult: {'COMPATIBLE' if result['is_compatible'] else 'BREAKING'}")

    if result["is_compatible"]:
        print("  Adding optional fields is backward compatible!")
        print("  The new schema can be published as a minor version bump.")
    else:
        print("  Unexpected breaking changes:")
        for bc in result["breaking_changes"]:
            print(f"    - {bc['message']}")

    # Show the detected schema
    print("\n  Detected schema from file:")
    for prop, details in result["table_schema"]["properties"].items():
        print(f"    - {prop}: {details.get('type', 'unknown')}")

    return result


async def example_3_detect_breaking_changes(asset: dict):
    """
    EXAMPLE 3: Detect Breaking Changes
    ----------------------------------
    The staging file has breaking changes:
    - 'email' field removed
    - 'customer_id' changed from integer to string
    - 'name' renamed to 'full_name'
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Detect Breaking Changes")
    print("=" * 70)

    file_path = DATA_DIR / "customers_v2_breaking.parquet"
    print(f"\nValidating: {file_path}")
    print("This file has BREAKING changes:")
    print("  - 'email' field removed")
    print("  - 'customer_id' changed from integer to string")
    print("  - 'name' renamed to 'full_name'")

    result = await validate_staging_file(file_path, CUSTOMERS_CONTRACT_SCHEMA)

    print(f"\nResult: {'COMPATIBLE' if result['is_compatible'] else 'BREAKING'}")

    if not result["is_compatible"]:
        print("\n  Breaking changes detected:")
        for bc in result["breaking_changes"]:
            print(f"    [{bc['kind']}] {bc['message']}")

        print("\n  Action required:")
        print("    1. Create a proposal in Tessera")
        print("    2. Notify downstream consumers")
        print("    3. Wait for acknowledgments before deploying")

    return result


async def example_4_ci_pipeline_integration():
    """
    EXAMPLE 4: CI/CD Pipeline Integration
    -------------------------------------
    Shows how to use this in a CI/CD pipeline to gate deployments.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: CI/CD Pipeline Integration")
    print("=" * 70)

    print("""
In your CI/CD pipeline, validate staging tables before deployment:

```yaml
# .github/workflows/validate-staging.yml
name: Validate Staging Tables

on:
  push:
    branches: [staging]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install tessera[duckdb] httpx

      - name: Validate staging tables
        env:
          TESSERA_URL: ${{ vars.TESSERA_URL }}
          TESSERA_API_KEY: ${{ secrets.TESSERA_API_KEY }}
        run: |
          python -c "
          import asyncio
          from tessera.connectors.duckdb import validate_local_file

          # Get contract from Tessera API
          import httpx
          resp = httpx.get(
              f'{TESSERA_URL}/api/v1/contracts/{CONTRACT_ID}',
              headers={'Authorization': f'Bearer {API_KEY}'}
          )
          contract = resp.json()

          # Validate staging file
          result = asyncio.run(validate_local_file(
              'staging/customers.parquet',
              contract['schema_def']
          ))

          if not result['is_compatible']:
              print('BREAKING CHANGES DETECTED!')
              for bc in result['breaking_changes']:
                  print(f'  - {bc[\"message\"]}')
              exit(1)

          print('Staging table validated successfully!')
          "
```
""")


async def main():
    """Run all staging validation examples."""
    print("\n" + "=" * 70)
    print("  STAGING TABLE VALIDATION EXAMPLES")
    print("=" * 70 + "\n")

    # Check server is running
    try:
        CLIENT.get(f"{BASE_URL.replace('/api/v1', '')}/health")
    except httpx.ConnectError:
        print("Server not running. Start it with: docker compose up -d")
        return

    # Check sample data exists
    if not (DATA_DIR / "customers_v1.parquet").exists():
        print("Sample data not found. Generate it with:")
        print("  uv run python examples/data/generate_sample_data.py")
        return

    # Setup Tessera resources
    asset = setup_tessera()

    # Run examples
    await example_1_validate_matching_file(asset)
    await example_2_validate_compatible_change(asset)
    await example_3_detect_breaking_changes(asset)
    await example_4_ci_pipeline_integration()

    print("\n" + "=" * 70)
    print("  EXAMPLES COMPLETE")
    print("=" * 70)
    print("\nKey takeaways:")
    print("  1. Use DuckDB connector to validate local Parquet/CSV files")
    print("  2. Adding optional fields is backward compatible")
    print("  3. Removing fields or changing types is breaking")
    print("  4. Integrate with CI/CD to gate deployments")
    print()


if __name__ == "__main__":
    asyncio.run(main())
