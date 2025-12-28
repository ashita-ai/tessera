# Audit API

Query audit events for compliance and debugging.

## List Audit Events

```http
GET /api/v1/audit/events
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | string | Filter by event type |
| `entity_type` | string | Filter by entity type (asset, contract, team, etc.) |
| `entity_id` | uuid | Filter by entity ID |
| `actor_id` | uuid | Filter by actor (user or API key) |
| `start_date` | datetime | Events after this time |
| `end_date` | datetime | Events before this time |
| `limit` | int | Number of results (default: 50, max: 100) |
| `offset` | int | Pagination offset |

### Response

```json
{
  "results": [
    {
      "id": "event-uuid",
      "event_type": "contract.published",
      "entity_type": "contract",
      "entity_id": "contract-uuid",
      "actor_id": "user-uuid",
      "actor_type": "user",
      "timestamp": "2025-01-15T10:00:00Z",
      "metadata": {
        "version": "1.2.0",
        "asset_fqn": "warehouse.analytics.users"
      }
    }
  ],
  "total": 500
}
```

## Get Audit Event

```http
GET /api/v1/audit/events/{event_id}
```

### Response

```json
{
  "id": "event-uuid",
  "event_type": "contract.published",
  "entity_type": "contract",
  "entity_id": "contract-uuid",
  "actor_id": "user-uuid",
  "actor_type": "user",
  "timestamp": "2025-01-15T10:00:00Z",
  "metadata": {
    "version": "1.2.0",
    "asset_fqn": "warehouse.analytics.users",
    "changes": ["property_added: email"]
  },
  "request_id": "req-uuid"
}
```

## Get Entity History

```http
GET /api/v1/audit/entities/{entity_type}/{entity_id}/history
```

Get all audit events for a specific entity.

### Example

```bash
# Get all events for an asset
curl http://localhost:8000/api/v1/audit/entities/asset/asset-uuid/history
```

### Response

```json
{
  "results": [
    {
      "id": "event-uuid",
      "event_type": "asset.created",
      "timestamp": "2025-01-10T10:00:00Z",
      ...
    },
    {
      "id": "event-uuid-2",
      "event_type": "contract.published",
      "timestamp": "2025-01-15T10:00:00Z",
      ...
    }
  ]
}
```

## Event Types

### Asset Events

| Event | Description |
|-------|-------------|
| `asset.created` | New asset created |
| `asset.updated` | Asset metadata updated |
| `asset.deleted` | Asset deleted |
| `asset.restored` | Deleted asset restored |

### Contract Events

| Event | Description |
|-------|-------------|
| `contract.published` | New contract version published |
| `contract.deprecated` | Contract deprecated |
| `contract.archived` | Contract archived |

### Proposal Events

| Event | Description |
|-------|-------------|
| `proposal.created` | Breaking change proposal created |
| `proposal.acknowledged` | Consumer acknowledged proposal |
| `proposal.published` | Proposal published as contract |
| `proposal.withdrawn` | Proposal withdrawn |
| `proposal.force_published` | Proposal force-published |

### Registration Events

| Event | Description |
|-------|-------------|
| `registration.created` | Consumer registered |
| `registration.updated` | Registration updated |
| `registration.deleted` | Registration removed |

### Team/User Events

| Event | Description |
|-------|-------------|
| `team.created` | Team created |
| `team.updated` | Team updated |
| `team.deleted` | Team deleted |
| `user.created` | User created |
| `api_key.created` | API key created |
| `api_key.revoked` | API key revoked |
