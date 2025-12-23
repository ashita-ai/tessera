#!/usr/bin/env python3
"""Generate a realistic dbt manifest with ~250 models for testing."""

import json
import random
from pathlib import Path

# Domain-specific schemas and naming
DOMAINS = {
    "core": {
        "prefix": "core",
        "teams": ["platform", "data-eng"],
        "tags": ["core", "sla-critical"],
    },
    "marketing": {
        "prefix": "mktg",
        "teams": ["marketing-analytics", "growth"],
        "tags": ["marketing", "pii"],
    },
    "finance": {
        "prefix": "fin",
        "teams": ["finance-analytics", "accounting"],
        "tags": ["finance", "sox-compliant", "pii"],
    },
    "product": {
        "prefix": "prod",
        "teams": ["product-analytics", "experimentation"],
        "tags": ["product", "events"],
    },
    "sales": {
        "prefix": "sales",
        "teams": ["sales-ops", "revenue"],
        "tags": ["sales", "crm"],
    },
    "support": {
        "prefix": "support",
        "teams": ["customer-success", "support-analytics"],
        "tags": ["support", "tickets"],
    },
}

# Column templates by type
COLUMN_TEMPLATES = {
    "id": {"type": "integer", "description": "Unique identifier"},
    "uuid": {"type": "string", "description": "UUID identifier"},
    "created_at": {"type": "timestamp", "description": "Record creation timestamp"},
    "updated_at": {"type": "timestamp", "description": "Last update timestamp"},
    "deleted_at": {"type": "timestamp", "description": "Soft delete timestamp"},
    "name": {"type": "string", "description": "Display name"},
    "email": {"type": "string", "description": "Email address"},
    "amount": {"type": "number", "description": "Monetary amount in USD"},
    "quantity": {"type": "integer", "description": "Count or quantity"},
    "status": {"type": "string", "description": "Current status"},
    "is_active": {"type": "boolean", "description": "Whether record is active"},
    "metadata": {"type": "object", "description": "Additional metadata JSON"},
    "date": {"type": "date", "description": "Calendar date"},
    "timestamp": {"type": "timestamp", "description": "Event timestamp"},
    "user_id": {"type": "integer", "description": "Foreign key to users"},
    "customer_id": {"type": "integer", "description": "Foreign key to customers"},
    "order_id": {"type": "integer", "description": "Foreign key to orders"},
    "product_id": {"type": "integer", "description": "Foreign key to products"},
    "campaign_id": {"type": "integer", "description": "Foreign key to campaigns"},
    "account_id": {"type": "integer", "description": "Foreign key to accounts"},
}

# Model templates per layer
STAGING_MODELS = [
    "stg_{domain}_users",
    "stg_{domain}_accounts",
    "stg_{domain}_events",
    "stg_{domain}_transactions",
    "stg_{domain}_sessions",
]

INTERMEDIATE_MODELS = [
    "int_{domain}_user_sessions",
    "int_{domain}_daily_events",
    "int_{domain}_transaction_summary",
    "int_{domain}_user_lifecycle",
    "int_{domain}_engagement_metrics",
]

DIMENSION_MODELS = [
    "dim_{domain}_users",
    "dim_{domain}_accounts",
    "dim_{domain}_products",
    "dim_{domain}_campaigns",
    "dim_{domain}_channels",
]

FACT_MODELS = [
    "fct_{domain}_events",
    "fct_{domain}_transactions",
    "fct_{domain}_conversions",
    "fct_{domain}_revenue",
    "fct_{domain}_engagement",
]

MART_MODELS = [
    "mart_{domain}_user_360",
    "mart_{domain}_daily_metrics",
    "mart_{domain}_weekly_rollup",
    "mart_{domain}_monthly_summary",
    "mart_{domain}_cohort_analysis",
    "mart_{domain}_funnel_analysis",
    "mart_{domain}_retention",
    "mart_{domain}_ltv",
    "mart_{domain}_attribution",
    "mart_{domain}_kpis",
    "mart_{domain}_executive_dashboard",
    "mart_{domain}_trends",
    "mart_{domain}_forecasts",
]


def generate_columns(model_name: str, layer: str) -> dict:
    """Generate appropriate columns for a model based on its name and layer."""
    columns = {}

    # Always include ID and timestamps
    pk_name = f"{model_name.split('_')[-1].rstrip('s')}_id"
    columns[pk_name] = {
        "name": pk_name,
        "description": f"Primary key for {model_name}",
        "data_type": "integer",
    }
    columns["created_at"] = {
        "name": "created_at",
        "description": "Record creation timestamp",
        "data_type": "timestamp",
    }

    # Add layer-specific columns
    if layer == "staging":
        columns["_loaded_at"] = {
            "name": "_loaded_at",
            "description": "ETL load timestamp",
            "data_type": "timestamp",
        }
        columns["_source"] = {
            "name": "_source",
            "description": "Source system identifier",
            "data_type": "string",
        }

    if layer in ("dimension", "mart"):
        columns["updated_at"] = {
            "name": "updated_at",
            "description": "Last update timestamp",
            "data_type": "timestamp",
        }

    # Add domain-specific columns
    if "user" in model_name:
        columns.update(
            {
                "email": {
                    "name": "email",
                    "description": "User email address",
                    "data_type": "string",
                },
                "name": {"name": "name", "description": "User display name", "data_type": "string"},
                "signup_date": {
                    "name": "signup_date",
                    "description": "User signup date",
                    "data_type": "date",
                },
            }
        )

    if "transaction" in model_name or "revenue" in model_name:
        columns.update(
            {
                "amount": {
                    "name": "amount",
                    "description": "Transaction amount in USD",
                    "data_type": "number",
                },
                "currency": {
                    "name": "currency",
                    "description": "Currency code",
                    "data_type": "string",
                },
                "transaction_date": {
                    "name": "transaction_date",
                    "description": "Transaction date",
                    "data_type": "date",
                },
            }
        )

    if "event" in model_name:
        columns.update(
            {
                "event_type": {
                    "name": "event_type",
                    "description": "Type of event",
                    "data_type": "string",
                },
                "event_timestamp": {
                    "name": "event_timestamp",
                    "description": "When event occurred",
                    "data_type": "timestamp",
                },
                "properties": {
                    "name": "properties",
                    "description": "Event properties JSON",
                    "data_type": "object",
                },
            }
        )

    if "campaign" in model_name or "marketing" in model_name:
        columns.update(
            {
                "campaign_name": {
                    "name": "campaign_name",
                    "description": "Campaign name",
                    "data_type": "string",
                },
                "channel": {
                    "name": "channel",
                    "description": "Marketing channel",
                    "data_type": "string",
                },
                "spend": {
                    "name": "spend",
                    "description": "Campaign spend in USD",
                    "data_type": "number",
                },
            }
        )

    if "metric" in model_name or "summary" in model_name or "rollup" in model_name:
        columns.update(
            {
                "metric_date": {
                    "name": "metric_date",
                    "description": "Metric date",
                    "data_type": "date",
                },
                "total_count": {
                    "name": "total_count",
                    "description": "Total count",
                    "data_type": "integer",
                },
                "total_amount": {
                    "name": "total_amount",
                    "description": "Total amount",
                    "data_type": "number",
                },
                "avg_value": {
                    "name": "avg_value",
                    "description": "Average value",
                    "data_type": "number",
                },
            }
        )

    return columns


def generate_model(
    name: str,
    domain: str,
    layer: str,
    depends_on: list[str],
    tags: list[str],
) -> dict:
    """Generate a dbt model node."""
    schema = "staging" if layer == "staging" else "analytics"

    return {
        "name": name,
        "resource_type": "model",
        "schema": schema,
        "database": "warehouse",
        "unique_id": f"model.ecommerce.{name}",
        "fqn": ["ecommerce", domain, name],
        "description": f"{layer.title()} model for {domain} domain: {name.replace('_', ' ')}",
        "columns": generate_columns(name, layer),
        "depends_on": {"nodes": depends_on},
        "path": f"models/{domain}/{layer}/{name}.sql",
        "tags": tags,
    }


def generate_source(name: str, domain: str) -> dict:
    """Generate a dbt source node."""
    return {
        "name": name,
        "resource_type": "source",
        "schema": "raw",
        "database": "warehouse",
        "unique_id": f"source.ecommerce.{name}",
        "source_name": domain,
        "description": f"Raw {name.replace('_', ' ')} data from {domain} source system",
        "columns": {
            "id": {"name": "id", "description": "Source record ID", "data_type": "integer"},
            "data": {"name": "data", "description": "Raw JSON payload", "data_type": "object"},
            "_loaded_at": {
                "name": "_loaded_at",
                "description": "Load timestamp",
                "data_type": "timestamp",
            },
        },
    }


def generate_manifest() -> dict:
    """Generate a complete dbt manifest."""
    nodes = {}
    sources = {}

    # Generate sources first (raw data)
    raw_sources = [
        "raw_users",
        "raw_events",
        "raw_transactions",
        "raw_products",
        "raw_orders",
        "raw_customers",
        "raw_campaigns",
        "raw_sessions",
        "raw_pageviews",
        "raw_clicks",
        "raw_conversions",
        "raw_accounts",
        "raw_invoices",
        "raw_payments",
        "raw_subscriptions",
        "raw_tickets",
    ]

    for source_name in raw_sources:
        domain = random.choice(list(DOMAINS.keys()))
        source_id = f"source.ecommerce.{source_name}"
        sources[source_id] = generate_source(source_name, domain)

    # Track model dependencies for each domain
    domain_models = {
        d: {"staging": [], "intermediate": [], "dimension": [], "fact": [], "mart": []}
        for d in DOMAINS
    }

    # Generate staging models (depend on sources)
    for domain, config in DOMAINS.items():
        for template in STAGING_MODELS:
            name = template.format(domain=config["prefix"])
            source_deps = [
                f"source.ecommerce.{s}"
                for s in random.sample(raw_sources, k=min(2, len(raw_sources)))
            ]
            tags = config["tags"] + ["staging"]

            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = generate_model(name, domain, "staging", source_deps, tags)
            domain_models[domain]["staging"].append(node_id)

    # Generate intermediate models (depend on staging)
    for domain, config in DOMAINS.items():
        staging = domain_models[domain]["staging"]
        for template in INTERMEDIATE_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(staging, k=min(2, len(staging))) if staging else []
            tags = config["tags"] + ["intermediate"]

            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = generate_model(name, domain, "intermediate", deps, tags)
            domain_models[domain]["intermediate"].append(node_id)

    # Generate dimension models (depend on staging + intermediate)
    for domain, config in DOMAINS.items():
        all_upstream = domain_models[domain]["staging"] + domain_models[domain]["intermediate"]
        for template in DIMENSION_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(all_upstream, k=min(3, len(all_upstream))) if all_upstream else []
            tags = config["tags"] + ["dimension"]

            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = generate_model(name, domain, "dimension", deps, tags)
            domain_models[domain]["dimension"].append(node_id)

    # Generate fact models (depend on dimensions + intermediate)
    for domain, config in DOMAINS.items():
        dims = domain_models[domain]["dimension"]
        ints = domain_models[domain]["intermediate"]
        for template in FACT_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(dims, k=min(2, len(dims))) + random.sample(
                ints, k=min(1, len(ints))
            )
            tags = config["tags"] + ["fact"]

            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = generate_model(name, domain, "fact", deps, tags)
            domain_models[domain]["fact"].append(node_id)

    # Generate mart models (depend on facts + dimensions, can cross domains)
    for domain, config in DOMAINS.items():
        facts = domain_models[domain]["fact"]
        dims = domain_models[domain]["dimension"]

        # Cross-domain dependencies for some marts
        other_domains = [d for d in DOMAINS if d != domain]
        cross_domain_facts = []
        for other in random.sample(other_domains, k=min(2, len(other_domains))):
            cross_domain_facts.extend(domain_models[other]["fact"][:1])

        for template in MART_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(facts, k=min(2, len(facts))) + random.sample(
                dims, k=min(1, len(dims))
            )

            # Some marts have cross-domain deps
            if random.random() > 0.5 and cross_domain_facts:
                deps.append(random.choice(cross_domain_facts))

            tags = config["tags"] + ["mart", "business-critical"]

            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = generate_model(name, domain, "mart", deps, tags)
            domain_models[domain]["mart"].append(node_id)

    # Add some shared/utility models
    shared_models = [
        ("util_date_spine", [], ["utility"]),
        ("util_calendar", ["model.ecommerce.util_date_spine"], ["utility"]),
        ("dim_date", ["model.ecommerce.util_calendar"], ["utility", "dimension"]),
        ("dim_time", [], ["utility", "dimension"]),
        ("stg_currency_rates", ["source.ecommerce.raw_transactions"], ["utility", "staging"]),
        (
            "int_currency_conversion",
            ["model.ecommerce.stg_currency_rates"],
            ["utility", "intermediate"],
        ),
    ]

    for name, deps, tags in shared_models:
        node_id = f"model.ecommerce.{name}"
        nodes[node_id] = generate_model(name, "shared", "utility", deps, tags)

    return {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v11.json",
            "generated_at": "2025-01-01T00:00:00Z",
            "project_name": "ecommerce",
        },
        "nodes": nodes,
        "sources": sources,
    }


def main():
    manifest = generate_manifest()

    # Count models by layer
    layers = {"staging": 0, "intermediate": 0, "dimension": 0, "fact": 0, "mart": 0, "utility": 0}
    for node in manifest["nodes"].values():
        for tag in node.get("tags", []):
            if tag in layers:
                layers[tag] += 1
                break

    print("Generated manifest with:")
    print(f"  Sources: {len(manifest['sources'])}")
    print(f"  Models: {len(manifest['nodes'])}")
    for layer, count in layers.items():
        print(f"    {layer}: {count}")

    # Write manifest
    output_path = Path(__file__).parent.parent / "examples" / "data" / "manifest.json"
    output_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWritten to {output_path}")


if __name__ == "__main__":
    main()
