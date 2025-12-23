#!/usr/bin/env python3
"""Seed demo data on Docker startup.

Creates:
- 5 teams (data-platform, marketing-analytics, finance-analytics, product-analytics, sales-ops)
- 12 users distributed across teams
- 220+ assets with contracts from dbt manifest
- Guarantees inferred from dbt tests (not_null, unique, accepted_values, dbt_utils, etc.)
- A handful of proposals (breaking changes in progress)
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

API_URL = "http://api:8000"
BOOTSTRAP_API_KEY = os.environ.get("BOOTSTRAP_API_KEY", "")


# Build headers with API key if available
def get_headers() -> dict[str, str]:
    """Get headers for API requests, including auth if configured."""
    headers = {"Content-Type": "application/json"}
    if BOOTSTRAP_API_KEY:
        headers["Authorization"] = f"Bearer {BOOTSTRAP_API_KEY}"
    return headers


# Default manifest path (synthetic)
MANIFEST_PATH = Path("/app/examples/data/manifest.json")
# Multi-project manifests from demo dbt projects
DBT_PROJECTS = {
    "core": {
        "manifest_path": Path("/app/tests/fixtures/demo_dbt_projects/core/target/manifest.json"),
        "owner_team": "data-platform",
    },
    "marketing": {
        "manifest_path": Path(
            "/app/tests/fixtures/demo_dbt_projects/marketing/target/manifest.json"
        ),
        "owner_team": "marketing-analytics",
    },
    "finance": {
        "manifest_path": Path("/app/tests/fixtures/demo_dbt_projects/finance/target/manifest.json"),
        "owner_team": "finance-analytics",
    },
}
MAX_RETRIES = 30
RETRY_DELAY = 2

# Teams to create
TEAMS = [
    {"name": "data-platform", "metadata": {"domain": "core", "slack_channel": "#data-platform"}},
    {
        "name": "marketing-analytics",
        "metadata": {"domain": "marketing", "slack_channel": "#marketing-data"},
    },
    {
        "name": "finance-analytics",
        "metadata": {"domain": "finance", "slack_channel": "#finance-data"},
    },
    {
        "name": "product-analytics",
        "metadata": {"domain": "product", "slack_channel": "#product-data"},
    },
    {"name": "sales-ops", "metadata": {"domain": "sales", "slack_channel": "#sales-data"}},
]

# Demo login users (admin:admin, team_admin:team_admin, user:user)
DEMO_USERS = [
    {
        "name": "Admin User",
        "email": "admin@test.com",
        "password": "admin",
        "role": "admin",
        "team": "data-platform",
    },
    {
        "name": "Team Admin",
        "email": "team_admin@test.com",
        "password": "team_admin",
        "role": "team_admin",
        "team": "data-platform",
    },
    {
        "name": "Regular User",
        "email": "user@test.com",
        "password": "user",
        "role": "user",
        "team": "marketing-analytics",
    },
]

# Users to create (12 users across 5 teams)
USERS = [
    # Data Platform (3 users)
    {"name": "Alice Chen", "email": "alice@company.com", "team": "data-platform"},
    {"name": "Bob Martinez", "email": "bob@company.com", "team": "data-platform"},
    {"name": "Charlie Kim", "email": "charlie@company.com", "team": "data-platform"},
    # Marketing Analytics (2 users)
    {"name": "Carol Johnson", "email": "carol@company.com", "team": "marketing-analytics"},
    {"name": "Dan Wilson", "email": "dan@company.com", "team": "marketing-analytics"},
    # Finance Analytics (2 users)
    {"name": "Emma Davis", "email": "emma@company.com", "team": "finance-analytics"},
    {"name": "Frank Brown", "email": "frank@company.com", "team": "finance-analytics"},
    # Product Analytics (3 users)
    {"name": "Grace Taylor", "email": "grace@company.com", "team": "product-analytics"},
    {"name": "Henry Anderson", "email": "henry@company.com", "team": "product-analytics"},
    {"name": "Ivy Thomas", "email": "ivy@company.com", "team": "product-analytics"},
    # Sales Ops (2 users)
    {"name": "Jack Moore", "email": "jack@company.com", "team": "sales-ops"},
    {"name": "Kate Jackson", "email": "kate@company.com", "team": "sales-ops"},
]


def wait_for_api() -> bool:
    """Wait for API to be healthy."""
    print("Waiting for API to be ready...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = httpx.get(f"{API_URL}/health", timeout=5)
            if resp.status_code == 200:
                print("API is ready!")
                return True
        except httpx.RequestError:
            pass
        print(f"Attempt {attempt + 1}/{MAX_RETRIES} - API not ready yet...")
        time.sleep(RETRY_DELAY)
    return False


def create_team(name: str, metadata: dict | None = None) -> str | None:
    """Create a team and return its ID."""
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/teams",
            json={"name": name, "metadata": metadata or {}},
            headers=get_headers(),
            timeout=10,
        )
        if resp.status_code == 201:
            team_id = resp.json()["id"]
            print(f"  Created team '{name}' -> {team_id[:8]}...")
            return team_id
        elif resp.status_code == 409:
            # Team exists, fetch it
            list_resp = httpx.get(
                f"{API_URL}/api/v1/teams?name={name}", headers=get_headers(), timeout=10
            )
            if list_resp.status_code == 200:
                results = list_resp.json().get("results", [])
                if results:
                    team_id = results[0]["id"]
                    print(f"  Team '{name}' exists -> {team_id[:8]}...")
                    return team_id
        print(f"  Failed to create team '{name}': {resp.status_code}")
    except httpx.RequestError as e:
        print(f"  Error creating team '{name}': {e}")
    return None


def create_user(
    name: str,
    email: str,
    team_id: str,
    password: str | None = None,
    role: str = "user",
) -> str | None:
    """Create a user and return their ID."""
    try:
        payload: dict = {"name": name, "email": email, "team_id": team_id, "role": role}
        if password:
            payload["password"] = password

        resp = httpx.post(
            f"{API_URL}/api/v1/users",
            json=payload,
            headers=get_headers(),
            timeout=10,
        )
        if resp.status_code == 201:
            user_id = resp.json()["id"]
            role_label = f" [{role}]" if role != "user" else ""
            print(f"  Created user '{name}' ({email}){role_label} -> {user_id[:8]}...")
            return user_id
        elif resp.status_code == 409:
            print(f"  User '{email}' already exists")
            return "exists"
        print(f"  Failed to create user '{name}': {resp.status_code} - {resp.text[:100]}")
    except httpx.RequestError as e:
        print(f"  Error creating user '{name}': {e}")
    return None


def import_manifest(default_team_id: str) -> dict | None:
    """Import the dbt manifest using the upload endpoint."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found at {MANIFEST_PATH}")
        return None

    print(f"Loading manifest from {MANIFEST_PATH}...")
    manifest = json.loads(MANIFEST_PATH.read_text())

    print("Importing manifest via /api/v1/sync/dbt/upload...")
    print("  (with auto_publish_contracts and meta.tessera ownership)")
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/sync/dbt/upload",
            json={
                "manifest": manifest,
                "owner_team_id": default_team_id,
                "conflict_mode": "ignore",
                "auto_publish_contracts": True,
                "auto_register_consumers": True,
                "infer_consumers_from_refs": True,
            },
            headers=get_headers(),
            timeout=180,
        )
        if resp.status_code == 200:
            result = resp.json()
            print("Import successful!")
            print(f"  Assets created: {result['assets']['created']}")
            print(f"  Assets updated: {result['assets']['updated']}")
            print(f"  Contracts published: {result['contracts']['published']}")
            print(f"  Registrations created: {result['registrations']['created']}")
            print(f"  Guarantees extracted: {result['guarantees_extracted']}")
            if result.get("ownership_warnings"):
                print(f"  Ownership warnings: {len(result['ownership_warnings'])}")
            return result
        else:
            print(f"Import failed: {resp.status_code} - {resp.text[:200]}")
    except httpx.RequestError as e:
        print(f"Error importing manifest: {e}")
    return None


def import_multi_project_manifests(team_ids: dict[str, str]) -> dict:
    """Import manifests from multiple dbt projects, each to its respective team.

    This demonstrates Tessera's multi-project support where different teams
    own different dbt projects.
    """
    print("\n[4a] Importing multi-project dbt manifests...")
    results = {
        "projects_imported": 0,
        "total_assets": 0,
        "total_contracts": 0,
        "total_guarantees": 0,
    }

    for project_name, config in DBT_PROJECTS.items():
        manifest_path = config["manifest_path"]
        owner_team = config["owner_team"]
        team_id = team_ids.get(owner_team)

        if not team_id:
            print(f"  Skipping {project_name}: team '{owner_team}' not found")
            continue

        if not manifest_path.exists():
            print(f"  Skipping {project_name}: manifest not found at {manifest_path}")
            continue

        print(f"\n  Importing {project_name} project -> {owner_team} team...")

        try:
            manifest = json.loads(manifest_path.read_text())
            resp = httpx.post(
                f"{API_URL}/api/v1/sync/dbt/upload",
                json={
                    "manifest": manifest,
                    "owner_team_id": team_id,
                    "conflict_mode": "ignore",
                    "auto_publish_contracts": True,
                    "auto_register_consumers": True,
                    "infer_consumers_from_refs": True,
                },
                headers=get_headers(),
                timeout=180,
            )

            if resp.status_code == 200:
                result = resp.json()
                results["projects_imported"] += 1
                results["total_assets"] += result["assets"]["created"]
                results["total_contracts"] += result["contracts"]["published"]
                results["total_guarantees"] += result.get("guarantees_extracted", 0)

                print(f"    Assets: {result['assets']['created']}")
                print(f"    Contracts: {result['contracts']['published']}")
                print(f"    Guarantees: {result.get('guarantees_extracted', 0)}")
            else:
                print(f"    Failed: {resp.status_code} - {resp.text[:100]}")

        except httpx.RequestError as e:
            print(f"    Error: {e}")

    return results


def create_proposals(team_ids: dict[str, str]) -> int:
    """Create a few proposals by publishing breaking changes to existing contracts."""
    print("\nCreating sample proposals (breaking changes)...")
    proposals_created = 0

    # Get registrations to find contracts with consumers
    try:
        reg_resp = httpx.get(
            f"{API_URL}/api/v1/registrations?limit=50", headers=get_headers(), timeout=10
        )
        if reg_resp.status_code != 200:
            print("  Could not fetch registrations")
            return 0

        registrations = reg_resp.json().get("results", [])
        if not registrations:
            print("  No registrations found")
            return 0

        # Get unique contract IDs from registrations
        contract_ids = list({r["contract_id"] for r in registrations})[:10]

        # Find contracts with good schemas for breaking changes
        target_contracts = []
        for contract_id in contract_ids:
            contract_resp = httpx.get(
                f"{API_URL}/api/v1/contracts/{contract_id}",
                headers=get_headers(),
                timeout=10,
            )
            if contract_resp.status_code != 200:
                continue

            contract = contract_resp.json()
            # Use 'schema' field from single contract response
            schema = contract.get("schema", {})
            props = schema.get("properties", {})

            if len(props) >= 2:  # Need at least 2 properties to remove one
                target_contracts.append(contract)
                if len(target_contracts) >= 3:
                    break

        if len(target_contracts) < 3:
            print(f"  Only found {len(target_contracts)} contracts with enough properties")
            return 0

        for contract in target_contracts:
            asset_id = contract["asset_id"]
            current_version = contract.get("version", "1.0.0")
            current_schema = contract.get("schema", {})

            # Get asset for owner_team_id and fqn
            asset_resp = httpx.get(
                f"{API_URL}/api/v1/assets/{asset_id}", headers=get_headers(), timeout=10
            )
            if asset_resp.status_code != 200:
                continue

            asset = asset_resp.json()
            fqn = asset["fqn"]
            owner_team_id = asset["owner_team_id"]

            if not current_schema.get("properties"):
                continue

            # Create a breaking change: remove a property
            props = current_schema.get("properties", {})
            if len(props) < 2:
                continue

            # Remove one property (breaking change)
            new_props = dict(props)
            removed_col = list(new_props.keys())[-1]  # Remove last property
            del new_props[removed_col]

            new_schema = {
                "type": "object",
                "properties": new_props,
                "required": current_schema.get("required", []),
            }

            # Bump major version
            parts = current_version.split(".")
            new_version = f"{int(parts[0]) + 1}.0.0"

            print(f"  Creating proposal for {fqn} (removing '{removed_col}')...")

            try:
                pub_resp = httpx.post(
                    f"{API_URL}/api/v1/assets/{asset_id}/contracts?published_by={owner_team_id}",
                    json={
                        "version": new_version,
                        "schema": new_schema,
                        "compatibility_mode": "backward",
                    },
                    headers=get_headers(),
                    timeout=30,
                )
                if pub_resp.status_code == 201:
                    result = pub_resp.json()
                    if result.get("action") == "proposal_created":
                        proposal_id = result["proposal"]["id"]
                        print(f"    Created proposal {proposal_id[:8]}...")
                        proposals_created += 1
                    else:
                        print(f"    No proposal needed (action: {result.get('action')})")
                else:
                    print(f"    Failed: {pub_resp.status_code}")
            except httpx.RequestError as e:
                print(f"    Error: {e}")

    except httpx.RequestError as e:
        print(f"  Error fetching assets: {e}")

    return proposals_created


def main() -> int:
    """Main entry point."""
    print("=" * 60)
    print("Tessera Demo Seeder")
    print("=" * 60)

    if not wait_for_api():
        print("ERROR: API did not become ready")
        return 1

    # Create teams
    print("\n[1/4] Creating teams...")
    team_ids: dict[str, str] = {}
    for team in TEAMS:
        team_id = create_team(team["name"], team.get("metadata"))
        if team_id:
            team_ids[team["name"]] = team_id

    if not team_ids:
        print("ERROR: Could not create any teams")
        return 1

    print(f"  Total: {len(team_ids)} teams")

    # Create demo users with login credentials first
    print("\n[2/5] Creating demo login users...")
    demo_users_created = 0
    for user in DEMO_USERS:
        team_id = team_ids.get(user["team"])
        if team_id:
            result = create_user(
                user["name"],
                user["email"],
                team_id,
                password=user.get("password"),
                role=user.get("role", "user"),
            )
            if result:
                demo_users_created += 1

    print(f"  Total: {demo_users_created} demo users")

    # Create regular users
    print("\n[3/5] Creating users...")
    users_created = 0
    for user in USERS:
        team_id = team_ids.get(user["team"])
        if team_id:
            result = create_user(user["name"], user["email"], team_id)
            if result:
                users_created += 1

    print(f"  Total: {users_created} users")

    # Import multi-project manifests (real dbt projects with team ownership)
    multi_project_result = import_multi_project_manifests(team_ids)

    # Fall back to synthetic manifest if no real dbt projects found
    if multi_project_result["projects_imported"] == 0:
        print("\n[4b] No real dbt projects found, using synthetic manifest...")
        default_team_id = team_ids.get("data-platform") or list(team_ids.values())[0]
        import_result = import_manifest(default_team_id)
        if not import_result:
            print("WARNING: Manifest import failed")
    else:
        import_result = {
            "assets": {"created": multi_project_result["total_assets"]},
            "contracts": {"published": multi_project_result["total_contracts"]},
            "registrations": {"created": 0},  # placeholder
        }
        print("\n  Multi-project import complete!")
        print(f"    Projects: {multi_project_result['projects_imported']}")
        print(f"    Total Assets: {multi_project_result['total_assets']}")
        print(f"    Total Contracts: {multi_project_result['total_contracts']}")
        print(f"    Total Guarantees: {multi_project_result['total_guarantees']}")

    # Create proposals
    print("\n[5/5] Creating sample proposals...")
    proposals = create_proposals(team_ids)
    print(f"  Total: {proposals} proposals")

    # Summary
    print("\n" + "=" * 60)
    print("Seeding complete!")
    print("=" * 60)
    print(f"  Teams: {len(team_ids)}")
    print(f"  Demo Users: {demo_users_created}")
    print(f"  Regular Users: {users_created}")
    if import_result:
        print(f"  Assets: {import_result['assets']['created']}")
        print(f"  Contracts: {import_result['contracts']['published']}")
        print(f"  Registrations: {import_result['registrations']['created']}")
    print(f"  Proposals: {proposals}")
    print("=" * 60)
    print("\nDemo Login Credentials:")
    print("  admin@test.com / admin (Admin)")
    print("  team_admin@test.com / team_admin (Team Admin)")
    print("  user@test.com / user (Regular User)")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
