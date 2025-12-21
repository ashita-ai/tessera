"""
Webhook Integration Examples
============================

Demonstrates how to receive and verify Tessera webhook events.

Tessera sends webhooks for:
- contract.published: When a new contract is published
- proposal.created: When a breaking change proposal is created
- proposal.acknowledged: When a consumer acknowledges a proposal
- proposal.approved: When all consumers have acknowledged
- proposal.rejected: When a proposal is rejected
- proposal.superseded: When a proposal is replaced by a newer one

Configuration:
- Set WEBHOOK_URL in the Tessera server environment
- Optionally set WEBHOOK_SECRET for HMAC signature verification

Run the receiver: uv run python examples/webhooks_example.py
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any


def example_1_webhook_payload_structure():
    """
    EXAMPLE 1: Webhook Payload Structure
    ------------------------------------
    All webhooks follow the same structure with event-specific payloads.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Webhook Payload Structure")
    print("=" * 70)

    print("""
All Tessera webhooks have this structure:

    {
        "event": "contract.published",
        "timestamp": "2024-01-15T10:30:00Z",
        "payload": { ... event-specific data ... }
    }

Headers included with each webhook:

    X-Tessera-Event: contract.published
    X-Tessera-Timestamp: 2024-01-15T10:30:00Z
    X-Tessera-Signature: sha256=abc123...  (if WEBHOOK_SECRET is set)
    Content-Type: application/json

Event types:
    - contract.published    - New contract version published
    - proposal.created      - Breaking change detected, waiting for acknowledgment
    - proposal.acknowledged - Consumer acknowledged a proposal
    - proposal.approved     - All consumers acknowledged, ready to publish
    - proposal.rejected     - Proposal was rejected
    - proposal.superseded   - Proposal replaced by newer version
""")


def example_2_contract_published_event():
    """
    EXAMPLE 2: Contract Published Event
    -----------------------------------
    Sent when a new contract version is published.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Contract Published Event")
    print("=" * 70)

    payload = {
        "event": "contract.published",
        "timestamp": "2024-01-15T10:30:00Z",
        "payload": {
            "contract_id": "550e8400-e29b-41d4-a716-446655440000",
            "asset_id": "660e8400-e29b-41d4-a716-446655440001",
            "asset_fqn": "warehouse.analytics.dim_customers",
            "version": "2.0.0",
            "producer_team_id": "770e8400-e29b-41d4-a716-446655440002",
            "producer_team_name": "platform-team",
            "from_proposal_id": "880e8400-e29b-41d4-a716-446655440003",  # null if auto-published
        },
    }

    print(f"""
contract.published is sent when:
- A new asset's first contract is published
- A compatible change auto-publishes a new version
- A breaking change proposal is approved and published

Payload:
{json.dumps(payload, indent=4)}

Use cases:
- Trigger downstream CI/CD pipelines
- Update documentation
- Notify Slack/Teams channel
- Sync to data catalog
""")


def example_3_proposal_created_event():
    """
    EXAMPLE 3: Proposal Created Event
    ---------------------------------
    Sent when a breaking change is detected and requires acknowledgment.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Proposal Created Event")
    print("=" * 70)

    payload = {
        "event": "proposal.created",
        "timestamp": "2024-01-15T10:30:00Z",
        "payload": {
            "proposal_id": "880e8400-e29b-41d4-a716-446655440003",
            "asset_id": "660e8400-e29b-41d4-a716-446655440001",
            "asset_fqn": "warehouse.analytics.dim_customers",
            "producer_team_id": "770e8400-e29b-41d4-a716-446655440002",
            "producer_team_name": "platform-team",
            "proposed_version": "2.0.0",
            "breaking_changes": [
                {
                    "change_type": "field_removed",
                    "path": "properties.email",
                    "message": "Required field 'email' was removed",
                    "details": None,
                },
                {
                    "change_type": "type_changed",
                    "path": "properties.customer_id.type",
                    "message": "Type changed from 'integer' to 'string'",
                    "details": {"old_type": "integer", "new_type": "string"},
                },
            ],
            "impacted_consumers": [
                {
                    "team_id": "990e8400-e29b-41d4-a716-446655440004",
                    "team_name": "ml-team",
                    "pinned_version": "1.0.0",
                },
                {
                    "team_id": "aa0e8400-e29b-41d4-a716-446655440005",
                    "team_name": "reporting-team",
                    "pinned_version": None,  # Uses latest
                },
            ],
        },
    }

    print(f"""
proposal.created is sent when:
- A producer attempts to publish a breaking change
- There are registered consumers who need to acknowledge

Payload:
{json.dumps(payload, indent=4)}

Use cases:
- Create PagerDuty/OpsGenie alert for impacted teams
- Post to team Slack channels
- Create Jira tickets for migration work
- Block deployments until acknowledged
""")


def example_4_verify_signature():
    """
    EXAMPLE 4: Verify Webhook Signature
    -----------------------------------
    Verify that webhooks are authentic using HMAC-SHA256.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Verify Webhook Signature")
    print("=" * 70)

    print("""
When WEBHOOK_SECRET is set, Tessera signs payloads with HMAC-SHA256.
Always verify signatures in production!

```python
import hmac
import hashlib

def verify_tessera_webhook(
    payload: bytes,
    signature_header: str,
    secret: str
) -> bool:
    '''Verify Tessera webhook signature.'''
    if not signature_header.startswith("sha256="):
        return False

    expected_signature = signature_header[7:]  # Remove "sha256=" prefix
    computed_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, computed_signature)

# In your webhook handler:
@app.post("/webhooks/tessera")
async def handle_tessera_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("X-Tessera-Signature", "")

    if not verify_tessera_webhook(payload, signature, WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid signature")

    event = json.loads(payload)
    # Process the event...
```
""")

    # Demonstrate signature verification
    secret = "my-webhook-secret"
    payload = '{"event":"contract.published","timestamp":"2024-01-15T10:30:00Z"}'

    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    print(f"Example signature calculation:")
    print(f"  Secret: {secret}")
    print(f"  Payload: {payload}")
    print(f"  Signature: sha256={signature}")


def example_5_flask_receiver():
    """
    EXAMPLE 5: Flask Webhook Receiver
    ---------------------------------
    A minimal Flask app to receive Tessera webhooks.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Flask Webhook Receiver")
    print("=" * 70)

    print("""
A minimal Flask webhook receiver:

```python
# webhook_receiver.py
import hmac
import hashlib
import json
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
WEBHOOK_SECRET = os.environ.get("TESSERA_WEBHOOK_SECRET", "")

def verify_signature(payload: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET or not signature:
        return True  # Skip verification if no secret configured
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.post("/webhooks/tessera")
def handle_webhook():
    payload = request.get_data()
    signature = request.headers.get("X-Tessera-Signature", "")

    if not verify_signature(payload, signature):
        return jsonify({"error": "Invalid signature"}), 401

    event = json.loads(payload)
    event_type = event["event"]
    data = event["payload"]

    if event_type == "proposal.created":
        # Alert impacted teams
        for consumer in data["impacted_consumers"]:
            notify_team(consumer["team_name"], data)

    elif event_type == "contract.published":
        # Trigger downstream updates
        sync_to_catalog(data["asset_fqn"], data["version"])

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(port=5000)
```

Run with:
    TESSERA_WEBHOOK_SECRET=your-secret flask run --port 5000

Configure Tessera to send webhooks:
    WEBHOOK_URL=http://your-server:5000/webhooks/tessera
    WEBHOOK_SECRET=your-secret
""")


def example_6_fastapi_receiver():
    """
    EXAMPLE 6: FastAPI Webhook Receiver
    -----------------------------------
    An async FastAPI app to receive Tessera webhooks.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 6: FastAPI Webhook Receiver")
    print("=" * 70)

    print("""
An async FastAPI webhook receiver:

```python
# webhook_receiver.py
import hmac
import hashlib
import os
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Any

app = FastAPI()
WEBHOOK_SECRET = os.environ.get("TESSERA_WEBHOOK_SECRET", "")

class WebhookEvent(BaseModel):
    event: str
    timestamp: datetime
    payload: dict[str, Any]

def verify_signature(payload: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")

@app.post("/webhooks/tessera")
async def handle_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("X-Tessera-Signature", "")

    if not verify_signature(payload, signature):
        raise HTTPException(401, "Invalid signature")

    event = WebhookEvent.model_validate_json(payload)

    match event.event:
        case "proposal.created":
            await handle_proposal_created(event.payload)
        case "proposal.acknowledged":
            await handle_acknowledgment(event.payload)
        case "contract.published":
            await handle_contract_published(event.payload)
        case _:
            pass  # Ignore unknown events

    return {"status": "ok"}

async def handle_proposal_created(payload: dict):
    '''Handle breaking change proposal.'''
    print(f"Breaking change proposed for {payload['asset_fqn']}")
    for consumer in payload["impacted_consumers"]:
        print(f"  - Notify {consumer['team_name']}")
    # Send Slack notification, create ticket, etc.

async def handle_acknowledgment(payload: dict):
    '''Handle consumer acknowledgment.'''
    print(f"{payload['consumer_team_name']} acknowledged proposal")
    print(f"  Pending: {payload['pending_count']}")

async def handle_contract_published(payload: dict):
    '''Handle new contract version.'''
    print(f"Contract {payload['version']} published for {payload['asset_fqn']}")
    # Trigger CI/CD, update catalog, etc.

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
```

Run with:
    TESSERA_WEBHOOK_SECRET=your-secret uvicorn webhook_receiver:app --port 5000
""")


def example_7_configuration():
    """
    EXAMPLE 7: Webhook Configuration
    --------------------------------
    How to configure webhooks in Tessera.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 7: Webhook Configuration")
    print("=" * 70)

    print("""
Configure webhooks via environment variables:

For Docker Compose (docker-compose.yml):

    services:
      api:
        environment:
          WEBHOOK_URL: http://your-receiver:5000/webhooks/tessera
          WEBHOOK_SECRET: your-shared-secret-key

For local development (.env):

    WEBHOOK_URL=http://localhost:5000/webhooks/tessera
    WEBHOOK_SECRET=dev-webhook-secret

For production:

    # Use a strong random secret
    WEBHOOK_SECRET=$(openssl rand -base64 32)

    # Or from a secrets manager
    WEBHOOK_URL=${VAULT_WEBHOOK_URL}
    WEBHOOK_SECRET=${VAULT_WEBHOOK_SECRET}

Retry behavior:
- Tessera retries failed deliveries up to 3 times
- Retry delays: 1s, 5s, 30s
- Success = HTTP status code < 300
- Timeout: 30 seconds per request

Best practices:
1. Always verify signatures in production
2. Respond quickly (< 5s) - do heavy work async
3. Return 2xx immediately, process in background
4. Log webhook events for debugging
5. Handle duplicate deliveries (at-least-once)
""")


def main():
    """Run all webhook examples."""
    print("\n" + "=" * 70)
    print("  TESSERA WEBHOOK INTEGRATION EXAMPLES")
    print("=" * 70)

    example_1_webhook_payload_structure()
    example_2_contract_published_event()
    example_3_proposal_created_event()
    example_4_verify_signature()
    example_5_flask_receiver()
    example_6_fastapi_receiver()
    example_7_configuration()

    print("\n" + "=" * 70)
    print("To receive webhooks, configure Tessera with:")
    print("  WEBHOOK_URL=http://your-receiver/webhooks/tessera")
    print("  WEBHOOK_SECRET=your-secret")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
