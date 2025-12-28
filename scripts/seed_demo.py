#!/usr/bin/env python3
"""Seed demo data on Docker startup.

Creates:
- 5 teams (data-platform, marketing-analytics, finance-analytics, product-analytics, sales-ops)
- 12 users distributed across teams
- 220+ assets with contracts from dbt manifest
- Guarantees inferred from dbt tests (not_null, unique, accepted_values, dbt_utils, etc.)
- Kafka topics with Avro schemas (demonstrating schema_format="avro")
- REST API endpoints via /sync/openapi (demonstrating OpenAPI import)
- GraphQL operations via /sync/graphql (demonstrating GraphQL introspection import)
- Audit results for WAP demo (dbt_test, great_expectations, soda integrations)
- A handful of proposals (breaking changes in progress)
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

API_URL = os.environ.get("TESSERA_API_URL", "http://api:8000")
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
    print("\n[4/7] Importing multi-project dbt manifests...")
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


def create_kafka_assets(team_ids: dict[str, str]) -> int:
    """Create sample Kafka assets with Avro schemas to demonstrate schema format support.

    This shows how Tessera handles Avro schemas from Kafka topics.
    """
    print("\nCreating Kafka assets with Avro schemas...")
    assets_created = 0

    # Sample Avro schemas representing typical Kafka topics
    kafka_schemas = [
        {
            "fqn": "kafka.events.user_activity",
            "schema": {
                "type": "record",
                "name": "UserActivity",
                "namespace": "com.company.events",
                "doc": "User activity events from web and mobile apps",
                "fields": [
                    {"name": "event_id", "type": {"type": "string", "logicalType": "uuid"}},
                    {"name": "user_id", "type": "long"},
                    {
                        "name": "event_type",
                        "type": {
                            "type": "enum",
                            "name": "EventType",
                            "symbols": ["PAGE_VIEW", "CLICK", "PURCHASE", "SIGN_UP"],
                        },
                    },
                    {
                        "name": "timestamp",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                    {
                        "name": "properties",
                        "type": ["null", {"type": "map", "values": "string"}],
                        "default": None,
                    },
                ],
            },
            "team": "data-platform",
        },
        {
            "fqn": "kafka.orders.order_created",
            "schema": {
                "type": "record",
                "name": "OrderCreated",
                "namespace": "com.company.orders",
                "doc": "Order creation events from the e-commerce platform",
                "fields": [
                    {"name": "order_id", "type": {"type": "string", "logicalType": "uuid"}},
                    {"name": "customer_id", "type": "long"},
                    {
                        "name": "items",
                        "type": {
                            "type": "array",
                            "items": {
                                "type": "record",
                                "name": "OrderItem",
                                "fields": [
                                    {"name": "product_id", "type": "string"},
                                    {"name": "quantity", "type": "int"},
                                    {
                                        "name": "unit_price",
                                        "type": {
                                            "type": "bytes",
                                            "logicalType": "decimal",
                                            "precision": 10,
                                            "scale": 2,
                                        },
                                    },
                                ],
                            },
                        },
                    },
                    {
                        "name": "total",
                        "type": {
                            "type": "bytes",
                            "logicalType": "decimal",
                            "precision": 12,
                            "scale": 2,
                        },
                    },
                    {
                        "name": "created_at",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                ],
            },
            "team": "sales-ops",
        },
        {
            "fqn": "kafka.marketing.campaign_attribution",
            "schema": {
                "type": "record",
                "name": "CampaignAttribution",
                "namespace": "com.company.marketing",
                "doc": "Marketing campaign attribution events",
                "fields": [
                    {"name": "attribution_id", "type": {"type": "string", "logicalType": "uuid"}},
                    {"name": "user_id", "type": "long"},
                    {"name": "campaign_id", "type": "string"},
                    {
                        "name": "channel",
                        "type": {
                            "type": "enum",
                            "name": "Channel",
                            "symbols": ["EMAIL", "SOCIAL", "PAID_SEARCH", "ORGANIC", "DIRECT"],
                        },
                    },
                    {"name": "conversion_value", "type": ["null", "double"], "default": None},
                    {
                        "name": "attributed_at",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                ],
            },
            "team": "marketing-analytics",
        },
    ]

    for kafka_asset in kafka_schemas:
        team_id = team_ids.get(kafka_asset["team"])
        if not team_id:
            print(f"  Skipping {kafka_asset['fqn']}: team not found")
            continue

        # Create the asset
        try:
            asset_resp = httpx.post(
                f"{API_URL}/api/v1/assets",
                json={
                    "fqn": kafka_asset["fqn"],
                    "owner_team_id": team_id,
                    "resource_type": "kafka_topic",
                    "metadata": {"source": "kafka", "format": "avro"},
                },
                headers=get_headers(),
                timeout=10,
            )

            if asset_resp.status_code == 201:
                asset = asset_resp.json()
                asset_id = asset["id"]
                print(f"  Created asset: {kafka_asset['fqn']}")

                # Publish contract with Avro schema
                contract_resp = httpx.post(
                    f"{API_URL}/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
                    json={
                        "version": "1.0.0",
                        "schema": kafka_asset["schema"],
                        "schema_format": "avro",
                        "compatibility_mode": "backward",
                    },
                    headers=get_headers(),
                    timeout=30,
                )

                if contract_resp.status_code == 201:
                    result = contract_resp.json()
                    contract = result.get("contract", {})
                    print(
                        f"    Published v{contract.get('version', '1.0.0')} (Avro -> JSON Schema)"
                    )
                    assets_created += 1
                else:
                    print(f"    Failed to publish contract: {contract_resp.status_code}")

            elif asset_resp.status_code == 409:
                print(f"  Asset exists: {kafka_asset['fqn']}")
            else:
                print(f"  Failed to create asset: {asset_resp.status_code}")

        except httpx.RequestError as e:
            print(f"  Error: {e}")

    return assets_created


def import_openapi_spec(team_ids: dict[str, str]) -> int:
    """Import OpenAPI spec via the /sync/openapi endpoint.

    This demonstrates how Tessera imports REST API contracts from OpenAPI specs.
    """
    print("\nImporting OpenAPI spec via /sync/openapi...")
    assets_created = 0

    team_id = team_ids.get("product-analytics")
    if not team_id:
        print("  Skipping: product-analytics team not found")
        return 0

    # Sample OpenAPI 3.0 spec representing a typical User API
    openapi_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "User Service API",
            "version": "1.0.0",
            "description": "API for managing users, orders, and products",
        },
        "paths": {
            "/v1/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "description": "Returns a paginated list of users",
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/User"},
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "createUser",
                    "summary": "Create a new user",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/CreateUserRequest"}
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    },
                },
            },
            "/v1/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "summary": "Get a user by ID",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        },
                        "404": {"description": "User not found"},
                    },
                },
            },
            "/v1/orders": {
                "post": {
                    "operationId": "createOrder",
                    "summary": "Create a new order",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/CreateOrderRequest"}
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Order"}
                                }
                            },
                        }
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "email": {"type": "string", "format": "email"},
                        "name": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "plan": {"type": "string", "enum": ["free", "pro", "enterprise"]},
                    },
                    "required": ["id", "email", "name", "created_at", "plan"],
                },
                "CreateUserRequest": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "name": {"type": "string"},
                        "plan": {"type": "string", "enum": ["free", "pro", "enterprise"]},
                    },
                    "required": ["email", "name"],
                },
                "Order": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "format": "uuid"},
                        "customer_id": {"type": "integer"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "sku": {"type": "string"},
                                    "quantity": {"type": "integer", "minimum": 1},
                                    "unit_price": {"type": "number"},
                                },
                                "required": ["sku", "quantity", "unit_price"],
                            },
                        },
                        "total": {"type": "number"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "confirmed", "shipped", "delivered"],
                        },
                    },
                    "required": ["order_id", "customer_id", "items", "total", "status"],
                },
                "CreateOrderRequest": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "sku": {"type": "string"},
                                    "quantity": {"type": "integer", "minimum": 1},
                                },
                                "required": ["sku", "quantity"],
                            },
                        },
                    },
                    "required": ["customer_id", "items"],
                },
            }
        },
    }

    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/sync/openapi",
            json={
                "spec": openapi_spec,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
            headers=get_headers(),
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()
            assets_created = result.get("assets_created", 0)
            contracts = result.get("contracts_published", 0)
            print(f"  Imported OpenAPI spec: {result.get('api_title', 'Unknown')}")
            print(f"    Endpoints found: {result.get('endpoints_found', 0)}")
            print(f"    Assets created: {assets_created}")
            print(f"    Contracts published: {contracts}")
        else:
            print(f"  Failed to import OpenAPI: {resp.status_code} - {resp.text[:100]}")

    except httpx.RequestError as e:
        print(f"  Error importing OpenAPI: {e}")

    return assets_created


def import_graphql_schema(team_ids: dict[str, str]) -> int:
    """Import GraphQL schema via the /sync/graphql endpoint.

    This demonstrates how Tessera imports GraphQL API contracts from introspection results.
    """
    print("\nImporting GraphQL schema via /sync/graphql...")
    assets_created = 0

    team_id = team_ids.get("marketing-analytics")
    if not team_id:
        print("  Skipping: marketing-analytics team not found")
        return 0

    # Sample GraphQL introspection result representing an Analytics API
    introspection = {
        "__schema": {
            "queryType": {"name": "Query"},
            "mutationType": {"name": "Mutation"},
            "types": [
                {
                    "kind": "OBJECT",
                    "name": "Query",
                    "fields": [
                        {
                            "name": "campaigns",
                            "description": "List all marketing campaigns",
                            "args": [
                                {
                                    "name": "status",
                                    "type": {"kind": "ENUM", "name": "CampaignStatus"},
                                },
                                {
                                    "name": "limit",
                                    "type": {"kind": "SCALAR", "name": "Int"},
                                },
                            ],
                            "type": {
                                "kind": "LIST",
                                "ofType": {"kind": "OBJECT", "name": "Campaign"},
                            },
                        },
                        {
                            "name": "campaign",
                            "description": "Get a campaign by ID",
                            "args": [
                                {
                                    "name": "id",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "SCALAR", "name": "ID"},
                                    },
                                }
                            ],
                            "type": {"kind": "OBJECT", "name": "Campaign"},
                        },
                        {
                            "name": "campaignMetrics",
                            "description": "Get performance metrics for a campaign",
                            "args": [
                                {
                                    "name": "campaignId",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "SCALAR", "name": "ID"},
                                    },
                                },
                                {
                                    "name": "startDate",
                                    "type": {"kind": "SCALAR", "name": "String"},
                                },
                                {
                                    "name": "endDate",
                                    "type": {"kind": "SCALAR", "name": "String"},
                                },
                            ],
                            "type": {"kind": "OBJECT", "name": "CampaignMetrics"},
                        },
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "Mutation",
                    "fields": [
                        {
                            "name": "createCampaign",
                            "description": "Create a new marketing campaign",
                            "args": [
                                {
                                    "name": "input",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {
                                            "kind": "INPUT_OBJECT",
                                            "name": "CreateCampaignInput",
                                        },
                                    },
                                }
                            ],
                            "type": {"kind": "OBJECT", "name": "Campaign"},
                        },
                        {
                            "name": "updateCampaignStatus",
                            "description": "Update campaign status",
                            "args": [
                                {
                                    "name": "id",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "SCALAR", "name": "ID"},
                                    },
                                },
                                {
                                    "name": "status",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "ENUM", "name": "CampaignStatus"},
                                    },
                                },
                            ],
                            "type": {"kind": "OBJECT", "name": "Campaign"},
                        },
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "Campaign",
                    "fields": [
                        {
                            "name": "id",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "SCALAR", "name": "ID"},
                            },
                        },
                        {"name": "name", "type": {"kind": "SCALAR", "name": "String"}},
                        {"name": "description", "type": {"kind": "SCALAR", "name": "String"}},
                        {"name": "status", "type": {"kind": "ENUM", "name": "CampaignStatus"}},
                        {"name": "budget", "type": {"kind": "SCALAR", "name": "Float"}},
                        {"name": "startDate", "type": {"kind": "SCALAR", "name": "String"}},
                        {"name": "endDate", "type": {"kind": "SCALAR", "name": "String"}},
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "CampaignMetrics",
                    "fields": [
                        {
                            "name": "campaignId",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "SCALAR", "name": "ID"},
                            },
                        },
                        {"name": "impressions", "type": {"kind": "SCALAR", "name": "Int"}},
                        {"name": "clicks", "type": {"kind": "SCALAR", "name": "Int"}},
                        {"name": "conversions", "type": {"kind": "SCALAR", "name": "Int"}},
                        {"name": "spend", "type": {"kind": "SCALAR", "name": "Float"}},
                        {"name": "revenue", "type": {"kind": "SCALAR", "name": "Float"}},
                        {"name": "roas", "type": {"kind": "SCALAR", "name": "Float"}},
                    ],
                },
                {
                    "kind": "ENUM",
                    "name": "CampaignStatus",
                    "enumValues": [
                        {"name": "DRAFT"},
                        {"name": "ACTIVE"},
                        {"name": "PAUSED"},
                        {"name": "ENDED"},
                    ],
                },
                {
                    "kind": "INPUT_OBJECT",
                    "name": "CreateCampaignInput",
                    "inputFields": [
                        {
                            "name": "name",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "SCALAR", "name": "String"},
                            },
                        },
                        {"name": "description", "type": {"kind": "SCALAR", "name": "String"}},
                        {"name": "budget", "type": {"kind": "SCALAR", "name": "Float"}},
                        {"name": "startDate", "type": {"kind": "SCALAR", "name": "String"}},
                        {"name": "endDate", "type": {"kind": "SCALAR", "name": "String"}},
                    ],
                },
            ],
        }
    }

    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/sync/graphql",
            json={
                "introspection": introspection,
                "owner_team_id": team_id,
                "schema_name": "Marketing Analytics API",
                "auto_publish_contracts": True,
            },
            headers=get_headers(),
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()
            assets_created = result.get("assets_created", 0)
            contracts = result.get("contracts_published", 0)
            print(f"  Imported GraphQL schema: {result.get('schema_name', 'Unknown')}")
            print(f"    Operations found: {result.get('operations_found', 0)}")
            print(f"    Assets created: {assets_created}")
            print(f"    Contracts published: {contracts}")
        else:
            print(f"  Failed to import GraphQL: {resp.status_code} - {resp.text[:100]}")

    except httpx.RequestError as e:
        print(f"  Error importing GraphQL: {e}")

    return assets_created


def create_audit_results(team_ids: dict[str, str]) -> int:
    """Create sample audit results to demonstrate WAP (Write-Audit-Publish) pattern.

    Creates a realistic mix of:
    - dbt test results (most common)
    - Great Expectations validations
    - Soda checks
    - Manual audits

    Some assets will have:
    - Consistently passing audits
    - Intermittent failures (realistic data quality issues)
    - Recent failures to trigger alerts
    """
    print("\nCreating audit results for WAP demo...")
    audits_created = 0

    # Get some assets to add audit results to
    try:
        assets_resp = httpx.get(
            f"{API_URL}/api/v1/assets?limit=30",
            headers=get_headers(),
            timeout=10,
        )
        if assets_resp.status_code != 200:
            print("  Could not fetch assets")
            return 0

        assets = assets_resp.json().get("results", [])
        if not assets:
            print("  No assets found")
            return 0

        # Define test patterns for different scenarios
        test_patterns = {
            "healthy": {  # Mostly passing, occasional failure
                "pass_rate": 0.9,
                "run_count": 10,
            },
            "flaky": {  # Intermittent failures
                "pass_rate": 0.7,
                "run_count": 15,
            },
            "degrading": {  # Started good, recent failures
                "pass_rate": 0.5,
                "run_count": 12,
                "recent_failures": True,
            },
            "failing": {  # Consistent failures
                "pass_rate": 0.2,
                "run_count": 8,
            },
        }

        # Common dbt test types
        dbt_test_types = [
            "not_null",
            "unique",
            "accepted_values",
            "relationships",
            "dbt_utils.expression_is_true",
            "dbt_utils.at_least_one",
            "dbt_expectations.expect_column_values_to_be_between",
            "dbt_expectations.expect_column_values_to_not_be_null",
        ]

        # Assign patterns to assets
        pattern_assignments = {}
        for i, asset in enumerate(assets[:20]):  # Audit first 20 assets
            if i < 8:
                pattern_assignments[asset["id"]] = "healthy"
            elif i < 12:
                pattern_assignments[asset["id"]] = "flaky"
            elif i < 16:
                pattern_assignments[asset["id"]] = "degrading"
            else:
                pattern_assignments[asset["id"]] = "failing"

        # Generate audit results
        triggered_by_sources = ["dbt_test", "dbt_test", "dbt_test", "great_expectations", "soda"]

        for asset_id, pattern_name in pattern_assignments.items():
            pattern = test_patterns[pattern_name]
            fqn = next((a["fqn"] for a in assets if a["id"] == asset_id), "unknown")

            # Generate runs spread over the last 30 days
            now = datetime.utcnow()
            for run_idx in range(pattern["run_count"]):
                # Distribute runs over time (more recent = more runs)
                hours_ago = random.randint(1, 720)  # Up to 30 days
                run_at = now - timedelta(hours=hours_ago)

                # Determine if this run passes
                if pattern.get("recent_failures") and hours_ago < 48:
                    passed = random.random() < 0.2  # Recent runs mostly fail
                else:
                    passed = random.random() < pattern["pass_rate"]

                # Generate guarantee results
                num_guarantees = random.randint(3, 8)
                guarantee_results = []
                guarantees_passed = 0
                guarantees_failed = 0

                for g_idx in range(num_guarantees):
                    test_type = random.choice(dbt_test_types)
                    guarantee_id = f"{test_type}_{fqn.split('.')[-1]}"

                    if passed or random.random() < 0.7:  # Even failed runs have some passing tests
                        guarantee_results.append(
                            {
                                "guarantee_id": guarantee_id,
                                "passed": True,
                                "rows_checked": random.randint(1000, 100000),
                                "rows_failed": 0,
                            }
                        )
                        guarantees_passed += 1
                    else:
                        rows_checked = random.randint(1000, 100000)
                        rows_failed = random.randint(1, min(100, rows_checked // 10))
                        guarantee_results.append(
                            {
                                "guarantee_id": guarantee_id,
                                "passed": False,
                                "error_message": f"Found {rows_failed} rows failing {test_type}",
                                "rows_checked": rows_checked,
                                "rows_failed": rows_failed,
                            }
                        )
                        guarantees_failed += 1

                # Determine overall status
                if guarantees_failed == 0:
                    status = "passed"
                elif guarantees_failed < num_guarantees:
                    status = "partial"
                else:
                    status = "failed"

                # Build payload
                triggered_by = random.choice(triggered_by_sources)
                payload = {
                    "status": status,
                    "guarantees_checked": num_guarantees,
                    "guarantees_passed": guarantees_passed,
                    "guarantees_failed": guarantees_failed,
                    "triggered_by": triggered_by,
                    "run_id": (
                        f"{triggered_by}-{run_at.strftime('%Y%m%d%H%M%S')}-"
                        f"{random.randint(1000, 9999)}"
                    ),
                    "guarantee_results": guarantee_results,
                    "run_at": run_at.isoformat() + "Z",
                    "details": {"source": triggered_by, "pattern": pattern_name},
                }

                # Submit audit result
                try:
                    resp = httpx.post(
                        f"{API_URL}/api/v1/assets/{asset_id}/audit-results",
                        json=payload,
                        headers=get_headers(),
                        timeout=10,
                    )
                    if resp.status_code in (200, 201):
                        audits_created += 1
                except httpx.RequestError:
                    pass  # Silently skip failures

            # Progress indicator
            if audits_created % 20 == 0:
                print(f"  Created {audits_created} audit results...")

    except httpx.RequestError as e:
        print(f"  Error creating audit results: {e}")

    return audits_created


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
    print("\n[1/7] Creating teams...")
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
    print("\n[2/7] Creating demo login users...")
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
    print("\n[3/7] Creating users...")
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
        print("\n  No real dbt projects found, using synthetic manifest...")
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

    # Create Kafka assets with Avro schemas
    print("\n[5/9] Creating Kafka assets with Avro schemas...")
    kafka_assets = create_kafka_assets(team_ids)
    print(f"  Total: {kafka_assets} Kafka assets with Avro contracts")

    # Import OpenAPI spec (REST endpoints)
    print("\n[6/9] Importing OpenAPI spec (REST endpoints)...")
    openapi_assets = import_openapi_spec(team_ids)
    print(f"  Total: {openapi_assets} REST API assets")

    # Import GraphQL schema
    print("\n[7/9] Importing GraphQL schema...")
    graphql_assets = import_graphql_schema(team_ids)
    print(f"  Total: {graphql_assets} GraphQL assets")

    # Create audit results (WAP demo)
    print("\n[8/9] Creating audit results (WAP demo)...")
    audit_results = create_audit_results(team_ids)
    print(f"  Total: {audit_results} audit results")

    # Create proposals
    print("\n[9/9] Creating sample proposals...")
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
    print(f"  Kafka Assets (Avro): {kafka_assets}")
    print(f"  OpenAPI Assets (REST): {openapi_assets}")
    print(f"  GraphQL Assets: {graphql_assets}")
    print(f"  Audit Results (WAP): {audit_results}")
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
