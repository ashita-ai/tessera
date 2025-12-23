#!/usr/bin/env python3
"""Import sample dbt manifest into Tessera on Docker startup."""

import json
import os
import sys
import time
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MANIFEST_PATH = Path("/app/examples/data/manifest.json")
TEAM_NAME = "data-platform"


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


def import_manifest(team_id: str) -> bool:
    """Import the dbt manifest by creating assets directly."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found at {MANIFEST_PATH}")
        return False

    manifest = json.loads(MANIFEST_PATH.read_text())
    assets_created = 0
    assets_failed = 0

    # Process nodes (models)
    nodes = manifest.get("nodes", {})
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue

        # Build FQN from dbt metadata
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()

        # Build metadata
        metadata = {
            "dbt_node_id": node_id,
            "resource_type": resource_type,
            "description": node.get("description", ""),
            "tags": node.get("tags", []),
        }

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
                assets_created += 1
                print(f"  Created asset: {fqn}")
            elif resp.status_code == 409:
                print(f"  Asset exists: {fqn}")
            else:
                print(f"  Failed to create {fqn}: {resp.status_code}")
                assets_failed += 1
        except Exception as e:
            print(f"  Error creating {fqn}: {e}")
            assets_failed += 1

    # Process sources
    sources = manifest.get("sources", {})
    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()

        metadata = {
            "dbt_source_id": source_id,
            "resource_type": "source",
            "description": source.get("description", ""),
        }

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
                assets_created += 1
                print(f"  Created asset: {fqn}")
            elif resp.status_code == 409:
                print(f"  Asset exists: {fqn}")
            else:
                print(f"  Failed to create {fqn}: {resp.status_code}")
                assets_failed += 1
        except Exception as e:
            print(f"  Error creating {fqn}: {e}")
            assets_failed += 1

    print("Manifest import complete!")
    print(f"  Assets created: {assets_created}")
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
