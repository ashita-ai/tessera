"""Manifest parsing and metadata extraction for dbt sync."""

from typing import Any


class TesseraMetaConfig:
    """Parsed tessera configuration from dbt model meta."""

    def __init__(
        self,
        owner_team: str | None = None,
        owner_user: str | None = None,
        consumers: list[dict[str, Any]] | None = None,
        freshness: dict[str, Any] | None = None,
        volume: dict[str, Any] | None = None,
        compatibility_mode: str | None = None,
    ):
        self.owner_team = owner_team
        self.owner_user = owner_user
        self.consumers = consumers or []
        self.freshness = freshness
        self.volume = volume
        self.compatibility_mode = compatibility_mode


def extract_tessera_meta(node: dict[str, Any]) -> TesseraMetaConfig:
    """Extract tessera configuration from dbt model meta.

    Looks for meta.tessera in the node and parses ownership, consumers, and SLAs.

    Example dbt YAML:
    ```yaml
    models:
      - name: orders
        meta:
          tessera:
            owner_team: data-platform
            owner_user: alice@corp.com
            consumers:
              - team: marketing
                purpose: Campaign attribution
              - team: finance
            freshness:
              max_staleness_minutes: 60
            volume:
              min_rows: 1000
            compatibility_mode: backward
    ```
    """
    meta = node.get("meta", {})
    tessera_config = meta.get("tessera", {})

    if not tessera_config:
        return TesseraMetaConfig()

    return TesseraMetaConfig(
        owner_team=tessera_config.get("owner_team"),
        owner_user=tessera_config.get("owner_user"),
        consumers=tessera_config.get("consumers", []),
        freshness=tessera_config.get("freshness"),
        volume=tessera_config.get("volume"),
        compatibility_mode=tessera_config.get("compatibility_mode"),
    )


def extract_field_metadata_from_columns(
    columns: dict[str, Any],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Extract field descriptions and tags from dbt column definitions.

    Args:
        columns: dbt columns dict (col_name -> col_info)

    Returns:
        Tuple of (field_descriptions, field_tags) using JSONPath keys.
    """
    field_descriptions: dict[str, str] = {}
    field_tags: dict[str, list[str]] = {}

    for col_name, col_info in columns.items():
        path = f"$.properties.{col_name}"

        description = col_info.get("description", "")
        if description:
            field_descriptions[path] = description

        # Tags from column meta.tags or meta.tessera.tags
        meta = col_info.get("meta", {})
        col_tags = meta.get("tags", [])
        if not col_tags:
            tessera_meta = meta.get("tessera", {})
            col_tags = tessera_meta.get("tags", [])
        if col_tags:
            field_tags[path] = col_tags

    return field_descriptions, field_tags


def extract_asset_tags_from_node(node: dict[str, Any]) -> list[str]:
    """Extract asset-level tags from a dbt node.

    Looks at node.tags first, then falls back to meta.tags.
    """
    tags: list[str] = node.get("tags", [])
    if tags:
        return tags
    meta: dict[str, Any] = node.get("meta", {})
    return list(meta.get("tags", []))


def extract_guarantees_from_tests(
    node_id: str, node: dict[str, Any], all_nodes: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract guarantees from dbt tests attached to a model/source.

    Parses dbt test nodes and converts them to Tessera guarantees format:
    - not_null tests -> nullability: {column: "never"}
    - accepted_values tests -> accepted_values: {column: [values]}
    - unique tests -> custom: {type: "unique", column, config}
    - relationships tests -> custom: {type: "relationships", column, config}
    - dbt_expectations/dbt_utils tests -> custom: {type: test_name, column, config}
    - singular tests (SQL files) -> custom: {type: "singular", name, description, sql}

    Singular tests are SQL files in the tests/ directory that express custom
    business logic assertions (e.g., "market_value must equal shares * price").
    These become contract guarantees - removing them is a breaking change.

    Args:
        node_id: The dbt node ID (e.g., "model.project.users")
        node: The node data from manifest
        all_nodes: All nodes from the manifest to find related tests

    Returns:
        Guarantees dict if any tests found, None otherwise
    """
    nullability: dict[str, str] = {}
    accepted_values: dict[str, list[str]] = {}
    custom_tests: list[dict[str, Any]] = []

    # dbt tests reference their model via depends_on.nodes or attached via refs
    # Test nodes have patterns like: test.project.not_null_users_id
    # They contain test_metadata with test name and kwargs
    for test_id, test_node in all_nodes.items():
        if test_node.get("resource_type") != "test":
            continue

        # Check if test depends on this node
        depends_on = test_node.get("depends_on", {}).get("nodes", [])
        if node_id not in depends_on:
            continue

        # Extract test metadata
        test_metadata = test_node.get("test_metadata", {})
        test_name = test_metadata.get("name", "")
        kwargs = test_metadata.get("kwargs", {})

        # Get column name from kwargs or test config
        column_name = kwargs.get("column_name") or test_node.get("column_name")

        # Map standard dbt tests to guarantees
        if test_name == "not_null" and column_name:
            nullability[column_name] = "never"
        elif test_name == "accepted_values" and column_name:
            values = kwargs.get("values", [])
            if values:
                accepted_values[column_name] = values
        elif test_name in ("unique", "relationships"):
            # Store as custom test for reference
            custom_tests.append(
                {
                    "type": test_name,
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif test_name.startswith(("dbt_expectations.", "dbt_utils.")):
            # dbt-expectations and dbt-utils tests
            custom_tests.append(
                {
                    "type": test_name,
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif test_metadata.get("namespace"):
            # Other namespaced tests (custom packages)
            custom_tests.append(
                {
                    "type": f"{test_metadata['namespace']}.{test_name}",
                    "column": column_name,
                    "config": kwargs,
                }
            )
        elif not test_metadata:
            # Singular test (SQL file in tests/ directory) - no test_metadata
            # These express custom business logic assertions
            # e.g., "assert_market_value_consistency" checks market_value = shares * price
            test_name_from_id = test_id.split(".")[-1] if "." in test_id else test_id
            custom_tests.append(
                {
                    "type": "singular",
                    "name": test_name_from_id,
                    "description": test_node.get("description", ""),
                    # Store compiled SQL so consumers can see the assertion logic
                    "sql": test_node.get("compiled_code") or test_node.get("raw_code"),
                }
            )

    # Build guarantees dict only if we have something
    if not (nullability or accepted_values or custom_tests):
        return None

    guarantees: dict[str, Any] = {}
    if nullability:
        guarantees["nullability"] = nullability
    if accepted_values:
        guarantees["accepted_values"] = accepted_values
    if custom_tests:
        guarantees["custom"] = custom_tests

    return guarantees
