#!/usr/bin/env python3
"""Import sample dbt manifest into Tessera on Docker startup.

Features:
- Creates multiple teams based on model domains/paths
- Imports all assets with full metadata (columns, tags, descriptions)
- Creates contracts with JSON Schema from column definitions
- Infers subscriptions from depends_on relationships
- Creates asset dependencies in the database
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MANIFEST_PATH = Path("/app/examples/data/manifest.json")

# dbt type to JSON Schema type mapping
TYPE_MAPPING = {
    "string": "string",
    "text": "string",
    "varchar": "string",
    "char": "string",
    "character varying": "string",
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
    "boolean": "boolean",
    "bool": "boolean",
    "date": "string",
    "datetime": "string",
    "timestamp": "string",
    "timestamp_ntz": "string",
    "timestamp_tz": "string",
    "time": "string",
    "json": "object",
    "jsonb": "object",
    "array": "array",
    "variant": "object",
    "object": "object",
}

# Domain to team name mapping
DOMAIN_TEAMS = {
    "core": "platform-team",
    "staging": "data-engineering",
    "analytics": "analytics-team",
    "marketing": "marketing-analytics",
    "finance": "finance-team",
    "sales": "sales-ops",
    "product": "product-analytics",
    "customer": "customer-success",
    "engineering": "engineering-team",
    "hr": "people-team",
    "ops": "operations",
    "support": "support-team",
}


def dbt_columns_to_json_schema(columns: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt column definitions to JSON Schema."""
    properties: dict[str, Any] = {}

    for col_name, col_info in columns.items():
        data_type = (col_info.get("data_type") or "string").lower()
        base_type = data_type.split("(")[0].strip()

        json_type = TYPE_MAPPING.get(base_type, "string")
        prop: dict[str, Any] = {"type": json_type}

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


def get_or_create_team(name: str) -> str | None:
    """Get or create a team by name, return team ID."""
    # Try to create team
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/teams",
            json={"name": name},
            timeout=10,
        )
        if resp.status_code == 201:
            return resp.json()["id"]
    except Exception:
        pass

    # Team might already exist, try to find it
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/teams",
            params={"name": name},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for team in results:
                if team.get("name") == name:
                    return team["id"]
    except Exception:
        pass

    return None


def get_or_create_asset(
    fqn: str, team_id: str, metadata: dict[str, Any]
) -> tuple[str | None, bool]:
    """Get existing asset or create new one. Returns (asset_id, was_created)."""
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
                    return asset["id"], False
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
            return resp.json()["id"], True
    except Exception:
        pass

    return None, False


def get_guarantees_for_layer(layer: str) -> dict[str, Any] | None:
    """Get SLA guarantees based on data layer.

    Uses the Guarantees model structure from tessera.models.contract:
    - freshness: max_staleness_minutes, measured_by
    - volume: min_rows, max_row_delta_pct
    - nullability: dict of column -> 'never', 'always', 'sometimes'
    - accepted_values: dict of column -> list of valid values
    """
    guarantees = {
        "mart": {
            "freshness": {
                "max_staleness_minutes": 60,  # 1 hour
                "measured_by": "updated_at",
                "sla": "99.9%",
            },
            "volume": {
                "min_rows": 100,
                "max_row_delta_pct": 50,
            },
        },
        "intermediate": {
            "freshness": {
                "max_staleness_minutes": 120,  # 2 hours
                "measured_by": "updated_at",
                "sla": "99.5%",
            },
            "volume": {
                "min_rows": 10,
                "max_row_delta_pct": 75,
            },
        },
        "staging": {
            "freshness": {
                "max_staleness_minutes": 240,  # 4 hours
                "measured_by": "loaded_at",
                "sla": "99%",
            },
        },
    }
    return guarantees.get(layer)


def publish_contract(
    asset_id: str,
    team_id: str,
    schema_def: dict[str, Any],
    version: str = "1.0.0",
    guarantees: dict[str, Any] | None = None,
) -> tuple[bool, str, str | None]:
    """Publish a contract for an asset. Returns (success, message, contract_id)."""
    try:
        payload: dict[str, Any] = {
            "version": version,
            "schema": schema_def,
            "compatibility_mode": "backward",
        }
        if guarantees:
            payload["guarantees"] = guarantees

        resp = httpx.post(
            f"{API_URL}/api/v1/assets/{asset_id}/contracts",
            params={"published_by": team_id},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            result = resp.json()
            contract_id = result.get("contract", {}).get("id") or result.get("id")
            return True, "created", contract_id
        elif resp.status_code == 409:
            return False, "exists", None
        else:
            return False, f"error {resp.status_code}", None
    except Exception as e:
        return False, f"exception: {e}", None


def get_active_contract(asset_id: str) -> str | None:
    """Get the active contract ID for an asset."""
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/assets/{asset_id}/contracts",
            params={"status": "active"},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                return results[0]["id"]
    except Exception:
        pass
    return None


def register_consumer(contract_id: str, consumer_team_id: str) -> bool:
    """Register a team as consumer of a contract."""
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/registrations",
            params={"contract_id": contract_id},
            json={"consumer_team_id": consumer_team_id},
            timeout=10,
        )
        return resp.status_code in (200, 201, 409)  # 409 = already registered
    except Exception:
        return False


def create_breaking_change_proposals(
    fqn_to_asset_id: dict[str, str],
    fqn_to_team_id: dict[str, str],
) -> int:
    """Create some breaking change proposals for demo purposes.

    Since registrations often point to sources (which have no columns),
    we need a different approach:
    1. Find contracts with columns (mart/intermediate models)
    2. Register a consumer for them
    3. Then publish a breaking change
    """
    proposals_created = 0
    max_proposals = 5

    # Find contracts that have columns (properties)
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/contracts",
            params={"limit": 100},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"    Failed to get contracts: {resp.status_code}")
            return 0
        contracts = resp.json().get("results", [])
        print(f"    Found {len(contracts)} contracts")
    except Exception as e:
        print(f"    Exception getting contracts: {e}")
        return 0

    # Filter to contracts with at least 2 properties (so we can remove one)
    good_contracts = []
    for c in contracts:
        schema = c.get("schema_def", {})
        props = schema.get("properties", {})
        if len(props) >= 3:  # Need at least 3 to have a meaningful breaking change
            good_contracts.append(c)

    print(f"    Contracts with 3+ properties: {len(good_contracts)}")

    if not good_contracts:
        print("    No suitable contracts found")
        return 0

    # Get available teams for creating cross-team registrations
    try:
        resp = httpx.get(f"{API_URL}/api/v1/teams", params={"limit": 20}, timeout=10)
        teams = resp.json().get("results", []) if resp.status_code == 200 else []
        team_ids = [t["id"] for t in teams]
    except Exception:
        team_ids = []

    if len(team_ids) < 2:
        print("    Not enough teams for cross-team registrations")
        return 0

    # For each contract, register a consumer and then publish a breaking change
    for contract in good_contracts[:max_proposals]:
        if proposals_created >= max_proposals:
            break

        try:
            contract_id = contract["id"]
            asset_id = contract.get("asset_id")
            current_schema = contract.get("schema_def", {})
            publisher_id = contract.get("published_by")

            if not asset_id or not publisher_id:
                continue

            # Get asset details
            resp = httpx.get(f"{API_URL}/api/v1/assets/{asset_id}", timeout=10)
            if resp.status_code != 200:
                continue
            asset = resp.json()
            owner_team_id = asset.get("owner_team_id")
            fqn = asset.get("fqn", "")

            print(f"    Processing: {fqn}")

            # Register a consumer from a different team
            consumer_team = None
            for tid in team_ids:
                if tid != owner_team_id:
                    consumer_team = tid
                    break

            if not consumer_team:
                print("      No different team available for registration")
                continue

            # Register the consumer
            resp = httpx.post(
                f"{API_URL}/api/v1/registrations",
                params={"contract_id": contract_id},
                json={"consumer_team_id": consumer_team},
                timeout=10,
            )
            if resp.status_code not in (200, 201, 409):
                print(f"      Failed to register consumer: {resp.status_code}")
                continue
            print("      Registered consumer team")

            # Create a breaking change (remove a column)
            properties = current_schema.get("properties", {})
            first_col = list(properties.keys())[0]
            new_properties = {k: v for k, v in properties.items() if k != first_col}
            new_schema = {
                "type": "object",
                "properties": new_properties,
                "required": [r for r in current_schema.get("required", []) if r != first_col],
            }

            print(f"      Publishing breaking change (removing '{first_col}')")

            # Publish with breaking change
            resp = httpx.post(
                f"{API_URL}/api/v1/assets/{asset_id}/contracts",
                params={"published_by": owner_team_id},
                json={
                    "version": "2.0.0",
                    "schema": new_schema,
                    "compatibility_mode": "backward",
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                result = resp.json()
                action = result.get("action")
                print(f"      Result: {action}")
                if action == "proposal_created":
                    proposals_created += 1
                    print(f"      Proposal created! Total: {proposals_created}")
                else:
                    print(f"      Unexpected action: {action}")
            else:
                print(f"      Failed to publish: {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            print(f"      Exception: {e}")
            continue

    return proposals_created


def infer_team_from_node(node: dict[str, Any]) -> str:
    """Infer the owning team from a node's path, tags, or schema."""
    # Try to get team from path
    path = node.get("path", "")
    for domain, team in DOMAIN_TEAMS.items():
        if domain in path.lower():
            return team

    # Try to get from schema
    schema = node.get("schema", "").lower()
    for domain, team in DOMAIN_TEAMS.items():
        if domain in schema:
            return team

    # Try to get from tags
    tags = node.get("tags", [])
    for tag in tags:
        tag_lower = tag.lower()
        for domain, team in DOMAIN_TEAMS.items():
            if domain in tag_lower:
                return team

    # Default team
    return "data-platform"


def import_manifest() -> bool:
    """Import the dbt manifest with full data."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found at {MANIFEST_PATH}")
        return False

    manifest = json.loads(MANIFEST_PATH.read_text())

    # Stats
    teams_created = set()
    assets_created = 0
    assets_found = 0
    contracts_created = 0
    registrations_created = 0

    # Build lookups
    node_id_to_fqn: dict[str, str] = {}
    node_id_to_team: dict[str, str] = {}
    fqn_to_asset_id: dict[str, str] = {}
    fqn_to_team_id: dict[str, str] = {}

    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})

    # First pass: collect FQNs and infer teams
    print("\n[Phase 1] Analyzing manifest structure...")

    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        database = node.get("database", "")
        schema = node.get("schema", "")
        name = node.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        node_id_to_fqn[node_id] = fqn
        node_id_to_team[node_id] = infer_team_from_node(node)

    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}".lower()
        node_id_to_fqn[source_id] = fqn
        node_id_to_team[source_id] = "data-engineering"  # Sources owned by data eng

    print(f"  Found {len(nodes)} nodes and {len(sources)} sources")

    # Collect unique teams
    unique_teams = set(node_id_to_team.values())
    print(f"  Inferred {len(unique_teams)} teams: {', '.join(sorted(unique_teams))}")

    # Create teams
    print("\n[Phase 2] Creating teams...")
    team_name_to_id: dict[str, str] = {}

    for team_name in unique_teams:
        team_id = get_or_create_team(team_name)
        if team_id:
            team_name_to_id[team_name] = team_id
            teams_created.add(team_name)
            print(f"  Created/found team: {team_name}")
        else:
            print(f"  FAILED to create team: {team_name}")

    # Import assets
    print("\n[Phase 3] Importing assets...")

    # Process nodes (models)
    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue

        fqn = node_id_to_fqn[node_id]
        team_name = node_id_to_team[node_id]
        team_id = team_name_to_id.get(team_name)

        if not team_id:
            continue

        columns = node.get("columns", {})
        depends_on = node.get("depends_on", {}).get("nodes", [])

        metadata = {
            "dbt_node_id": node_id,
            "resource_type": resource_type,
            "description": node.get("description", ""),
            "tags": node.get("tags", []),
            "dbt_fqn": node.get("fqn", []),
            "path": node.get("path", ""),
            "columns": {
                col_name: {
                    "description": col_info.get("description", ""),
                    "data_type": col_info.get("data_type"),
                }
                for col_name, col_info in columns.items()
            },
            "depends_on": [node_id_to_fqn.get(dep, dep) for dep in depends_on],
        }

        asset_id, was_created = get_or_create_asset(fqn, team_id, metadata)
        if asset_id:
            fqn_to_asset_id[fqn] = asset_id
            fqn_to_team_id[fqn] = team_id
            if was_created:
                assets_created += 1
            else:
                assets_found += 1

            # Publish contract if columns defined
            if columns:
                schema_def = dbt_columns_to_json_schema(columns)
                # Determine layer from path for guarantees
                path = node.get("path", "").lower()
                layer = None
                if "mart" in path:
                    layer = "mart"
                elif "intermediate" in path:
                    layer = "intermediate"
                elif "staging" in path:
                    layer = "staging"
                guarantees = get_guarantees_for_layer(layer) if layer else None
                success, msg, contract_id = publish_contract(
                    asset_id, team_id, schema_def, guarantees=guarantees
                )
                if success:
                    contracts_created += 1

    # Process sources
    for source_id, source in sources.items():
        fqn = node_id_to_fqn[source_id]
        team_name = node_id_to_team[source_id]
        team_id = team_name_to_id.get(team_name)

        if not team_id:
            continue

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

        asset_id, was_created = get_or_create_asset(fqn, team_id, metadata)
        if asset_id:
            fqn_to_asset_id[fqn] = asset_id
            fqn_to_team_id[fqn] = team_id
            if was_created:
                assets_created += 1
            else:
                assets_found += 1

            if columns:
                schema_def = dbt_columns_to_json_schema(columns)
                success, msg, contract_id = publish_contract(asset_id, team_id, schema_def)
                if success:
                    contracts_created += 1

    print(f"  Created {assets_created} assets, found {assets_found} existing")
    print(f"  Created {contracts_created} contracts")

    # Infer and create registrations from depends_on
    print("\n[Phase 4] Creating contract registrations from dependencies...")

    cross_team_deps = 0
    no_contract = 0

    for node_id, node in nodes.items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue

        consumer_team_name = node_id_to_team.get(node_id)
        consumer_team_id = team_name_to_id.get(consumer_team_name)

        if not consumer_team_id:
            continue

        depends_on = node.get("depends_on", {}).get("nodes", [])

        for dep_node_id in depends_on:
            dep_fqn = node_id_to_fqn.get(dep_node_id)
            if not dep_fqn:
                continue

            dep_asset_id = fqn_to_asset_id.get(dep_fqn)
            dep_team_id = fqn_to_team_id.get(dep_fqn)

            # Only register if different team owns the dependency
            if dep_asset_id and dep_team_id and dep_team_id != consumer_team_id:
                cross_team_deps += 1
                contract_id = get_active_contract(dep_asset_id)
                if contract_id:
                    if register_consumer(contract_id, consumer_team_id):
                        registrations_created += 1
                else:
                    no_contract += 1

    print(f"  Cross-team deps: {cross_team_deps}, no contract: {no_contract}")
    print(f"  Created {registrations_created} contract registrations")

    # Create some breaking change proposals
    print("\n[Phase 5] Creating breaking change proposals...")
    proposals_created = create_breaking_change_proposals(fqn_to_asset_id, fqn_to_team_id)
    print(f"  Created {proposals_created} breaking change proposals")

    print("\n" + "=" * 50)
    print("Manifest import complete!")
    print(f"  Teams: {len(teams_created)}")
    print(f"  Assets: {assets_created} created, {assets_found} found")
    print(f"  Contracts: {contracts_created}")
    print(f"  Registrations: {registrations_created}")
    print(f"  Proposals: {proposals_created}")
    print("=" * 50)

    return True


# Sample users to create - 2 per team
SAMPLE_USERS = [
    {"name": "Alice Chen", "email": "alice@example.com", "team": "data-engineering"},
    {"name": "Bob Martinez", "email": "bob@example.com", "team": "data-engineering"},
    {"name": "Carol Johnson", "email": "carol@example.com", "team": "analytics-team"},
    {"name": "David Kim", "email": "david@example.com", "team": "analytics-team"},
    {"name": "Eva Williams", "email": "eva@example.com", "team": "marketing-analytics"},
    {"name": "Frank Brown", "email": "frank@example.com", "team": "marketing-analytics"},
    {"name": "Grace Lee", "email": "grace@example.com", "team": "sales-ops"},
    {"name": "Henry Davis", "email": "henry@example.com", "team": "sales-ops"},
    {"name": "Iris Taylor", "email": "iris@example.com", "team": "platform-team"},
    {"name": "Jack Wilson", "email": "jack@example.com", "team": "platform-team"},
]


def get_or_create_user(name: str, email: str, team_id: str | None) -> str | None:
    """Get or create a user by email, return user ID."""
    # Try to create user
    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/users",
            json={"name": name, "email": email, "team_id": team_id},
            timeout=10,
        )
        if resp.status_code == 201:
            return resp.json()["id"]
    except Exception:
        pass

    # User might already exist, try to find it
    try:
        resp = httpx.get(
            f"{API_URL}/api/v1/users",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for user in results:
                if user.get("email") == email:
                    return user["id"]
    except Exception:
        pass

    return None


def create_sample_users(team_name_to_id: dict[str, str]) -> list[str]:
    """Create sample users and assign to teams. Returns list of user IDs."""
    print("\n--- Creating sample users ---")
    user_ids = []

    for user_data in SAMPLE_USERS:
        team_id = team_name_to_id.get(user_data["team"])
        user_id = get_or_create_user(
            name=user_data["name"],
            email=user_data["email"],
            team_id=team_id,
        )
        if user_id:
            user_ids.append(user_id)
            print(f"  Created/found user: {user_data['name']} ({user_data['email']})")
        else:
            print(f"  Failed to create user: {user_data['name']}")

    print(f"Total users: {len(user_ids)}")
    return user_ids


def get_all_assets() -> list[dict[str, Any]]:
    """Fetch all assets with pagination."""
    assets: list[dict[str, Any]] = []
    offset = 0
    limit = 100

    while True:
        try:
            resp = httpx.get(
                f"{API_URL}/api/v1/assets",
                params={"limit": limit, "offset": offset},
                timeout=30,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            batch = data.get("results", [])
            assets.extend(batch)

            if len(batch) < limit:
                break
            offset += limit
        except Exception:
            break

    return assets


def assign_random_owners(user_ids: list[str]) -> int:
    """Assign random users as owners to assets. Returns count of assignments."""
    import random

    if not user_ids:
        print("No users to assign as owners")
        return 0

    print("\n--- Assigning random asset owners ---")

    assets = get_all_assets()
    if not assets:
        print("Failed to fetch assets")
        return 0

    print(f"  Found {len(assets)} assets")
    assigned = 0
    for asset in assets:
        # Randomly assign an owner (70% chance to have an owner)
        if random.random() < 0.7:
            owner_id = random.choice(user_ids)
            try:
                resp = httpx.patch(
                    f"{API_URL}/api/v1/assets/{asset['id']}",
                    json={"owner_user_id": owner_id},
                    timeout=10,
                )
                if resp.status_code == 200:
                    assigned += 1
            except Exception:
                pass

    print(f"Assigned owners to {assigned}/{len(assets)} assets")
    return assigned


def main():
    """Main entry point."""
    print("=" * 50)
    print("Tessera Init: Importing sample dbt manifest")
    print("=" * 50)

    if not wait_for_api():
        print("Warning: API did not become ready, exiting")
        sys.exit(1)

    if not import_manifest():
        print("Warning: Manifest import failed")
        sys.exit(1)

    # Get team name to ID mapping
    team_name_to_id = {}
    try:
        resp = httpx.get(f"{API_URL}/api/v1/teams", params={"limit": 100}, timeout=10)
        if resp.status_code == 200:
            for team in resp.json().get("results", []):
                team_name_to_id[team["name"]] = team["id"]
    except Exception:
        pass

    # Create users and assign to teams
    user_ids = create_sample_users(team_name_to_id)

    # Assign random owners to assets
    assign_random_owners(user_ids)

    print("\nInit complete! Sample data imported successfully.")


if __name__ == "__main__":
    main()
