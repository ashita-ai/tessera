"""dbt integration CLI commands for Tessera.

Provides CI/CD integration for checking schema changes in dbt projects.
"""

import json
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="dbt integration commands")
console = Console()
err_console = Console(stderr=True)


def get_base_url() -> str:
    """Get the Tessera API base URL from environment or default."""
    return os.environ.get("TESSERA_URL", "http://localhost:8000")


def get_api_key() -> str | None:
    """Get the API key from environment."""
    return os.environ.get("TESSERA_API_KEY")


def get_team_id() -> str | None:
    """Get the default team ID from environment."""
    return os.environ.get("TESSERA_TEAM_ID")


def make_request(
    method: str,
    path: str,
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """Make an HTTP request to the Tessera API."""
    url = f"{get_base_url()}/api/v1{path}"
    headers: dict[str, str] = {}
    api_key = get_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method=method,
            url=url,
            json=json_data,
            params=params,
            headers=headers,
        )
    return response


def extract_schema_from_columns(columns: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt column definitions to JSON Schema.

    dbt columns look like:
    {
        "id": {"name": "id", "data_type": "integer", ...},
        "name": {"name": "name", "data_type": "string", ...}
    }
    """
    type_mapping = {
        "integer": "integer",
        "int": "integer",
        "bigint": "integer",
        "int64": "integer",
        "smallint": "integer",
        "string": "string",
        "varchar": "string",
        "text": "string",
        "char": "string",
        "float": "number",
        "double": "number",
        "decimal": "number",
        "numeric": "number",
        "float64": "number",
        "boolean": "boolean",
        "bool": "boolean",
        "date": "string",
        "datetime": "string",
        "timestamp": "string",
        "timestamp_ntz": "string",
        "timestamp_tz": "string",
        "time": "string",
        "array": "array",
        "json": "object",
        "struct": "object",
        "record": "object",
        "variant": "object",
    }

    properties: dict[str, Any] = {}
    for col_name, col_def in columns.items():
        data_type = col_def.get("data_type", "string").lower()
        # Handle complex types like ARRAY<STRING>
        base_type = data_type.split("<")[0].split("(")[0].strip()
        json_type = type_mapping.get(base_type, "string")

        prop: dict[str, Any] = {"type": json_type}
        if col_def.get("description"):
            prop["description"] = col_def["description"]

        properties[col_name] = prop

    return {
        "type": "object",
        "properties": properties,
    }


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load dbt manifest.json file."""
    if not manifest_path.exists():
        err_console.print(f"[red]Manifest not found:[/red] {manifest_path}")
        err_console.print("Run 'dbt compile' or 'dbt build' first to generate the manifest.")
        raise typer.Exit(1)

    with open(manifest_path) as f:
        result: dict[str, Any] = json.load(f)
        return result


def get_models_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract model information from dbt manifest."""
    models = []
    nodes = manifest.get("nodes", {})

    for node_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue

        # Build FQN: database.schema.alias
        database = node.get("database", "")
        schema = node.get("schema", "")
        alias = node.get("alias") or node.get("name", "")

        fqn = f"{database}.{schema}.{alias}"

        # Extract columns as schema
        columns = node.get("columns", {})
        schema_def = extract_schema_from_columns(columns) if columns else None

        models.append(
            {
                "node_id": node_id,
                "name": node.get("name", ""),
                "fqn": fqn,
                "schema": schema_def,
                "description": node.get("description", ""),
                "columns": columns,
                "meta": node.get("meta", {}),
                "tags": node.get("tags", []),
            }
        )

    return models


@app.command("check")
def check(
    manifest_path: Annotated[
        Path, typer.Option("--manifest", "-m", help="Path to dbt manifest.json file")
    ] = Path("target/manifest.json"),
    team_id: Annotated[
        str | None, typer.Option("--team", "-t", help="Publisher team ID (or set TESSERA_TEAM_ID)")
    ] = None,
    create_proposals: Annotated[
        bool, typer.Option("--create-proposals", "-p", help="Create proposals for breaking changes")
    ] = False,
    fail_on_breaking: Annotated[
        bool,
        typer.Option("--fail-on-breaking", "-f", help="Exit with error code on breaking changes"),
    ] = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output results as JSON")
    ] = False,
) -> None:
    """Check dbt models for schema changes against registered contracts.

    This command analyzes your dbt manifest.json and compares model schemas
    against contracts registered in Tessera. It reports:

    - New models not yet registered in Tessera
    - Compatible changes that can be auto-published
    - Breaking changes that require consumer acknowledgment

    Use this in CI/CD to catch breaking changes before they're deployed.

    Example:
        tessera dbt check --manifest target/manifest.json --team your-team-id
    """
    # Resolve team ID
    resolved_team_id = team_id or get_team_id()
    if not resolved_team_id and create_proposals:
        err_console.print("[red]Team ID required when creating proposals[/red]")
        err_console.print("Set TESSERA_TEAM_ID or use --team option")
        raise typer.Exit(1)

    # Load manifest
    manifest = load_manifest(manifest_path)
    models = get_models_from_manifest(manifest)

    if not models:
        console.print("[dim]No models found in manifest[/dim]")
        raise typer.Exit(0)

    # Results tracking
    results: dict[str, list[dict[str, Any]]] = {
        "new": [],
        "compatible": [],
        "breaking": [],
        "unchanged": [],
        "errors": [],
    }

    # Check each model against Tessera
    for model in models:
        if not model["schema"]:
            # Skip models without column definitions
            continue

        try:
            # Search for existing asset
            resp = make_request("GET", "/assets/search", params={"q": model["fqn"], "limit": 1})
            if resp.status_code != 200:
                results["errors"].append(
                    {
                        "model": model["name"],
                        "fqn": model["fqn"],
                        "error": f"API error: {resp.status_code}",
                    }
                )
                continue

            search_result = resp.json()
            items = search_result.get("results", [])

            if not items:
                # New model, not registered
                results["new"].append(model)
                continue

            asset = items[0]
            asset_id = asset["id"]

            # Check impact of proposed schema change
            impact_resp = make_request(
                "POST",
                f"/assets/{asset_id}/impact",
                json_data={"proposed_schema": model["schema"]},
            )

            if impact_resp.status_code != 200:
                results["errors"].append(
                    {
                        "model": model["name"],
                        "fqn": model["fqn"],
                        "error": f"Impact check failed: {impact_resp.status_code}",
                    }
                )
                continue

            impact = impact_resp.json()

            if impact.get("is_breaking"):
                model["breaking_changes"] = impact.get("breaking_changes", [])
                model["impacted_consumers"] = impact.get("impacted_consumers", [])
                model["asset_id"] = asset_id
                results["breaking"].append(model)

                # Optionally create proposal
                if create_proposals and resolved_team_id:
                    # Try to publish (will create proposal for breaking change)
                    contracts_resp = make_request("GET", f"/assets/{asset_id}/contracts")
                    if contracts_resp.status_code == 200:
                        contracts = contracts_resp.json().get("results", [])
                        current = next((c for c in contracts if c["status"] == "active"), None)
                        if current:
                            # Increment version
                            current_version = current.get("version", "1.0.0")
                            parts = current_version.split(".")
                            new_version = f"{int(parts[0]) + 1}.0.0"

                            publish_resp = make_request(
                                "POST",
                                f"/assets/{asset_id}/contracts",
                                json_data={
                                    "version": new_version,
                                    "schema": model["schema"],
                                    "compatibility_mode": "backward",
                                    "publisher_team_id": resolved_team_id,
                                },
                            )
                            if publish_resp.status_code in (200, 201):
                                publish_result = publish_resp.json()
                                if "proposal" in publish_result:
                                    model["proposal_id"] = publish_result["proposal"]["id"]

            elif impact.get("change_type") != "none":
                results["compatible"].append(model)
            else:
                results["unchanged"].append(model)

        except httpx.ConnectError:
            results["errors"].append(
                {
                    "model": model["name"],
                    "fqn": model["fqn"],
                    "error": "Cannot connect to Tessera API",
                }
            )

    # Output results
    if json_output:
        console.print_json(json.dumps(results, default=str))
    else:
        _print_results(results)

    # Exit code
    if results["breaking"] and fail_on_breaking:
        raise typer.Exit(1)
    if results["errors"]:
        raise typer.Exit(2)


def _print_results(results: dict[str, list[dict[str, Any]]]) -> None:
    """Print check results in a human-readable format."""
    # Summary
    console.print()
    console.print(
        Panel.fit(
            f"[bold]dbt Schema Check Results[/bold]\n\n"
            f"New models: {len(results['new'])}\n"
            f"Compatible: {len(results['compatible'])}\n"
            f"Breaking: {len(results['breaking'])}\n"
            f"Unchanged: {len(results['unchanged'])}\n"
            f"Errors: {len(results['errors'])}",
            title="Summary",
        )
    )

    # Breaking changes (most important)
    if results["breaking"]:
        console.print()
        console.print("[red bold]Breaking Changes Detected[/red bold]")
        for model in results["breaking"]:
            console.print(f"\n[red]{model['fqn']}[/red]")
            for bc in model.get("breaking_changes", []):
                console.print(f"  - {bc.get('message', bc)}")
            if model.get("impacted_consumers"):
                console.print("  [yellow]Impacted consumers:[/yellow]")
                for consumer in model["impacted_consumers"]:
                    console.print(f"    - {consumer.get('team_name', consumer)}")
            if model.get("proposal_id"):
                console.print(f"  [cyan]Proposal created:[/cyan] {model['proposal_id']}")

    # New models
    if results["new"]:
        console.print()
        console.print("[blue bold]New Models (not yet registered)[/blue bold]")
        table = Table()
        table.add_column("Model")
        table.add_column("FQN")
        for model in results["new"]:
            table.add_row(model["name"], model["fqn"])
        console.print(table)

    # Compatible changes
    if results["compatible"]:
        console.print()
        console.print("[green bold]Compatible Changes[/green bold]")
        for model in results["compatible"]:
            console.print(f"  {model['fqn']}")

    # Errors
    if results["errors"]:
        console.print()
        console.print("[red bold]Errors[/red bold]")
        for error in results["errors"]:
            console.print(f"  {error['model']}: {error['error']}")


@app.command("sync")
def sync(
    manifest_path: Annotated[
        Path, typer.Option("--manifest", "-m", help="Path to dbt manifest.json file")
    ] = Path("target/manifest.json"),
    team_id: Annotated[str, typer.Option("--team", "-t", help="Owner team ID for new assets")] = "",
    create_assets: Annotated[
        bool, typer.Option("--create-assets", "-c", help="Create assets for new models")
    ] = False,
    publish_compatible: Annotated[
        bool, typer.Option("--publish-compatible", help="Auto-publish compatible schema changes")
    ] = False,
) -> None:
    """Sync dbt models with Tessera.

    This command registers new dbt models as assets in Tessera and optionally
    publishes their schemas as contracts.

    Example:
        tessera dbt sync --manifest target/manifest.json --team your-team-id --create-assets
    """
    resolved_team_id = team_id or get_team_id()
    if not resolved_team_id:
        err_console.print("[red]Team ID required[/red]")
        err_console.print("Set TESSERA_TEAM_ID or use --team option")
        raise typer.Exit(1)

    # Load manifest
    manifest = load_manifest(manifest_path)
    models = get_models_from_manifest(manifest)

    if not models:
        console.print("[dim]No models found in manifest[/dim]")
        raise typer.Exit(0)

    created = 0
    published = 0
    skipped = 0
    errors = 0

    for model in models:
        if not model["schema"]:
            skipped += 1
            continue

        # Check if asset exists
        resp = make_request("GET", "/assets/search", params={"q": model["fqn"], "limit": 1})
        if resp.status_code != 200:
            errors += 1
            continue

        search_result = resp.json()
        items = search_result.get("results", [])

        if items:
            asset = items[0]
            asset_id = asset["id"]

            if publish_compatible:
                # Check if schema has changed (compatible changes only)
                impact_resp = make_request(
                    "POST",
                    f"/assets/{asset_id}/impact",
                    json_data={"proposed_schema": model["schema"]},
                )
                if impact_resp.status_code == 200:
                    impact = impact_resp.json()
                    if not impact.get("is_breaking") and impact.get("change_type") != "none":
                        # Get current version and increment
                        contracts_resp = make_request("GET", f"/assets/{asset_id}/contracts")
                        if contracts_resp.status_code == 200:
                            contracts = contracts_resp.json().get("results", [])
                            current = next((c for c in contracts if c["status"] == "active"), None)
                            if current:
                                v = current.get("version", "1.0.0")
                                parts = v.split(".")
                                new_v = f"{parts[0]}.{int(parts[1]) + 1}.0"
                                make_request(
                                    "POST",
                                    f"/assets/{asset_id}/contracts",
                                    json_data={
                                        "version": new_v,
                                        "schema": model["schema"],
                                        "compatibility_mode": "backward",
                                        "publisher_team_id": resolved_team_id,
                                    },
                                )
                                published += 1
                                console.print(f"[green]Published:[/green] {model['fqn']} v{new_v}")
        elif create_assets:
            # Create new asset
            create_resp = make_request(
                "POST",
                "/assets",
                json_data={
                    "fqn": model["fqn"],
                    "owner_team_id": resolved_team_id,
                    "metadata": {
                        "description": model.get("description", ""),
                        "tags": model.get("tags", []),
                        "dbt_node_id": model.get("node_id", ""),
                    },
                },
            )

            if create_resp.status_code == 201:
                asset = create_resp.json()
                created += 1
                console.print(f"[green]Created:[/green] {model['fqn']}")

                # Publish initial contract
                if model["schema"]:
                    make_request(
                        "POST",
                        f"/assets/{asset['id']}/contracts",
                        json_data={
                            "version": "1.0.0",
                            "schema": model["schema"],
                            "compatibility_mode": "backward",
                            "publisher_team_id": resolved_team_id,
                        },
                    )
                    published += 1
            else:
                errors += 1

    console.print()
    console.print("[bold]Sync complete:[/bold]")
    console.print(f"  Created: {created}")
    console.print(f"  Published: {published}")
    console.print(f"  Skipped: {skipped}")
    console.print(f"  Errors: {errors}")


@app.command("register")
def register_consumers(
    manifest_path: Annotated[
        Path, typer.Option("--manifest", "-m", help="Path to dbt manifest.json file")
    ] = Path("target/manifest.json"),
    team_id: Annotated[str, typer.Option("--team", "-t", help="Consumer team ID")] = "",
    upstream_only: Annotated[
        bool,
        typer.Option("--upstream", "-u", help="Only register for upstream (source) dependencies"),
    ] = False,
) -> None:
    """Register as a consumer of upstream dependencies.

    This command analyzes your dbt manifest to find models that depend on
    external sources or other projects, and registers your team as a consumer
    of those assets in Tessera.

    Example:
        tessera dbt register --manifest target/manifest.json --team your-team-id --upstream
    """
    resolved_team_id = team_id or get_team_id()
    if not resolved_team_id:
        err_console.print("[red]Team ID required[/red]")
        err_console.print("Set TESSERA_TEAM_ID or use --team option")
        raise typer.Exit(1)

    manifest = load_manifest(manifest_path)

    # Find sources (external dependencies)
    sources = manifest.get("sources", {})
    registered = 0
    not_found = 0

    for source_id, source in sources.items():
        database = source.get("database", "")
        schema = source.get("schema", "")
        name = source.get("name", "")
        fqn = f"{database}.{schema}.{name}"

        # Search for asset in Tessera
        resp = make_request("GET", "/assets/search", params={"q": fqn, "limit": 1})
        if resp.status_code == 200:
            items = resp.json().get("results", [])
            if items:
                asset = items[0]
                # Register as consumer
                reg_resp = make_request(
                    "POST",
                    "/registrations",
                    json_data={
                        "asset_id": asset["id"],
                        "consumer_team_id": resolved_team_id,
                    },
                )
                if reg_resp.status_code in (200, 201):
                    registered += 1
                    console.print(f"[green]Registered:[/green] {fqn}")
            else:
                not_found += 1
                console.print(f"[dim]Not found:[/dim] {fqn}")

    console.print()
    console.print("[bold]Registration complete:[/bold]")
    console.print(f"  Registered: {registered}")
    console.print(f"  Not found: {not_found}")
