"""
Webhook Receiver Example
========================

A real webhook receiver that logs Tessera events.
Run this alongside docker-compose to see webhooks in action.

Run with: uv run python examples/webhook_receiver.py

Then configure Tessera to send webhooks:
  WEBHOOK_URL=http://host.docker.internal:5555/webhooks
  WEBHOOK_SECRET=dev-webhook-secret
"""

import hashlib
import hmac
import json
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = FastAPI(title="Tessera Webhook Receiver")
console = Console()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret")

# Store received events for inspection
received_events: list[dict] = []


def verify_signature(payload: bytes, signature: str | None) -> bool:
    """Verify HMAC-SHA256 signature from Tessera."""
    if not WEBHOOK_SECRET:
        return True

    if not signature or not signature.startswith("sha256="):
        return False

    expected = (
        "sha256="
        + hmac.new(
            WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected, signature)


def format_breaking_change(bc: dict) -> str:
    """Format a breaking change for display."""
    return f"[{bc.get('change_type', 'unknown')}] {bc.get('message', 'No message')}"


def display_proposal_created(payload: dict):
    """Display proposal.created event."""
    console.print(
        Panel.fit(
            f"[bold red]BREAKING CHANGE PROPOSED[/bold red]\n\n"
            f"Asset: {payload.get('asset_fqn', 'unknown')}\n"
            f"Version: {payload.get('proposed_version', 'unknown')}\n"
            f"Producer: {payload.get('producer_team_name', 'unknown')}",
            title="proposal.created",
            border_style="red",
        )
    )

    if payload.get("breaking_changes"):
        console.print("\n[bold]Breaking Changes:[/bold]")
        for bc in payload["breaking_changes"]:
            console.print(f"  - {format_breaking_change(bc)}")

    if payload.get("impacted_consumers"):
        console.print("\n[bold]Impacted Consumers:[/bold]")
        for consumer in payload["impacted_consumers"]:
            console.print(f"  - {consumer.get('team_name', 'unknown')}")


def display_proposal_acknowledged(payload: dict):
    """Display proposal.acknowledged event."""
    console.print(
        Panel.fit(
            f"[bold green]CONSUMER ACKNOWLEDGED[/bold green]\n\n"
            f"Asset: {payload.get('asset_fqn', 'unknown')}\n"
            f"Consumer: {payload.get('consumer_team_name', 'unknown')}\n"
            f"Response: {payload.get('response', 'unknown')}\n"
            f"Pending: {payload.get('pending_count', '?')} | "
            f"Acknowledged: {payload.get('acknowledged_count', '?')}",
            title="proposal.acknowledged",
            border_style="green",
        )
    )


def display_contract_published(payload: dict):
    """Display contract.published event."""
    console.print(
        Panel.fit(
            f"[bold blue]CONTRACT PUBLISHED[/bold blue]\n\n"
            f"Asset: {payload.get('asset_fqn', 'unknown')}\n"
            f"Version: {payload.get('version', 'unknown')}\n"
            f"Producer: {payload.get('producer_team_name', 'unknown')}",
            title="contract.published",
            border_style="blue",
        )
    )


def display_generic_event(event_type: str, payload: dict):
    """Display any other event type."""
    console.print(
        Panel.fit(
            f"[bold]{event_type.upper()}[/bold]\n\n"
            f"{json.dumps(payload, indent=2, default=str)[:500]}",
            title=event_type,
            border_style="yellow",
        )
    )


@app.post("/webhooks")
async def receive_webhook(request: Request):
    """Receive and process Tessera webhook events."""
    payload = await request.body()
    signature = request.headers.get("X-Tessera-Signature")

    # Verify signature
    if not verify_signature(payload, signature):
        console.print("[red]Invalid signature - rejecting webhook[/red]")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse event
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Store event
    received_events.append(
        {
            "received_at": datetime.now().isoformat(),
            "event": event,
        }
    )

    # Display event
    event_type = event.get("event", "unknown")
    event_payload = event.get("payload", {})

    console.print(
        f"\n[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Received: [bold]{event_type}[/bold]"
    )

    if event_type == "proposal.created":
        display_proposal_created(event_payload)
    elif event_type == "proposal.acknowledged":
        display_proposal_acknowledged(event_payload)
    elif event_type == "contract.published":
        display_contract_published(event_payload)
    else:
        display_generic_event(event_type, event_payload)

    return {"status": "ok", "event": event_type}


@app.get("/events")
async def list_events():
    """List all received events."""
    return {"events": received_events, "count": len(received_events)}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "events_received": len(received_events)}


def main():
    """Run the webhook receiver."""
    import uvicorn

    console.print(
        Panel.fit(
            "[bold]Tessera Webhook Receiver[/bold]\n\n"
            f"Listening on: http://0.0.0.0:5555\n"
            f"Webhook endpoint: http://localhost:5555/webhooks\n"
            f"Secret: {WEBHOOK_SECRET[:10]}...\n\n"
            "Configure Tessera with:\n"
            "  WEBHOOK_URL=http://host.docker.internal:5555/webhooks\n"
            "  WEBHOOK_SECRET=dev-webhook-secret",
            title="Starting",
            border_style="cyan",
        )
    )

    uvicorn.run(app, host="0.0.0.0", port=5555, log_level="warning")


if __name__ == "__main__":
    main()
