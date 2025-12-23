#!/usr/bin/env python3
"""Build all demo dbt projects and generate manifests.

This script is called by Docker to build dbt projects before the seeder runs.
Each project generates a manifest.json that the seeder imports into Tessera.
"""

import subprocess
import sys
from pathlib import Path

# Demo dbt projects directory
DEMO_PROJECTS_DIR = Path("/app/tests/fixtures/demo_dbt_projects")

# Projects to build with their team ownership
PROJECTS = [
    {"name": "core", "team": "data-platform"},
    {"name": "marketing", "team": "marketing-analytics"},
    {"name": "finance", "team": "finance-analytics"},
]


def build_project(project_dir: Path, project_name: str) -> bool:
    """Build a single dbt project."""
    print(f"\n{'='*60}")
    print(f"Building {project_name} project...")
    print(f"{'='*60}")

    # Install dependencies
    print("  Installing dbt deps...")
    deps_result = subprocess.run(
        ["dbt", "deps", "--profiles-dir", "."],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if deps_result.returncode != 0:
        print("  ERROR: dbt deps failed")
        print(deps_result.stderr)
        return False
    print("  Dependencies installed")

    # Build project (seeds, models, tests)
    print("  Running dbt build...")
    build_result = subprocess.run(
        ["dbt", "build", "--profiles-dir", "."],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )

    # Check if manifest was generated (even if some tests failed)
    manifest_path = project_dir / "target" / "manifest.json"
    if manifest_path.exists():
        print(f"  Manifest generated: {manifest_path}")

        # Parse output for summary
        output = build_result.stdout
        if "PASS=" in output:
            # Extract test counts
            for line in output.split("\n"):
                if "Done." in line and "PASS=" in line:
                    print(f"  {line.strip()}")
        return True
    else:
        print("  ERROR: No manifest generated")
        print(build_result.stderr)
        return False


def main() -> int:
    """Build all demo dbt projects."""
    print("=" * 60)
    print("Tessera Demo dbt Projects Builder")
    print("=" * 60)

    if not DEMO_PROJECTS_DIR.exists():
        print(f"ERROR: Demo projects directory not found: {DEMO_PROJECTS_DIR}")
        return 1

    successful = 0
    failed = 0

    for project in PROJECTS:
        project_dir = DEMO_PROJECTS_DIR / project["name"]
        if not project_dir.exists():
            print(f"\nWARNING: Project directory not found: {project_dir}")
            failed += 1
            continue

        if build_project(project_dir, project["name"]):
            successful += 1
        else:
            failed += 1

    # Summary
    print("\n" + "=" * 60)
    print("Build Summary")
    print("=" * 60)
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  Total: {len(PROJECTS)}")

    if successful > 0:
        print("\nManifests ready for import:")
        for project in PROJECTS:
            manifest_path = DEMO_PROJECTS_DIR / project["name"] / "target" / "manifest.json"
            if manifest_path.exists():
                print(f"  - {project['name']}: {manifest_path}")
                print(f"    Owner team: {project['team']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
