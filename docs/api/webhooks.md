# Webhooks

Tessera sends webhooks for key events like proposal creation and contract publishing.

## Configuration

Configure webhooks via environment variables:

```bash
WEBHOOK_URL=https://your-service.com/webhooks/tessera
WEBHOOK_SECRET=your-hmac-signing-secret
```

## Webhook Events

| Event | Description |
|-------|-------------|
| `proposal.created` | Breaking change proposal created |
| `proposal.acknowledged` | Consumer acknowledged a proposal |
| `proposal.approved` | All consumers acknowledged |
| `proposal.published` | Proposal published as new contract |
| `contract.published` | New contract version published |

## Payload Format

All webhooks have a consistent format:

```json
{
  "event": "proposal.created",
  "timestamp": "2025-01-15T10:00:00Z",
  "payload": {
    "proposal_id": "uuid",
    "asset_id": "uuid",
    "asset_fqn": "warehouse.analytics.users",
    ...
  }
}
```

## Signature Verification

When `WEBHOOK_SECRET` is configured, webhooks include an HMAC-SHA256 signature:

```
X-Tessera-Signature: sha256=abc123...
X-Tessera-Event: proposal.created
X-Tessera-Timestamp: 2025-01-15T10:00:00Z
```

Verify the signature:

```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

## Delivery Tracking

### List Deliveries

```http
GET /api/v1/webhooks/deliveries
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: `pending`, `delivered`, `failed` |
| `event_type` | string | Filter by event type |
| `limit` | int | Number of results (default: 50) |

### Response

```json
{
  "results": [
    {
      "id": "delivery-uuid",
      "event_type": "proposal.created",
      "status": "delivered",
      "url": "https://your-service.com/webhooks",
      "attempts": 1,
      "created_at": "2025-01-15T10:00:00Z",
      "delivered_at": "2025-01-15T10:00:01Z"
    }
  ],
  "total": 100
}
```

### Get Delivery Details

```http
GET /api/v1/webhooks/deliveries/{delivery_id}
```

### Response

```json
{
  "id": "delivery-uuid",
  "event_type": "proposal.created",
  "status": "delivered",
  "url": "https://your-service.com/webhooks",
  "payload": { ... },
  "attempts": 1,
  "last_attempt_at": "2025-01-15T10:00:01Z",
  "last_status_code": 200,
  "last_error": null,
  "created_at": "2025-01-15T10:00:00Z",
  "delivered_at": "2025-01-15T10:00:01Z"
}
```

## Retry Behavior

Failed deliveries are retried with exponential backoff:

- Attempt 1: Immediate
- Attempt 2: After 1 second
- Attempt 3: After 5 seconds
- Attempt 4: After 30 seconds

After 4 attempts, the delivery is marked as `failed`.

## Security

Tessera implements several security measures for webhooks:

### SSRF Protection

Webhook URLs are validated to prevent Server-Side Request Forgery:

- Private IPs are blocked (10.x, 172.16-31.x, 192.168.x)
- Loopback addresses are blocked (127.x)
- Cloud metadata endpoints are blocked (169.254.x)
- HTTPS is required in production

### Backpressure

Concurrent webhook deliveries are limited to prevent resource exhaustion.
