"""Tessera CLI - Data contract coordination from the command line."""

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="tessera",
    help="Data contract coordination for warehouses",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# Sub-commands
team_app = typer.Typer(help="Manage teams")
asset_app = typer.Typer(help="Manage assets")
contract_app = typer.Typer(help="Manage contracts")
proposal_app = typer.Typer(help="Manage breaking change proposals")

app.add_typer(team_app, name="team")
app.add_typer(asset_app, name="asset")
app.add_typer(contract_app, name="contract")
app.add_typer(proposal_app, name="proposal")


def get_base_url() -> str:
    """Get the Tessera API base URL from environment or default."""
    import os

    return os.environ.get("TESSERA_URL", "http://localhost:8000")


def get_api_key() -> str | None:
    """Get the API key from environment."""
    import os

    return os.environ.get("TESSERA_API_KEY")


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


def handle_response(response: httpx.Response) -> Any:
    """Handle API response, raising on errors.

    Returns the JSON response which may be a dict or list depending on the endpoint.
    """
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        err_console.print(f"[red]Error ({response.status_code}):[/red] {detail}")
        raise typer.Exit(1)
    if response.status_code == 204:
        return {}
    return response.json()


# ============================================================================
# Team commands
# ============================================================================


@team_app.command("create")
def team_create(
    name: Annotated[str, typer.Argument(help="Team name")],
    metadata: Annotated[str | None, typer.Option("--metadata", "-m", help="JSON metadata")] = None,
) -> None:
    """Create a new team."""
    data: dict[str, Any] = {"name": name}
    if metadata:
        data["metadata"] = json.loads(metadata)

    response = make_request("POST", "/teams", json_data=data)
    team = handle_response(response)
    console.print(f"[green]Created team:[/green] {team['name']} (id: {team['id']})")


@team_app.command("list")
def team_list() -> None:
    """List all teams."""
    response = make_request("GET", "/teams")
    teams = handle_response(response)

    if not teams:
        console.print("[dim]No teams found[/dim]")
        return

    table = Table(title="Teams")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Created")

    for team in teams:
        table.add_row(team["id"], team["name"], team["created_at"][:10])

    console.print(table)


@team_app.command("get")
def team_get(
    team_id: Annotated[str, typer.Argument(help="Team ID")],
) -> None:
    """Get team details."""
    response = make_request("GET", f"/teams/{team_id}")
    team = handle_response(response)
    console.print_json(json.dumps(team))


# ============================================================================
# Asset commands
# ============================================================================


@asset_app.command("create")
def asset_create(
    fqn: Annotated[str, typer.Argument(help="Fully qualified name (e.g., warehouse.schema.table)")],
    owner_team_id: Annotated[str, typer.Option("--team", "-t", help="Owner team ID")],
    metadata: Annotated[str | None, typer.Option("--metadata", "-m", help="JSON metadata")] = None,
) -> None:
    """Create a new asset."""
    data: dict[str, Any] = {"fqn": fqn, "owner_team_id": owner_team_id}
    if metadata:
        data["metadata"] = json.loads(metadata)

    response = make_request("POST", "/assets", json_data=data)
    asset = handle_response(response)
    console.print(f"[green]Created asset:[/green] {asset['fqn']} (id: {asset['id']})")


@asset_app.command("list")
def asset_list(
    team_id: Annotated[str | None, typer.Option("--team", "-t", help="Filter by team ID")] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 50,
) -> None:
    """List assets."""
    params: dict[str, Any] = {"limit": limit}
    if team_id:
        params["team_id"] = team_id

    response = make_request("GET", "/assets", params=params)
    result = handle_response(response)
    assets = result.get("results", [])

    if not assets:
        console.print("[dim]No assets found[/dim]")
        return

    table = Table(title="Assets")
    table.add_column("ID", style="dim")
    table.add_column("FQN", style="bold")
    table.add_column("Owner Team")

    for asset in assets:
        table.add_row(asset["id"], asset["fqn"], asset["owner_team_id"])

    console.print(table)


@asset_app.command("get")
def asset_get(
    asset_id: Annotated[str, typer.Argument(help="Asset ID")],
) -> None:
    """Get asset details."""
    response = make_request("GET", f"/assets/{asset_id}")
    asset = handle_response(response)
    console.print_json(json.dumps(asset))


@asset_app.command("search")
def asset_search(
    query: Annotated[str, typer.Argument(help="Search query (matches FQN)")],
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
) -> None:
    """Search for assets by FQN."""
    params = {"q": query, "limit": limit}
    response = make_request("GET", "/assets/search", params=params)
    result = handle_response(response)
    assets = result.get("results", [])

    if not assets:
        console.print(f"[dim]No assets matching '{query}'[/dim]")
        return

    table = Table(title=f"Assets matching '{query}'")
    table.add_column("ID", style="dim")
    table.add_column("FQN", style="bold")

    for asset in assets:
        table.add_row(asset["id"], asset["fqn"])

    console.print(table)


# ============================================================================
# Contract commands
# ============================================================================


@contract_app.command("publish")
def contract_publish(
    asset_id: Annotated[str, typer.Option("--asset", "-a", help="Asset ID")],
    version: Annotated[str, typer.Option("--version", "-v", help="Contract version")],
    schema_file: Annotated[Path, typer.Option("--schema", "-s", help="Path to JSON schema file")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Publisher team ID")],
    compatibility: Annotated[
        str, typer.Option("--compat", "-c", help="Compatibility mode")
    ] = "backward",
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force publish breaking changes")
    ] = False,
) -> None:
    """Publish a new contract version."""
    if not schema_file.exists():
        err_console.print(f"[red]Schema file not found:[/red] {schema_file}")
        raise typer.Exit(1)

    schema = json.loads(schema_file.read_text())
    data = {
        "version": version,
        "schema": schema,
        "compatibility_mode": compatibility,
        "publisher_team_id": team_id,
        "force": force,
    }

    response = make_request("POST", f"/assets/{asset_id}/contracts", json_data=data)
    result = handle_response(response)

    if "proposal" in result:
        proposal = result["proposal"]
        console.print("[yellow]Breaking change detected![/yellow]")
        console.print(f"Proposal created: {proposal['id']}")
        console.print(f"Status: {proposal['status']}")
        if result.get("breaking_changes"):
            console.print("\nBreaking changes:")
            for bc in result["breaking_changes"]:
                console.print(f"  - {bc['change_type']}: {bc['message']}")
    else:
        contract = result.get("contract", result)
        console.print(f"[green]Published contract:[/green] v{contract['version']}")


@contract_app.command("list")
def contract_list(
    asset_id: Annotated[str, typer.Argument(help="Asset ID")],
) -> None:
    """List contracts for an asset."""
    response = make_request("GET", f"/assets/{asset_id}/contracts")
    result = handle_response(response)
    contracts = result.get("results", [])

    if not contracts:
        console.print("[dim]No contracts found[/dim]")
        return

    table = Table(title="Contracts")
    table.add_column("ID", style="dim")
    table.add_column("Version", style="bold")
    table.add_column("Status")
    table.add_column("Published")

    for contract in contracts:
        status_style = "green" if contract["status"] == "active" else "dim"
        table.add_row(
            contract["id"],
            contract["version"],
            f"[{status_style}]{contract['status']}[/{status_style}]",
            contract["published_at"][:10],
        )

    console.print(table)


@contract_app.command("diff")
def contract_diff(
    asset_id: Annotated[str, typer.Argument(help="Asset ID")],
    from_version: Annotated[str, typer.Option("--from", help="From version")] = "",
    to_version: Annotated[str, typer.Option("--to", help="To version")] = "",
) -> None:
    """Show differences between contract versions."""
    params = {}
    if from_version:
        params["from_version"] = from_version
    if to_version:
        params["to_version"] = to_version

    response = make_request("GET", f"/assets/{asset_id}/contracts/diff", params=params)
    result = handle_response(response)

    console.print(f"[bold]Comparing:[/bold] v{result['from_version']} -> v{result['to_version']}")
    console.print(f"[bold]Change type:[/bold] {result['change_type']}")
    console.print(f"[bold]Is breaking:[/bold] {result['is_breaking']}")

    if result.get("changes"):
        console.print("\n[bold]Changes:[/bold]")
        for change in result["changes"]:
            style = "red" if change.get("breaking") else "green"
            console.print(f"  [{style}]{change['change_type']}[/{style}]: {change['message']}")


@contract_app.command("impact")
def contract_impact(
    asset_id: Annotated[str, typer.Argument(help="Asset ID")],
    schema_file: Annotated[
        Path, typer.Option("--schema", "-s", help="Path to proposed JSON schema file")
    ],
) -> None:
    """Analyze impact of a proposed schema change."""
    if not schema_file.exists():
        err_console.print(f"[red]Schema file not found:[/red] {schema_file}")
        raise typer.Exit(1)

    schema = json.loads(schema_file.read_text())
    data = {"proposed_schema": schema}

    response = make_request("POST", f"/assets/{asset_id}/impact", json_data=data)
    result = handle_response(response)

    console.print(f"[bold]Change type:[/bold] {result['change_type']}")
    console.print(f"[bold]Is breaking:[/bold] {result['is_breaking']}")

    if result.get("breaking_changes"):
        console.print("\n[red]Breaking changes:[/red]")
        for bc in result["breaking_changes"]:
            console.print(f"  - {bc['change_type']}: {bc['message']}")

    if result.get("impacted_consumers"):
        console.print(f"\n[yellow]Impacted consumers:[/yellow] {len(result['impacted_consumers'])}")
        for consumer in result["impacted_consumers"]:
            pinned = consumer.get("pinned_version", "none")
            console.print(f"  - {consumer['team_name']} (pinned: {pinned})")


# ============================================================================
# Proposal commands
# ============================================================================


@proposal_app.command("list")
def proposal_list(
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    asset_id: Annotated[
        str | None, typer.Option("--asset", "-a", help="Filter by asset ID")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 50,
) -> None:
    """List breaking change proposals."""
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    if asset_id:
        params["asset_id"] = asset_id

    response = make_request("GET", "/proposals", params=params)
    result = handle_response(response)
    proposals = result.get("results", [])

    if not proposals:
        console.print("[dim]No proposals found[/dim]")
        return

    table = Table(title="Breaking Change Proposals")
    table.add_column("ID", style="dim")
    table.add_column("Asset ID")
    table.add_column("Status", style="bold")
    table.add_column("Proposed")

    for p in proposals:
        status_style = {
            "pending": "yellow",
            "approved": "green",
            "rejected": "red",
            "force_approved": "cyan",
            "withdrawn": "dim",
        }.get(p["status"], "white")
        table.add_row(
            p["id"][:8] + "...",
            p["asset_id"][:8] + "...",
            f"[{status_style}]{p['status']}[/{status_style}]",
            p["proposed_at"][:10],
        )

    console.print(table)


@proposal_app.command("get")
def proposal_get(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
) -> None:
    """Get proposal details."""
    response = make_request("GET", f"/proposals/{proposal_id}")
    proposal = handle_response(response)
    console.print_json(json.dumps(proposal))


@proposal_app.command("status")
def proposal_status(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
) -> None:
    """Get proposal acknowledgment status."""
    response = make_request("GET", f"/proposals/{proposal_id}/status")
    status = handle_response(response)

    console.print(f"[bold]Proposal:[/bold] {status['proposal_id']}")
    console.print(f"[bold]Status:[/bold] {status['status']}")
    console.print(f"[bold]Pending:[/bold] {status['pending_count']}")
    console.print(f"[bold]Acknowledged:[/bold] {status['acknowledged_count']}")
    console.print(f"[bold]Can publish:[/bold] {status['can_publish']}")

    if status.get("acknowledgments"):
        console.print("\n[bold]Acknowledgments:[/bold]")
        for ack in status["acknowledgments"]:
            style = "green" if ack["response"] == "approved" else "yellow"
            console.print(f"  [{style}]{ack['consumer_team_name']}[/{style}]: {ack['response']}")


@proposal_app.command("acknowledge")
def proposal_acknowledge(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Consumer team ID")],
    response_type: Annotated[
        str, typer.Option("--response", "-r", help="Response: approved, blocked, or migrating")
    ] = "approved",
    notes: Annotated[str | None, typer.Option("--notes", "-n", help="Optional notes")] = None,
) -> None:
    """Acknowledge a breaking change proposal."""
    data: dict[str, Any] = {
        "consumer_team_id": team_id,
        "response": response_type,
    }
    if notes:
        data["notes"] = notes

    resp = make_request("POST", f"/proposals/{proposal_id}/acknowledge", json_data=data)
    ack = handle_response(resp)
    console.print(f"[green]Acknowledged:[/green] {ack['response']}")


@proposal_app.command("withdraw")
def proposal_withdraw(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Producer team ID")],
) -> None:
    """Withdraw a pending proposal."""
    data = {"actor_team_id": team_id}
    response = make_request("POST", f"/proposals/{proposal_id}/withdraw", json_data=data)
    proposal = handle_response(response)
    console.print(f"[green]Withdrawn:[/green] {proposal['id']}")


@proposal_app.command("force")
def proposal_force(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Producer team ID")],
) -> None:
    """Force approve a proposal (skips consumer acknowledgment)."""
    data = {"actor_team_id": team_id}
    response = make_request("POST", f"/proposals/{proposal_id}/force", json_data=data)
    proposal = handle_response(response)
    console.print(f"[yellow]Force approved:[/yellow] {proposal['id']}")


@proposal_app.command("publish")
def proposal_publish(
    proposal_id: Annotated[str, typer.Argument(help="Proposal ID")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Publisher team ID")],
) -> None:
    """Publish an approved proposal as a new contract."""
    data = {"publisher_team_id": team_id}
    response = make_request("POST", f"/proposals/{proposal_id}/publish", json_data=data)
    result = handle_response(response)
    contract = result.get("contract", result)
    console.print(f"[green]Published:[/green] v{contract['version']}")


# ============================================================================
# Registration command (top-level for convenience)
# ============================================================================


@app.command("register")
def register(
    asset_id: Annotated[str, typer.Option("--asset", "-a", help="Asset ID")],
    team_id: Annotated[str, typer.Option("--team", "-t", help="Consumer team ID")],
    pinned_version: Annotated[
        str | None, typer.Option("--pin", "-p", help="Pin to specific version")
    ] = None,
) -> None:
    """Register as a consumer of an asset."""
    data: dict[str, Any] = {
        "asset_id": asset_id,
        "consumer_team_id": team_id,
    }
    if pinned_version:
        data["pinned_version"] = pinned_version

    response = make_request("POST", "/registrations", json_data=data)
    reg = handle_response(response)
    console.print(f"[green]Registered:[/green] {reg['id']}")
    if reg.get("pinned_version"):
        console.print(f"  Pinned to: v{reg['pinned_version']}")


# ============================================================================
# Server command
# ============================================================================


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", "-h", help="Host to bind")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", "-r", help="Enable auto-reload")] = False,
) -> None:
    """Start the Tessera API server."""
    import uvicorn

    uvicorn.run("tessera.main:app", host=host, port=port, reload=reload)


# ============================================================================
# Version command
# ============================================================================


@app.command("version")
def version() -> None:
    """Show Tessera version."""
    console.print("tessera 0.1.0")


# Import and register dbt subcommand at the end to avoid circular imports
from tessera.cli.dbt import app as dbt_app  # noqa: E402

app.add_typer(dbt_app, name="dbt")


if __name__ == "__main__":
    app()
