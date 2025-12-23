#!/usr/bin/env python3
"""Import sample dbt manifest into Tessera on Docker startup."""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MANIFEST_PATH = Path("/app/examples/data/manifest.json")
TEAM_NAME = "data-platform"

# dbt type to JSON Schema type mapping
TYPE_MAPPING = {
    # String types
    "string": "string",
    "text": "string",
    "varchar": "string",
    "char": "string",
    "character varying": "string",
    # Numeric types
    "integer": "integer",
    "int": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "int64": "integer",
    "int32": "integer",
    "number": "number",
    "numeric": "number",
    "decimal": "number",
    "float": "number",
    "double": "number",
    "real": "number",
    "float64": "number",
    # Boolean
    "boolean": "boolean",
    "bool": "boolean",
    # Date/time (represented as strings in JSON)
    "date": "string",
    "datetime": "string",
    "timestamp": "string",
    "timestamp_ntz": "string",
    "timestamp_tz": "string",
    "time": "string",
    # Other
    "json": "object",
    "jsonb": "object",
    "array": "array",
    "variant": "object",
    "object": "object",
}


def dbt_columns_to_json_schema(columns: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt column definitions to JSON Schema."""
    properties: dict[str, Any] = {}

    for col_name, col_info in columns.items():
        data_type = (col_info.get("data_type") or "string").lower()
        # Extract base type (e.g., "varchar(255)" -> "varchar")
        base_type = data_type.split("(")[0].strip()

        json_type = TYPE_MAPPING.get(base_type, "string")
        prop: dict[str, Any] = {"type": json_type}

        # Add description if present
        if col_info.get("description"):
            prop["description"] = col_info["description"]

        properties[col_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": [],
    }


def wait_for_api(max_attempts: int = 30) -> bool:
    """Wait for API to be ready."""
    for attempt in range(max_attempts):
        try:
            resp = httpx.get(f"{API_URL}/health", timeout=5)
            if resp.status_code == 200:
                print("API is ready!")
                return True
        except Exception:
            pass
        print(f"Attempt {attempt + 1}/{max_attempts} - API not ready yet...")
        time.sleep(2)
    return False


def get_or_create_team() -> str | None:
    """Get or create the default team."""
    # Try to create team
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/teams",
            json={"name": TEAM_NAME},
            timeout=10,
        )
        if resp.status_code == 201:
            team_id = resp.json()["id"]
            print(f"Created team '{TEAM_NAME}' with ID: {team_id}")
            return team_id
    except Exception as e:
        print(f"Could not create team: {e}")

    # Team might already exist, try to find it
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/teams",
            params={"name": TEAM_NAME},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                team_id = results[0]["id"]
                print(f"Found existing team '{TEAM_NAME}' with ID: {team_id}")
                return team_id
    except Exception as e:
        print(f"Could not find team: {e}")

    return None


def get_or_create_asset(fqn: str, team_id: str, metadata: dict[str, Any]) -> str | None:
    """Get existing asset or create new one, return asset ID."""
    # First try to get existing asset
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/assets",
            params={"fqn": fqn},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for asset in results:
                if asset.get("fqn") == fqn:
                    return asset["id"]
    except Exception:
        pass

    # Create new asset
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/assets",
            json={
                "fqn": fqn,
                "owner_team_id": team_id,
                "metadata": metadata,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return resp.json()["id"]
    except Exception:
        pass

    return None


def publish_contract(
    asset_id: str,
    team_id: str,
    schema_def: dict[str, Any],
    version: str = "1.0.0",
) -> tuple[bool, str]:
    """Publish a contract for an asset. Returns (success, message)."""
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json={
                "version": version,
                "schema": schema_def,
                "compatibility_mode": "backward",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, "created"
        elif resp.status_code == 409:
            return False, "already exists"
        else:
            return False, f"error {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, f"exception: {e}"


def import_manifest(team_id: str) -> bool:
    """Import the dbt manifest with full data - assets, contracts, and columns."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found at {MANIFEST_PATH}")
        return False

    manifest = json.loads(MANIFEST_PATH.read_text())
    assets_created = 0
    contracts_created = 0
    assets_failed = 0

    # Build FQN lookup for dependencies
    node_id_to_fqn: dict[str, str] = {}

    # First pass: collect all FQNs
    nodes = manifest.get("nodes", {})
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        node_id_to_fqn[node_id] = f"{database}.{schema}.{name}".lower()

    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        node_id_to_fqn[source_id] = f"{database}.{schema}.{name}".lower()

    print("\nImporting nodes (models)...")

    # Process nodes (models) with full metadata
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue

        fqn = node_id_to_fqn[node_id]
        columns = node.get("columns", {})
        depends_on = node.get("depends_on", {}).get("nodes", [])

        # Build comprehensive metadata
        metadata = {
            "dbt_node_id": node_id,
            "resource_type": resource_type,
            "description": node.get("description", ""),
            "tags": node.get("tags", []),
            "dbt_fqn": node.get("fqn", []),
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in columns.items()
            },
            "depends_on": [node_id_to_fqn.get(dep, dep) for dep in depends_on],
        }

        asset_id = get_or_create_asset(fqn, team_id, metadata)
        if asset_id:
            assets_created += 1
            print(f"  Created/found asset: {fqn}")

            # Publish contract with JSON Schema from columns
            if columns:
                schema_def = dbt_columns_to_json_schema(columns)
                success, msg = publish_contract(asset_id, team_id, schema_def)
                if success:
                    contracts_created += 1
                    print(f"    Published contract with {len(columns)} columns")
                else:
                    print(f"    Contract: {msg}")
        else:
            print(f"  Failed to create {fqn}")
            assets_failed += 1

    print("\nImporting sources...")

    # Process sources with full metadata
    for source_id, source in sources.items():
        fqn = node_id_to_fqn[source_id]
        columns = source.get("columns", {})

        metadata = {
            "dbt_source_id": source_id,
            "resource_type": "source",
            "source_name": source.get("source_name", ""),
            "description": source.get("description", ""),
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in columns.items()
            },
        }

        asset_id = get_or_create_asset(fqn, team_id, metadata)
        if asset_id:
            assets_created += 1
            print(f"  Created/found asset: {fqn}")

            # Publish contract if columns defined
            if columns:
                schema_def = dbt_columns_to_json_schema(columns)
                success, msg = publish_contract(asset_id, team_id, schema_def)
                if success:
                    contracts_created += 1
                    print(f"    Published contract with {len(columns)} columns")
                else:
                    print(f"    Contract: {msg}")
        else:
            print(f"  Failed to create {fqn}")
            assets_failed += 1

    print("\nManifest import complete!")
    print(f"  Assets created/found: {assets_created}")
    print(f"  Contracts published: {contracts_created}")
    print(f"  Assets failed: {assets_failed}")
    return assets_failed == 0


def main():
    """Main entry point."""
    print("=" * 50)
    print("Tessera Init: Importing sample dbt manifest")
    print("=" * 50)

    # Wait for API
    if not wait_for_api():
        print("Warning: API did not become ready, exiting")
        sys.exit(1)

    # Get or create team
    team_id = get_or_create_team()
    if not team_id:
        print("Error: Could not get or create team")
        sys.exit(1)

    # Import manifest
    if import_manifest(team_id):
        print("=" * 50)
        print("Init complete! Sample data imported successfully.")
        print("=" * 50)
    else:
        print("Warning: Manifest import failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
