#!/usr/bin/env python3
"""Generate a realistic dbt manifest with ~250 models, tests, and tessera meta for testing."""

import json
import random
from pathlib import Path

# Domain-specific schemas and naming with teams
DOMAINS = {
    "core": {
        "prefix": "core",
        "teams": ["data-platform"],
        "users": ["alice@company.com", "bob@company.com"],
        "tags": ["core", "sla-critical"],
    },
    "marketing": {
        "prefix": "mktg",
        "teams": ["marketing-analytics"],
        "users": ["carol@company.com", "dan@company.com"],
        "tags": ["marketing", "pii"],
    },
    "finance": {
        "prefix": "fin",
        "teams": ["finance-analytics"],
        "users": ["emma@company.com", "frank@company.com"],
        "tags": ["finance", "sox-compliant", "pii"],
    },
    "product": {
        "prefix": "prod",
        "teams": ["product-analytics"],
        "users": ["grace@company.com", "henry@company.com"],
        "tags": ["product", "events"],
    },
    "sales": {
        "prefix": "sales",
        "teams": ["sales-ops"],
        "users": ["iris@company.com", "jack@company.com"],
        "tags": ["sales", "crm"],
    },
    "support": {
        "prefix": "support",
        "teams": ["sales-ops"],  # Shared with sales
        "users": ["kate@company.com", "leo@company.com"],
        "tags": ["support", "tickets"],
    },
}

# Valid status values for accepted_values tests
STATUS_VALUES = {
    "user_status": ["active", "inactive", "pending", "suspended"],
    "order_status": ["pending", "confirmed", "shipped", "delivered", "cancelled"],
    "payment_status": ["pending", "completed", "failed", "refunded"],
    "subscription_status": ["trial", "active", "cancelled", "expired"],
    "ticket_status": ["open", "in_progress", "resolved", "closed"],
    "campaign_status": ["draft", "active", "paused", "completed"],
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
                "status": {
                    "name": "status",
                    "description": "User status",
                    "data_type": "string",
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
                "status": {
                    "name": "status",
                    "description": "Payment status",
                    "data_type": "string",
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
                "user_id": {
                    "name": "user_id",
                    "description": "Foreign key to users",
                    "data_type": "integer",
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
                "status": {
                    "name": "status",
                    "description": "Campaign status",
                    "data_type": "string",
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

    if "order" in model_name:
        columns.update(
            {
                "order_id": {
                    "name": "order_id",
                    "description": "Order identifier",
                    "data_type": "integer",
                },
                "customer_id": {
                    "name": "customer_id",
                    "description": "Customer identifier",
                    "data_type": "integer",
                },
                "status": {
                    "name": "status",
                    "description": "Order status",
                    "data_type": "string",
                },
            }
        )

    if "ticket" in model_name or "support" in model_name:
        columns.update(
            {
                "ticket_id": {
                    "name": "ticket_id",
                    "description": "Support ticket ID",
                    "data_type": "integer",
                },
                "priority": {
                    "name": "priority",
                    "description": "Ticket priority",
                    "data_type": "string",
                },
                "status": {
                    "name": "status",
                    "description": "Ticket status",
                    "data_type": "string",
                },
            }
        )

    return columns


def generate_tests_for_model(
    model_name: str,
    model_id: str,
    columns: dict,
    depends_on_models: list[str],
    project_name: str = "ecommerce",
) -> dict:
    """Generate dbt test nodes for a model's columns.

    Supports:
    - not_null tests (standard dbt)
    - unique tests (standard dbt)
    - accepted_values tests (standard dbt)
    - relationships tests (standard dbt)
    - dbt_utils tests (expression_is_true, at_least_one, etc.)
    - dbt_expectations tests
    - Custom SQL tests
    """
    tests = {}
    pk_column = None

    # Find primary key column
    for col_name in columns:
        if col_name.endswith("_id") and col_name != "user_id" and col_name != "customer_id":
            pk_column = col_name
            break

    # Generate tests for each column
    for col_name, col_info in columns.items():
        # not_null tests for important columns
        if col_name in [pk_column, "created_at", "email", "name", "amount", "status"]:
            test_id = f"test.{project_name}.not_null_{model_name}_{col_name}"
            tests[test_id] = {
                "name": f"not_null_{model_name}_{col_name}",
                "resource_type": "test",
                "unique_id": test_id,
                "depends_on": {"nodes": [model_id]},
                "column_name": col_name,
                "test_metadata": {
                    "name": "not_null",
                    "kwargs": {"column_name": col_name},
                },
            }

        # unique test for primary key
        if col_name == pk_column:
            test_id = f"test.{project_name}.unique_{model_name}_{col_name}"
            tests[test_id] = {
                "name": f"unique_{model_name}_{col_name}",
                "resource_type": "test",
                "unique_id": test_id,
                "depends_on": {"nodes": [model_id]},
                "column_name": col_name,
                "test_metadata": {
                    "name": "unique",
                    "kwargs": {"column_name": col_name},
                },
            }

        # accepted_values for status columns
        if col_name == "status":
            # Determine which status values to use based on model name
            status_key = "user_status"  # default
            if "order" in model_name:
                status_key = "order_status"
            elif "payment" in model_name or "transaction" in model_name:
                status_key = "payment_status"
            elif "subscription" in model_name:
                status_key = "subscription_status"
            elif "ticket" in model_name or "support" in model_name:
                status_key = "ticket_status"
            elif "campaign" in model_name:
                status_key = "campaign_status"

            test_id = f"test.{project_name}.accepted_values_{model_name}_{col_name}"
            tests[test_id] = {
                "name": f"accepted_values_{model_name}_{col_name}",
                "resource_type": "test",
                "unique_id": test_id,
                "depends_on": {"nodes": [model_id]},
                "column_name": col_name,
                "test_metadata": {
                    "name": "accepted_values",
                    "kwargs": {
                        "column_name": col_name,
                        "values": STATUS_VALUES[status_key],
                    },
                },
            }

        # relationships tests for foreign keys
        if col_name in ["user_id", "customer_id", "order_id"] and depends_on_models:
            # Find a parent model that likely has this column as PK
            parent_model = None
            for dep in depends_on_models:
                if "user" in dep and col_name == "user_id":
                    parent_model = dep
                    break
                elif "customer" in dep and col_name == "customer_id":
                    parent_model = dep
                    break
                elif "order" in dep and col_name == "order_id":
                    parent_model = dep
                    break

            if parent_model:
                test_id = f"test.{project_name}.relationships_{model_name}_{col_name}"
                tests[test_id] = {
                    "name": f"relationships_{model_name}_{col_name}",
                    "resource_type": "test",
                    "unique_id": test_id,
                    "depends_on": {"nodes": [model_id, parent_model]},
                    "column_name": col_name,
                    "test_metadata": {
                        "name": "relationships",
                        "kwargs": {
                            "column_name": col_name,
                            "to": parent_model.split(".")[-1],
                            "field": col_name,
                        },
                    },
                }

    # dbt_utils tests for certain models
    if "amount" in columns or "total_amount" in columns:
        amount_col = "amount" if "amount" in columns else "total_amount"
        # expression_is_true: amount >= 0
        test_id = (
            f"test.{project_name}.dbt_utils_expression_is_true_{model_name}_{amount_col}_positive"
        )
        tests[test_id] = {
            "name": f"dbt_utils_expression_is_true_{model_name}_{amount_col}_positive",
            "resource_type": "test",
            "unique_id": test_id,
            "depends_on": {"nodes": [model_id]},
            "column_name": amount_col,
            "test_metadata": {
                "name": "dbt_utils.expression_is_true",
                "namespace": "dbt_utils",
                "kwargs": {
                    "expression": f"{amount_col} >= 0",
                },
            },
        }

    # dbt_utils.at_least_one for staging tables
    if model_name.startswith("stg_") and pk_column:
        test_id = f"test.{project_name}.dbt_utils_at_least_one_{model_name}_{pk_column}"
        tests[test_id] = {
            "name": f"dbt_utils_at_least_one_{model_name}_{pk_column}",
            "resource_type": "test",
            "unique_id": test_id,
            "depends_on": {"nodes": [model_id]},
            "column_name": pk_column,
            "test_metadata": {
                "name": "dbt_utils.at_least_one",
                "namespace": "dbt_utils",
                "kwargs": {
                    "column_name": pk_column,
                },
            },
        }

    # dbt_expectations tests for date columns
    for col_name in columns:
        if "date" in col_name or col_name.endswith("_at"):
            # expect_column_values_to_be_of_type
            test_id = (
                f"test.{project_name}.dbt_expectations_expect_column_to_exist_"
                f"{model_name}_{col_name}"
            )
            tests[test_id] = {
                "name": f"dbt_expectations_expect_column_to_exist_{model_name}_{col_name}",
                "resource_type": "test",
                "unique_id": test_id,
                "depends_on": {"nodes": [model_id]},
                "column_name": col_name,
                "test_metadata": {
                    "name": "dbt_expectations.expect_column_to_exist",
                    "namespace": "dbt_expectations",
                    "kwargs": {
                        "column_name": col_name,
                    },
                },
            }
            break  # Only one per model

    # Custom SQL test for some models (row count check)
    if model_name.startswith("mart_") and random.random() > 0.7:
        test_id = f"test.{project_name}.{model_name}_row_count_check"
        tests[test_id] = {
            "name": f"{model_name}_row_count_check",
            "resource_type": "test",
            "unique_id": test_id,
            "depends_on": {"nodes": [model_id]},
            "test_metadata": {
                "name": "custom_sql",
                "kwargs": {
                    "sql": (
                        f"SELECT CASE WHEN COUNT(*) > 0 THEN 0 ELSE 1 END "
                        f"AS failures FROM {{{{ ref('{model_name}') }}}}"
                    ),
                    "description": "Ensures mart has at least one row",
                },
            },
        }

    return tests


def generate_model(
    name: str,
    domain: str,
    layer: str,
    depends_on: list[str],
    tags: list[str],
    domain_config: dict,
) -> tuple[dict, dict]:
    """Generate a dbt model node and its tests."""
    schema = "staging" if layer == "staging" else "analytics"
    model_id = f"model.ecommerce.{name}"

    # Pick owner from domain config
    owner_team = random.choice(domain_config["teams"])
    owner_user = random.choice(domain_config["users"]) if domain_config["users"] else None

    # Generate tessera meta for ownership
    tessera_meta = {
        "owner_team": owner_team,
    }
    if owner_user:
        tessera_meta["owner_user"] = owner_user

    # Add SLA guarantees for critical models
    if "sla-critical" in tags or layer == "mart":
        tessera_meta["freshness"] = {
            "max_staleness_minutes": 60 if layer == "mart" else 120,
            "measured_by": "updated_at" if "updated_at" in tags else "created_at",
        }
        tessera_meta["volume"] = {
            "min_rows": 100 if layer == "staging" else 10,
            "max_row_delta_pct": 50,
        }

    # Add consumer declarations for some models
    if layer == "mart" and random.random() > 0.5:
        # Other teams might consume this mart
        other_teams = ["marketing-analytics", "finance-analytics", "product-analytics", "sales-ops"]
        other_teams = [t for t in other_teams if t != owner_team]
        if other_teams:
            consumers = [{"team": random.choice(other_teams), "purpose": "Reporting"}]
            tessera_meta["consumers"] = consumers

    columns = generate_columns(name, layer)

    model = {
        "name": name,
        "resource_type": "model",
        "schema": schema,
        "database": "warehouse",
        "unique_id": model_id,
        "fqn": ["ecommerce", domain, name],
        "description": f"{layer.title()} model for {domain} domain: {name.replace('_', ' ')}",
        "columns": columns,
        "depends_on": {"nodes": depends_on},
        "path": f"models/{domain}/{layer}/{name}.sql",
        "tags": tags,
        "meta": {
            "tessera": tessera_meta,
        },
    }

    # Generate tests for this model
    tests = generate_tests_for_model(name, model_id, columns, depends_on)

    return model, tests


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
    """Generate a complete dbt manifest with tests."""
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

            model, tests = generate_model(name, domain, "staging", source_deps, tags, config)
            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = model
            nodes.update(tests)
            domain_models[domain]["staging"].append(node_id)

    # Generate intermediate models (depend on staging)
    for domain, config in DOMAINS.items():
        staging = domain_models[domain]["staging"]
        for template in INTERMEDIATE_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(staging, k=min(2, len(staging))) if staging else []
            tags = config["tags"] + ["intermediate"]

            model, tests = generate_model(name, domain, "intermediate", deps, tags, config)
            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = model
            nodes.update(tests)
            domain_models[domain]["intermediate"].append(node_id)

    # Generate dimension models (depend on staging + intermediate)
    for domain, config in DOMAINS.items():
        all_upstream = domain_models[domain]["staging"] + domain_models[domain]["intermediate"]
        for template in DIMENSION_MODELS:
            name = template.format(domain=config["prefix"])
            deps = random.sample(all_upstream, k=min(3, len(all_upstream))) if all_upstream else []
            tags = config["tags"] + ["dimension"]

            model, tests = generate_model(name, domain, "dimension", deps, tags, config)
            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = model
            nodes.update(tests)
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

            model, tests = generate_model(name, domain, "fact", deps, tags, config)
            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = model
            nodes.update(tests)
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

            model, tests = generate_model(name, domain, "mart", deps, tags, config)
            node_id = f"model.ecommerce.{name}"
            nodes[node_id] = model
            nodes.update(tests)
            domain_models[domain]["mart"].append(node_id)

    # Add some shared/utility models
    shared_config = {
        "prefix": "util",
        "teams": ["data-platform"],
        "users": ["alice@company.com"],
        "tags": ["utility"],
    }
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
        model, tests = generate_model(name, "shared", "utility", deps, tags, shared_config)
        node_id = f"model.ecommerce.{name}"
        nodes[node_id] = model
        nodes.update(tests)

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

    # Count models by layer and tests
    layers = {"staging": 0, "intermediate": 0, "dimension": 0, "fact": 0, "mart": 0, "utility": 0}
    test_count = 0
    for node_id, node in manifest["nodes"].items():
        if node.get("resource_type") == "test":
            test_count += 1
        else:
            for tag in node.get("tags", []):
                if tag in layers:
                    layers[tag] += 1
                    break

    print("Generated manifest with:")
    print(f"  Sources: {len(manifest['sources'])}")
    print(f"  Models: {sum(layers.values())}")
    for layer, count in layers.items():
        print(f"    {layer}: {count}")
    print(f"  Tests: {test_count}")

    # Write manifest
    output_path = Path(__file__).parent.parent / "examples" / "data" / "manifest.json"
    output_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWritten to {output_path}")


if __name__ == "__main__":
    main()
