"""
Tessera Quickstart Examples
===========================
5 core workflows demonstrating how to use Tessera for data contract coordination.

This script is self-contained - it creates all the data it needs.

Run with: uv run python examples/quickstart.py
"""

import os
import httpx

BASE_URL = "http://localhost:8000/api/v1"
API_KEY = os.environ.get("TESSERA_API_KEY", "tessera-dev-key")
CLIENT = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {API_KEY}"})


def setup():
    """Create the teams, asset, and initial contract needed for the examples."""
    print("Setting up test data...")

    # Create producer team
    resp = CLIENT.post(f"{BASE_URL}/teams", json={"name": "data-platform"})
    if resp.status_code == 201:
        producer = resp.json()
    else:
        # Team might already exist, try to find it
        teams_resp = CLIENT.get(f"{BASE_URL}/teams").json()
        teams = (
            teams_resp.get("results", teams_resp) if isinstance(teams_resp, dict) else teams_resp
        )
        producer = next((t for t in teams if t["name"] == "data-platform"), None)
        if not producer:
            raise Exception("Could not create or find data-platform team")

    # Create consumer team
    resp = CLIENT.post(f"{BASE_URL}/teams", json={"name": "ml-team"})
    if resp.status_code == 201:
        consumer = resp.json()
    else:
        teams_resp = CLIENT.get(f"{BASE_URL}/teams").json()
        teams = (
            teams_resp.get("results", teams_resp) if isinstance(teams_resp, dict) else teams_resp
        )
        consumer = next((t for t in teams if t["name"] == "ml-team"), None)
        if not consumer:
            raise Exception("Could not create or find ml-team")

    # Create an asset
    resp = CLIENT.post(
        f"{BASE_URL}/assets",
        json={
            "fqn": "warehouse.analytics.dim_customers",
            "owner_team_id": producer["id"],
            "metadata": {"description": "Customer dimension table"},
        },
    )
    if resp.status_code == 201:
        asset = resp.json()
    else:
        # Asset might already exist
        assets_resp = CLIENT.get(f"{BASE_URL}/assets").json()
        assets = (
            assets_resp.get("results", assets_resp)
            if isinstance(assets_resp, dict)
            else assets_resp
        )
        asset = next((a for a in assets if a["fqn"] == "warehouse.analytics.dim_customers"), None)
        if not asset:
            raise Exception("Could not create or find asset")

    # Publish initial contract
    contracts_resp = CLIENT.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json()
    contracts = (
        contracts_resp.get("results", contracts_resp)
        if isinstance(contracts_resp, dict)
        else contracts_resp
    )
    if not any(c["status"] == "active" for c in contracts):
        resp = CLIENT.post(
            f"{BASE_URL}/assets/{asset['id']}/contracts",
            params={"published_by": producer["id"]},
            json={
                "version": "1.0.0",
                "schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer"},
                        "email": {"type": "string", "format": "email"},
                        "name": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                    },
                    "required": ["customer_id", "email"],
                },
                "compatibility_mode": "backward",
            },
        )
        if resp.status_code != 201:
            raise Exception(f"Could not create contract: {resp.text}")

    print(f"  Producer team: {producer['name']} ({producer['id']})")
    print(f"  Consumer team: {consumer['name']} ({consumer['id']})")
    print(f"  Asset: {asset['fqn']} ({asset['id']})")
    print()

    return producer, consumer, asset


def example_1_register_as_consumer(asset: dict, consumer: dict):
    """
    EXAMPLE 1: Register as a Consumer
    ---------------------------------
    The ML team wants to use the customer data.
    They register their dependency so they get notified of changes.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Register as a Consumer")
    print("=" * 70)

    # Get the active contract
    contracts_resp = CLIENT.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json()
    contracts = (
        contracts_resp.get("results", contracts_resp)
        if isinstance(contracts_resp, dict)
        else contracts_resp
    )
    contract = next((c for c in contracts if c["status"] == "active"), None)

    if not contract:
        print("No active contract found.")
        return None

    print(f"Found contract: {contract['id']} (v{contract['version']})")

    # Register as a consumer
    resp = CLIENT.post(
        f"{BASE_URL}/registrations",
        params={"contract_id": contract["id"]},
        json={"consumer_team_id": consumer["id"]},
    )
    registration = resp.json()

    print(f"\n✓ Registered as consumer!")
    print(f"  Registration ID: {registration['id']}")
    print(f"  Status: {registration['status']}")

    return contract


def example_2_check_impact(asset: dict):
    """
    EXAMPLE 2: Impact Analysis
    --------------------------
    Before making changes, check who would be affected.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Check Impact Before Making Changes")
    print("=" * 70)

    # Proposed schema that removes the 'email' field
    proposed_schema = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer"},
            "name": {"type": "string"},
            # email field removed!
        },
        "required": ["customer_id"],
    }

    impact = CLIENT.post(f"{BASE_URL}/assets/{asset['id']}/impact", json=proposed_schema).json()

    print(f"\nChange type: {impact['change_type'].upper()}")
    print(f"Safe to publish: {impact['safe_to_publish']}")

    if impact["breaking_changes"]:
        print(f"\n⚠ Breaking changes detected:")
        for bc in impact["breaking_changes"]:
            print(f"  - {bc['message']}")

    if impact["impacted_consumers"]:
        print(f"\n👥 Impacted consumers:")
        for consumer in impact["impacted_consumers"]:
            print(f"  - {consumer['team_name']} (status: {consumer['status']})")

    return impact


def example_3_breaking_change_creates_proposal(asset: dict, producer: dict):
    """
    EXAMPLE 3: Breaking Change → Proposal
    -------------------------------------
    When you try to publish a breaking change, Tessera creates
    a Proposal instead of breaking downstream consumers.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Breaking Change Creates a Proposal")
    print("=" * 70)

    # Try to publish a breaking change (removing 'email')
    result = CLIENT.post(
        f"{BASE_URL}/assets/{asset['id']}/contracts",
        params={"published_by": producer["id"]},
        json={
            "version": "2.0.0",
            "schema": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "full_name": {"type": "string"},  # renamed from 'name'
                    # 'email' removed - breaking change!
                },
                "required": ["customer_id"],
            },
            "compatibility_mode": "backward",
        },
    ).json()

    print(f"\nAction: {result['action']}")

    if result["action"] == "proposal_created":
        print(f"Change type: {result['change_type']}")
        print(f"\n⚠ Breaking changes:")
        for bc in result["breaking_changes"]:
            print(f"  - {bc['message']}")
        print(f"\n📋 Proposal created:")
        print(f"  ID: {result['proposal']['id']}")
        print(f"  Status: {result['proposal']['status']}")
        print(f"\n✓ Consumers must acknowledge before this goes live!")
        return result["proposal"]

    return None


def example_4_acknowledge_proposal(proposal: dict, consumer: dict):
    """
    EXAMPLE 4: Consumer Acknowledges Proposal
    -----------------------------------------
    The affected team reviews and acknowledges the breaking change.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Consumer Acknowledges the Proposal")
    print("=" * 70)

    ack = CLIENT.post(
        f"{BASE_URL}/proposals/{proposal['id']}/acknowledge",
        json={
            "consumer_team_id": consumer["id"],
            "response": "acknowledged",
            "notes": "We've updated our ML pipeline. Ready for the change.",
        },
    ).json()

    print(f"\n✓ Proposal acknowledged!")
    print(f"  Status: {ack.get('status', 'acknowledged')}")
    print(f"  The consumer confirmed they're ready for the change.")

    return ack


def example_5_compatible_change_auto_publishes(asset: dict, producer: dict):
    """
    EXAMPLE 5: Compatible Change Auto-Publishes
    -------------------------------------------
    Adding new optional fields is backward compatible.
    These changes publish automatically without needing approval.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Compatible Change Auto-Publishes")
    print("=" * 70)

    # Get current contract
    contracts_resp = CLIENT.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json()
    contracts = (
        contracts_resp.get("results", contracts_resp)
        if isinstance(contracts_resp, dict)
        else contracts_resp
    )
    current = next((c for c in contracts if c["status"] == "active"), None)

    if not current:
        print("\n⚠ No active contract found.")
        return None

    current_schema = current.get("schema_def") or current.get("schema", {})

    # Add a new optional field (backward compatible)
    new_schema = {
        "type": "object",
        "properties": {
            **current_schema.get("properties", {}),
            "loyalty_tier": {
                "type": "string",
                "enum": ["bronze", "silver", "gold", "platinum"],
                "description": "Customer loyalty program tier",
            },
        },
        "required": current_schema.get("required", []),
    }

    result = CLIENT.post(
        f"{BASE_URL}/assets/{asset['id']}/contracts",
        params={"published_by": producer["id"]},
        json={"version": "1.1.0", "schema": new_schema, "compatibility_mode": "backward"},
    ).json()

    print(f"\nAction: {result['action']}")

    if result["action"] == "published":
        print(f"Change type: {result.get('change_type', 'minor')}")
        print(f"\n✓ Auto-published! No approval needed.")
        print(f"  New version: {result['contract']['version']}")
        print(f"  Added: loyalty_tier field")

    return result


def main():
    """Run all examples."""
    print("\n" + "🔷" * 35)
    print("  TESSERA QUICKSTART EXAMPLES")
    print("🔷" * 35 + "\n")

    # Check server is running
    try:
        CLIENT.get(f"{BASE_URL.replace('/api/v1', '')}/health")
    except httpx.ConnectError:
        print("❌ Server not running. Start it with:")
        print("   uv run uvicorn tessera.main:app --reload")
        return

    try:
        # Setup: create teams, asset, and initial contract
        producer, consumer, asset = setup()

        # Run examples
        example_1_register_as_consumer(asset, consumer)
        example_2_check_impact(asset)
        proposal = example_3_breaking_change_creates_proposal(asset, producer)
        if proposal:
            example_4_acknowledge_proposal(proposal, consumer)
        example_5_compatible_change_auto_publishes(asset, producer)

    except httpx.HTTPStatusError as e:
        print(f"\n❌ HTTP Error: {e.response.status_code}")
        print(e.response.text)
    except Exception as e:
        print(f"\n❌ Error: {e}")

    print("\n" + "=" * 70)
    print("✅ All examples complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
