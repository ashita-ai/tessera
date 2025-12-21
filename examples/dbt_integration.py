"""
dbt Integration Examples
========================

Demonstrates how to use Tessera with dbt for CI/CD schema validation.

These examples show the CLI commands and Python equivalents for:
1. Syncing dbt models to Tessera assets
2. Checking for breaking changes in CI
3. Registering as a consumer of upstream sources

Prerequisites:
- dbt project with a compiled manifest.json (run `dbt compile` or `dbt build`)
- Tessera server running (docker compose up -d)
- TESSERA_URL and TESSERA_API_KEY environment variables set

Run with: uv run python examples/dbt_integration.py
"""

import json
import os
import tempfile
from pathlib import Path

# Sample dbt manifest.json structure for demonstration
SAMPLE_DBT_MANIFEST = {
    "metadata": {
        "dbt_version": "1.7.0",
        "project_name": "analytics",
    },
    "nodes": {
        "model.analytics.dim_customers": {
            "resource_type": "model",
            "name": "dim_customers",
            "schema": "analytics",
            "database": "warehouse",
            "columns": {
                "customer_id": {
                    "name": "customer_id",
                    "data_type": "integer",
                    "description": "Primary key",
                },
                "email": {
                    "name": "email",
                    "data_type": "varchar",
                    "description": "Customer email address",
                },
                "name": {
                    "name": "name",
                    "data_type": "varchar",
                    "description": "Customer full name",
                },
                "created_at": {
                    "name": "created_at",
                    "data_type": "timestamp",
                    "description": "Account creation timestamp",
                },
            },
            "description": "Customer dimension table with core attributes",
        },
        "model.analytics.fct_orders": {
            "resource_type": "model",
            "name": "fct_orders",
            "schema": "analytics",
            "database": "warehouse",
            "columns": {
                "order_id": {
                    "name": "order_id",
                    "data_type": "integer",
                    "description": "Primary key",
                },
                "customer_id": {
                    "name": "customer_id",
                    "data_type": "integer",
                    "description": "Foreign key to dim_customers",
                },
                "order_total": {
                    "name": "order_total",
                    "data_type": "numeric",
                    "description": "Total order amount",
                },
                "order_date": {
                    "name": "order_date",
                    "data_type": "date",
                    "description": "Order date",
                },
            },
            "description": "Fact table for orders",
            "depends_on": {
                "nodes": ["model.analytics.dim_customers"],
            },
        },
        "source.analytics.raw.customers": {
            "resource_type": "source",
            "name": "customers",
            "source_name": "raw",
            "schema": "raw",
            "database": "warehouse",
            "columns": {
                "id": {"name": "id", "data_type": "integer"},
                "email": {"name": "email", "data_type": "varchar"},
                "first_name": {"name": "first_name", "data_type": "varchar"},
                "last_name": {"name": "last_name", "data_type": "varchar"},
            },
        },
    },
    "sources": {
        "source.analytics.raw.customers": {
            "resource_type": "source",
            "name": "customers",
            "source_name": "raw",
            "schema": "raw",
            "database": "warehouse",
        },
    },
}


def create_sample_manifest():
    """Create a temporary manifest.json for demonstration."""
    temp_dir = tempfile.mkdtemp()
    manifest_path = Path(temp_dir) / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(SAMPLE_DBT_MANIFEST, f, indent=2)
    return manifest_path


def example_1_sync_models():
    """
    EXAMPLE 1: Sync dbt Models to Tessera
    -------------------------------------
    This registers your dbt models as Tessera assets and publishes
    their schemas as contracts.

    CLI equivalent:
        tessera dbt sync --manifest target/manifest.json --team-id <uuid>
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Sync dbt Models to Tessera (CLI)")
    print("=" * 70)

    manifest_path = create_sample_manifest()

    print(f"""
To sync your dbt models to Tessera, run:

    tessera dbt sync \\
        --manifest {manifest_path} \\
        --team-id $TEAM_ID \\
        --tessera-url http://localhost:8000

This will:
1. Parse the manifest.json to extract model schemas
2. Create/update assets for each model (fqn: database.schema.model_name)
3. Publish contracts with the column schemas
4. Track sources as upstream dependencies

Example output:
    Syncing dbt models...
    Created asset: warehouse.analytics.dim_customers
    Published contract v1.0.0 for dim_customers
    Created asset: warehouse.analytics.fct_orders
    Published contract v1.0.0 for fct_orders
    Sync complete: 2 models synced
""")

    # Clean up
    os.unlink(manifest_path)
    os.rmdir(os.path.dirname(manifest_path))


def example_2_check_breaking_changes():
    """
    EXAMPLE 2: Check for Breaking Changes in CI
    -------------------------------------------
    Before merging a PR, check if schema changes would break consumers.

    CLI equivalent:
        tessera dbt check --manifest target/manifest.json --team-id <uuid>
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Check for Breaking Changes in CI (CLI)")
    print("=" * 70)

    manifest_path = create_sample_manifest()

    print(f"""
To check for breaking changes in your CI pipeline, run:

    tessera dbt check \\
        --manifest {manifest_path} \\
        --team-id $TEAM_ID \\
        --tessera-url http://localhost:8000 \\
        --fail-on-breaking

This will:
1. Compare the manifest schemas against registered contracts
2. Detect any breaking changes (removed columns, type changes, etc.)
3. Exit with code 1 if breaking changes found (fails the CI)

Example output when changes are compatible:
    Checking dbt models for breaking changes...
    dim_customers: compatible (added loyalty_tier column)
    fct_orders: no changes
    Check complete: 0 breaking changes

Example output when changes are breaking:
    Checking dbt models for breaking changes...
    dim_customers: BREAKING
      - Removed required field: email
      - Changed type of customer_id: integer -> string
    fct_orders: no changes
    Check complete: 2 breaking changes
    ERROR: Breaking changes detected. Run with --create-proposals to notify consumers.
""")

    # Clean up
    os.unlink(manifest_path)
    os.rmdir(os.path.dirname(manifest_path))


def example_3_create_proposals_for_breaking_changes():
    """
    EXAMPLE 3: Create Proposals for Breaking Changes
    ------------------------------------------------
    When breaking changes are detected, create proposals so consumers
    can be notified and acknowledge before the change is deployed.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Create Proposals for Breaking Changes (CLI)")
    print("=" * 70)

    print("""
When you want to proceed with breaking changes, create proposals:

    tessera dbt check \\
        --manifest target/manifest.json \\
        --team-id $TEAM_ID \\
        --create-proposals

This will:
1. Detect breaking changes
2. Create Proposal records in Tessera
3. Notify consumers via webhooks (if configured)
4. Block until all consumers acknowledge

Example output:
    Checking dbt models for breaking changes...
    dim_customers: BREAKING
      - Removed required field: email

    Creating proposals for breaking changes...
    Created proposal abc123 for dim_customers
      - Waiting for acknowledgment from: ml-team, reporting-team

    Proposals created. Consumers must acknowledge before merging.
    View proposals: https://tessera.example.com/proposals/abc123
""")


def example_4_register_sources():
    """
    EXAMPLE 4: Register as Consumer of Upstream Sources
    ---------------------------------------------------
    Register your dbt project as a consumer of upstream data sources
    so you get notified when they change.

    CLI equivalent:
        tessera dbt register --manifest target/manifest.json --team-id <uuid>
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Register as Consumer of Upstream Sources (CLI)")
    print("=" * 70)

    print("""
To register as a consumer of your upstream sources, run:

    tessera dbt register \\
        --manifest target/manifest.json \\
        --team-id $TEAM_ID

This will:
1. Parse source definitions from manifest.json
2. Find matching assets in Tessera
3. Register your team as a consumer of each source

Example output:
    Registering as consumer of upstream sources...
    Registered for: warehouse.raw.customers
    Registered for: warehouse.raw.orders
    Registration complete: 2 sources registered

Now when the upstream teams make breaking changes to these tables,
you'll be notified and asked to acknowledge before they can deploy.
""")


def example_5_github_action():
    """
    EXAMPLE 5: GitHub Action for dbt CI/CD
    --------------------------------------
    Integrate Tessera into your GitHub workflow to automatically
    check schemas on every PR.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 5: GitHub Action for dbt CI/CD")
    print("=" * 70)

    print("""
Add this to your .github/workflows/dbt-ci.yml:

```yaml
name: dbt CI

on:
  pull_request:
    paths:
      - 'models/**'
      - 'dbt_project.yml'

jobs:
  schema-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup dbt
        uses: dbt-labs/dbt-setup@v1

      - name: Compile dbt
        run: dbt compile

      - name: Check for breaking schema changes
        uses: ashita-ai/tessera/.github/actions/dbt-check@main
        with:
          tessera-url: ${{ secrets.TESSERA_URL }}
          tessera-api-key: ${{ secrets.TESSERA_API_KEY }}
          team-id: ${{ vars.TEAM_ID }}
          manifest-path: target/manifest.json
          fail-on-breaking: true
```

This action will:
1. Comment on the PR with any breaking changes detected
2. Fail the check if breaking changes are found
3. Provide a link to create proposals if needed

Example PR comment:
    ## Schema Change Analysis

    | Model | Status | Changes |
    |-------|--------|---------|
    | dim_customers | BREAKING | Removed email column |
    | fct_orders | Compatible | No changes |

    **Action required**: This PR contains breaking changes.
    [Create proposals](https://tessera.example.com/...) to notify consumers.
""")


def main():
    """Run all dbt integration examples."""
    print("\n" + "=" * 70)
    print("  dbt INTEGRATION EXAMPLES")
    print("=" * 70)

    example_1_sync_models()
    example_2_check_breaking_changes()
    example_3_create_proposals_for_breaking_changes()
    example_4_register_sources()
    example_5_github_action()

    print("\n" + "=" * 70)
    print("For more information, see:")
    print("  - tessera dbt --help")
    print("  - tessera dbt sync --help")
    print("  - tessera dbt check --help")
    print("  - tessera dbt register --help")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
