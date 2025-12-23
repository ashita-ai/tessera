#!/usr/bin/env python3
"""Report dbt test results to Tessera.

This script parses dbt's run_results.json and reports test outcomes to Tessera
for WAP (Write-Audit-Publish) pattern tracking.

Usage:
    # After dbt test/run
    python scripts/report_to_tessera.py

    # Or as on-run-end hook in dbt_project.yml:
    # on-run-end:
    #   - "python scripts/report_to_tessera.py"

Environment variables:
    TESSERA_URL: Base URL of Tessera API (default: http://localhost:8000)
    TESSERA_API_KEY: API key for authentication
    DBT_TARGET_PATH: Path to dbt target directory (default: target)

Exit codes:
    0: Success (results reported or no tests found)
    1: Error reporting results to Tessera
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# Configuration from environment
TESSERA_URL = os.getenv("TESSERA_URL", "http://localhost:8000")
TESSERA_API_KEY = os.getenv("TESSERA_API_KEY")
DBT_TARGET_PATH = Path(os.getenv("DBT_TARGET_PATH", "target"))


def load_run_results() -> dict[str, Any] | None:
    """Load dbt run_results.json from the target directory."""
    results_path = DBT_TARGET_PATH / "run_results.json"
    if not results_path.exists():
        print(f"No run_results.json found at {results_path}")
        return None

    with open(results_path) as f:
        return json.load(f)


def load_manifest() -> dict[str, Any] | None:
    """Load dbt manifest.json to map test node_ids to model FQNs."""
    manifest_path = DBT_TARGET_PATH / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest.json found at {manifest_path}")
        return None

    with open(manifest_path) as f:
        return json.load(f)


def get_model_fqn_for_test(test_node: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    """Get the FQN of the model that a test depends on."""
    depends_on = test_node.get("depends_on", {}).get("nodes", [])

    # Find the first model/source this test depends on
    for node_id in depends_on:
        if node_id.startswith("model.") or node_id.startswith("source."):
            node = manifest.get("nodes", {}).get(node_id) or manifest.get("sources", {}).get(
                node_id
            )
            if node:
                database = node.get("database", "")
                schema = node.get("schema", "")
                name = node.get("name", "")
                return f"{database}.{schema}.{name}".lower()
    return None


def extract_test_results(
    run_results: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Extract test results grouped by model FQN.

    Returns:
        Dict mapping model FQN to {
            "passed": int,
            "failed": int,
            "errored": int,
            "skipped": int,
            "failed_tests": [{"name": str, "message": str}]
        }
    """
    results_by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "errored": 0, "skipped": 0, "failed_tests": []}
    )

    for result in run_results.get("results", []):
        unique_id = result.get("unique_id", "")
        if not unique_id.startswith("test."):
            continue

        # Get test node from manifest
        test_node = manifest.get("nodes", {}).get(unique_id, {})
        if not test_node:
            continue

        # Find which model this test is for
        model_fqn = get_model_fqn_for_test(test_node, manifest)
        if not model_fqn:
            continue

        status = result.get("status", "").lower()
        model_results = results_by_model[model_fqn]

        if status == "pass":
            model_results["passed"] += 1
        elif status == "fail":
            model_results["failed"] += 1
            model_results["failed_tests"].append(
                {
                    "name": test_node.get("name", unique_id),
                    "message": result.get("message", "Test failed"),
                    "unique_id": unique_id,
                }
            )
        elif status == "error":
            model_results["errored"] += 1
            model_results["failed_tests"].append(
                {
                    "name": test_node.get("name", unique_id),
                    "message": result.get("message", "Test errored"),
                    "unique_id": unique_id,
                }
            )
        elif status == "skipped":
            model_results["skipped"] += 1

    return dict(results_by_model)


def get_asset_id_by_fqn(fqn: str) -> str | None:
    """Look up Tessera asset ID by FQN."""
    headers = {"Authorization": f"Bearer {TESSERA_API_KEY}"} if TESSERA_API_KEY else {}

    try:
        response = requests.get(
            f"{TESSERA_URL}/api/v1/assets",
            params={"fqn": fqn},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        assets = response.json()
        if assets:
            return assets[0].get("id")
    except requests.RequestException as e:
        print(f"Failed to look up asset {fqn}: {e}")
    return None


def report_to_tessera(
    asset_id: str, model_fqn: str, results: dict[str, Any], invocation_id: str
) -> bool:
    """Report test results for a single asset to Tessera."""
    total_checked = results["passed"] + results["failed"] + results["errored"]
    total_failed = results["failed"] + results["errored"]

    if total_checked == 0:
        return True  # No tests to report

    # Determine status
    if total_failed > 0:
        status = "failed"
    elif results["skipped"] > 0 and results["passed"] == 0:
        status = "partial"
    else:
        status = "passed"

    payload = {
        "status": status,
        "guarantees_checked": total_checked,
        "guarantees_passed": results["passed"],
        "guarantees_failed": total_failed,
        "triggered_by": "dbt_test",
        "run_id": invocation_id,
        "details": {
            "failed_tests": results["failed_tests"],
            "skipped": results["skipped"],
        },
        "run_at": datetime.utcnow().isoformat() + "Z",
    }

    headers = {"Authorization": f"Bearer {TESSERA_API_KEY}"} if TESSERA_API_KEY else {}
    headers["Content-Type"] = "application/json"

    try:
        response = requests.post(
            f"{TESSERA_URL}/api/v1/assets/{asset_id}/audit-results",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        print(f"  Reported: {model_fqn} - {status} ({results['passed']}/{total_checked} passed)")
        return True
    except requests.RequestException as e:
        print(f"  Failed to report {model_fqn}: {e}")
        return False


def main() -> int:
    """Main entry point."""
    print("Tessera dbt Test Reporter")
    print("=" * 40)

    # Load dbt artifacts
    run_results = load_run_results()
    if not run_results:
        print("No run results found. Exiting.")
        return 0

    manifest = load_manifest()
    if not manifest:
        print("No manifest found. Exiting.")
        return 0

    invocation_id = run_results.get("metadata", {}).get("invocation_id", "unknown")
    print(f"Invocation ID: {invocation_id}")

    # Extract test results by model
    results_by_model = extract_test_results(run_results, manifest)
    if not results_by_model:
        print("No test results found.")
        return 0

    print(f"Found test results for {len(results_by_model)} models")
    print()

    # Report to Tessera
    success_count = 0
    error_count = 0

    for model_fqn, results in results_by_model.items():
        asset_id = get_asset_id_by_fqn(model_fqn)
        if not asset_id:
            print(f"  Skipping {model_fqn}: not found in Tessera")
            continue

        if report_to_tessera(asset_id, model_fqn, results, invocation_id):
            success_count += 1
        else:
            error_count += 1

    print()
    print(f"Results: {success_count} reported, {error_count} failed")

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
