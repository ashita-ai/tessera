"""
Tessera Quickstart Examples
===========================
5 core workflows demonstrating how to use Tessera for data contract coordination.

Two approaches are shown for each workflow:
  - HTTP (httpx): Direct REST API calls. No extra dependency beyond httpx.
    Use this when you need fine-grained control, are integrating into an existing
    HTTP-based pipeline, or want to avoid the SDK dependency.
  - SDK (tessera-sdk): Higher-level client that handles pagination, error mapping,
    and resource resolution. Use this for application code and scripts where
    readability and maintainability matter more than raw control.

Install the SDK:  pip install tessera-sdk

This script is self-contained - it creates all the data it needs.

Run with:
  HTTP mode:  uv run python examples/quickstart.py
  SDK mode:   uv run python examples/quickstart.py --sdk
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000/api/v1"
SERVER_URL = "http://localhost:8000"
API_KEY = os.environ.get("TESSERA_API_KEY", "tessera-dev-key")


def _check_server_http() -> bool:
    """Return True if the Tessera server is reachable via httpx."""
    import httpx

    try:
        httpx.get(f"{SERVER_URL}/health", timeout=5.0)
        return True
    except httpx.ConnectError:
        return False


# ============================================================================
# HTTP (httpx) implementation
# ============================================================================


def _get_http_client():
    import httpx

    return httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {API_KEY}"})


def _unpack(resp_json: dict | list, key: str = "results") -> list:
    """Extract list from paginated or raw response."""
    if isinstance(resp_json, list):
        return resp_json
    return resp_json.get(key, resp_json) if isinstance(resp_json, dict) else []


def setup_http(client):
    """Create the teams, asset, and initial contract needed for the examples."""
    print("Setting up test data...")

    # Create producer team
    resp = client.post(f"{BASE_URL}/teams", json={"name": "data-platform"})
    if resp.status_code == 201:
        producer = resp.json()
    else:
        teams = _unpack(client.get(f"{BASE_URL}/teams").json())
        producer = next((t for t in teams if t["name"] == "data-platform"), None)
        if not producer:
            raise RuntimeError("Could not create or find data-platform team")

    # Create consumer team
    resp = client.post(f"{BASE_URL}/teams", json={"name": "ml-team"})
    if resp.status_code == 201:
        consumer = resp.json()
    else:
        teams = _unpack(client.get(f"{BASE_URL}/teams").json())
        consumer = next((t for t in teams if t["name"] == "ml-team"), None)
        if not consumer:
            raise RuntimeError("Could not create or find ml-team")

    # Create an asset
    resp = client.post(
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
        assets = _unpack(client.get(f"{BASE_URL}/assets").json())
        asset = next(
            (a for a in assets if a["fqn"] == "warehouse.analytics.dim_customers"),
            None,
        )
        if not asset:
            raise RuntimeError("Could not create or find asset")

    # Publish initial contract if none active
    contracts = _unpack(client.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json())
    if not any(c["status"] == "active" for c in contracts):
        resp = client.post(
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
            raise RuntimeError(f"Could not create contract: {resp.text}")

    _print_setup(producer, consumer, asset)
    return producer, consumer, asset


def example_1_http(asset: dict, consumer: dict, client):
    """Register as a consumer (HTTP)."""
    _print_header("EXAMPLE 1: Register as a Consumer")

    contracts = _unpack(client.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json())
    contract = next((c for c in contracts if c["status"] == "active"), None)
    if not contract:
        print("No active contract found.")
        return None

    print(f"Found contract: {contract['id']} (v{contract['version']})")

    resp = client.post(
        f"{BASE_URL}/registrations",
        params={"contract_id": contract["id"]},
        json={"consumer_team_id": consumer["id"]},
    )
    registration = resp.json()

    print("\nRegistered as consumer!")
    print(f"  Registration ID: {registration['id']}")
    print(f"  Status: {registration['status']}")
    return contract


def example_2_http(asset: dict, client):
    """Check impact before making changes (HTTP)."""
    _print_header("EXAMPLE 2: Check Impact Before Making Changes")

    proposed_schema = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer"},
            "name": {"type": "string"},
            # email field removed!
        },
        "required": ["customer_id"],
    }

    impact = client.post(
        f"{BASE_URL}/assets/{asset['id']}/impact-preview",
        json={"proposed_schema": proposed_schema},
    ).json()

    print(f"\nBreaking: {impact['is_breaking']}")

    if impact["breaking_changes"]:
        print("\nBreaking changes detected:")
        for bc in impact["breaking_changes"]:
            print(f"  - {bc['message']}")

    if impact["affected_consumers"]:
        print("\nAffected consumers:")
        for c in impact["affected_consumers"]:
            print(f"  - {c['team_name']} (status: {c['status']})")

    return impact


def example_3_http(asset: dict, producer: dict, client):
    """Publish a breaking change, creating a proposal (HTTP)."""
    _print_header("EXAMPLE 3: Breaking Change Creates a Proposal")

    result = client.post(
        f"{BASE_URL}/assets/{asset['id']}/contracts",
        params={"published_by": producer["id"]},
        json={
            "version": "2.0.0",
            "schema": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "full_name": {"type": "string"},
                },
                "required": ["customer_id"],
            },
            "compatibility_mode": "backward",
        },
    ).json()

    print(f"\nAction: {result['action']}")

    if result["action"] == "proposal_created":
        print(f"Change type: {result['change_type']}")
        print("\nBreaking changes:")
        for bc in result["breaking_changes"]:
            print(f"  - {bc['message']}")
        print(f"\nProposal created: {result['proposal']['id']}")
        print(f"  Status: {result['proposal']['status']}")
        print("\nConsumers must acknowledge before this goes live!")
        return result["proposal"]

    return None


def example_4_http(proposal: dict, consumer: dict, client):
    """Consumer acknowledges a proposal (HTTP)."""
    _print_header("EXAMPLE 4: Consumer Acknowledges the Proposal")

    ack = client.post(
        f"{BASE_URL}/proposals/{proposal['id']}/acknowledge",
        json={
            "consumer_team_id": consumer["id"],
            "response": "approved",
            "notes": "We've updated our ML pipeline. Ready for the change.",
        },
    ).json()

    print("\nProposal acknowledged!")
    print(f"  Response: {ack.get('response', 'approved')}")
    return ack


def example_5_http(asset: dict, producer: dict, client):
    """Publish a compatible change that auto-publishes (HTTP)."""
    _print_header("EXAMPLE 5: Compatible Change Auto-Publishes")

    contracts = _unpack(client.get(f"{BASE_URL}/assets/{asset['id']}/contracts").json())
    current = next((c for c in contracts if c["status"] == "active"), None)
    if not current:
        print("\nNo active contract found.")
        return None

    current_schema = current.get("schema_def") or current.get("schema", {})

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

    result = client.post(
        f"{BASE_URL}/assets/{asset['id']}/contracts",
        params={"published_by": producer["id"]},
        json={"version": "1.1.0", "schema": new_schema, "compatibility_mode": "backward"},
    ).json()

    print(f"\nAction: {result['action']}")
    if result["action"] == "published":
        print(f"Change type: {result.get('change_type', 'minor')}")
        print("\nAuto-published! No approval needed.")
        print(f"  New version: {result['contract']['version']}")
        print("  Added: loyalty_tier field")

    return result


def run_http():
    """Run all examples using raw httpx."""
    client = _get_http_client()
    try:
        producer, consumer, asset = setup_http(client)
        example_1_http(asset, consumer, client)
        example_2_http(asset, client)
        proposal = example_3_http(asset, producer, client)
        if proposal:
            example_4_http(proposal, consumer, client)
        example_5_http(asset, producer, client)
    finally:
        client.close()


# ============================================================================
# SDK (tessera-sdk) implementation
# ============================================================================


def setup_sdk(client):
    """Create the teams, asset, and initial contract needed for the examples."""
    print("Setting up test data...")

    # SDK handles errors and returns typed objects
    producer = client.teams.create(name="data-platform")
    consumer = client.teams.create(name="ml-team")

    asset = client.assets.create(
        fqn="warehouse.analytics.dim_customers",
        owner_team_id=producer.id,
        description="Customer dimension table",
    )

    # Publish initial contract
    contracts = client.contracts.list(asset_id=asset.id)
    if not any(c.status == "active" for c in contracts):
        client.assets.publish_contract(
            asset_id=asset.id,
            version="1.0.0",
            schema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "email": {"type": "string", "format": "email"},
                    "name": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"},
                },
                "required": ["customer_id", "email"],
            },
            compatibility_mode="backward",
        )

    _print_setup_sdk(producer, consumer, asset)
    return producer, consumer, asset


def example_1_sdk(asset, consumer, client):
    """Register as a consumer (SDK)."""
    _print_header("EXAMPLE 1: Register as a Consumer")

    # Find the active contract
    contracts = client.contracts.list(asset_id=asset.id)
    contract = next((c for c in contracts if c.status == "active"), None)
    if not contract:
        print("No active contract found.")
        return None

    print(f"Found contract: {contract.id} (v{contract.version})")

    # One call to register - no need to build URLs or manage query params
    registration = client.registrations.create(
        contract_id=contract.id,
        consumer_team_id=consumer.id,
    )

    print("\nRegistered as consumer!")
    print(f"  Registration ID: {registration.id}")
    print(f"  Status: {registration.status}")
    return contract


def example_2_sdk(asset, client):
    """Check impact before making changes (SDK)."""
    _print_header("EXAMPLE 2: Check Impact Before Making Changes")

    proposed_schema = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer"},
            "name": {"type": "string"},
        },
        "required": ["customer_id"],
    }

    # SDK wraps the request body for you
    impact = client.assets.check_impact(
        asset_id=asset.id,
        proposed_schema=proposed_schema,
    )

    print(f"\nBreaking: {impact.is_breaking}")

    if impact.breaking_changes:
        print("\nBreaking changes detected:")
        for bc in impact.breaking_changes:
            print(f"  - {bc['message']}")

    if impact.affected_consumers:
        print("\nAffected consumers:")
        for c in impact.affected_consumers:
            print(f"  - {c['team_name']} (status: {c['status']})")

    return impact


def example_3_sdk(asset, producer, client):
    """Publish a breaking change, creating a proposal (SDK)."""
    _print_header("EXAMPLE 3: Breaking Change Creates a Proposal")

    result = client.assets.publish_contract(
        asset_id=asset.id,
        version="2.0.0",
        schema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
                "full_name": {"type": "string"},
            },
            "required": ["customer_id"],
        },
        compatibility_mode="backward",
    )

    print(f"\nAction: {result.action}")

    if result.action == "proposal_created":
        print(f"Change type: {result.change_type}")
        print("\nBreaking changes:")
        for bc in result.breaking_changes:
            print(f"  - {bc['message']}")
        print(f"\nProposal created: {result.proposal.id}")
        print(f"  Status: {result.proposal.status}")
        print("\nConsumers must acknowledge before this goes live!")
        return result.proposal

    return None


def example_4_sdk(proposal, consumer, client):
    """Consumer acknowledges a proposal (SDK)."""
    _print_header("EXAMPLE 4: Consumer Acknowledges the Proposal")

    ack = client.proposals.acknowledge(
        proposal_id=proposal.id,
        team_id=consumer.id,
        accepted=True,
        comment="We've updated our ML pipeline. Ready for the change.",
    )

    print("\nProposal acknowledged!")
    print(f"  Response: {ack.response}")
    return ack


def example_5_sdk(asset, producer, client):
    """Publish a compatible change that auto-publishes (SDK)."""
    _print_header("EXAMPLE 5: Compatible Change Auto-Publishes")

    # Get current active contract's schema
    contracts = client.contracts.list(asset_id=asset.id)
    current = next((c for c in contracts if c.status == "active"), None)
    if not current:
        print("\nNo active contract found.")
        return None

    current_schema = current.schema

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

    result = client.assets.publish_contract(
        asset_id=asset.id,
        version="1.1.0",
        schema=new_schema,
        compatibility_mode="backward",
    )

    print(f"\nAction: {result.action}")
    if result.action == "published":
        print(f"Change type: {result.change_type}")
        print("\nAuto-published! No approval needed.")
        print(f"  New version: {result.contract.version}")
        print("  Added: loyalty_tier field")

    return result


def run_sdk():
    """Run all examples using the tessera-sdk."""
    try:
        from tessera_sdk import TesseraClient
    except ImportError:
        print("tessera-sdk is not installed. Install it with:")
        print("  pip install tessera-sdk")
        sys.exit(1)

    with TesseraClient(base_url=SERVER_URL, api_key=API_KEY) as client:
        producer, consumer, asset = setup_sdk(client)
        example_1_sdk(asset, consumer, client)
        example_2_sdk(asset, client)
        proposal = example_3_sdk(asset, producer, client)
        if proposal:
            example_4_sdk(proposal, consumer, client)
        example_5_sdk(asset, producer, client)


# ============================================================================
# Shared helpers
# ============================================================================


def _print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _print_setup(producer: dict, consumer: dict, asset: dict) -> None:
    print(f"  Producer team: {producer['name']} ({producer['id']})")
    print(f"  Consumer team: {consumer['name']} ({consumer['id']})")
    print(f"  Asset: {asset['fqn']} ({asset['id']})")
    print()


def _print_setup_sdk(producer, consumer, asset) -> None:
    print(f"  Producer team: {producer.name} ({producer.id})")
    print(f"  Consumer team: {consumer.name} ({consumer.id})")
    print(f"  Asset: {asset.fqn} ({asset.id})")
    print()


# ============================================================================
# Entry point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="Tessera quickstart examples")
    parser.add_argument(
        "--sdk",
        action="store_true",
        help="Use the tessera-sdk client instead of raw httpx",
    )
    args = parser.parse_args()

    mode = "SDK (tessera-sdk)" if args.sdk else "HTTP (httpx)"
    print(f"\n{'=' * 70}")
    print(f"  TESSERA QUICKSTART EXAMPLES  [{mode}]")
    print(f"{'=' * 70}\n")

    if not _check_server_http():
        print("Server not running. Start it with:")
        print("  uv run uvicorn tessera.main:app --reload")
        sys.exit(1)

    try:
        if args.sdk:
            run_sdk()
        else:
            run_http()
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("All examples complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
