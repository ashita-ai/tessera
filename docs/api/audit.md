# Audit API

Query audit events for compliance and debugging. All audit endpoints require both admin and read scope.

## List Audit Events

```http
GET /api/v1/audit/events
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_type` | string | Filter by entity type (asset, contract, team, etc.) |
| `entity_id` | uuid | Filter by entity ID |
| `action` | string | Filter by action (e.g. `contract.published`) |
| `actor_id` | uuid | Filter by actor (user or API key) |
| `actor_type` | string | Filter by actor type: `human` or `agent` |
| `from` | datetime | Events on or after this time |
| `to` | datetime | Events on or before this time |
| `limit` | int | Number of results (default: 50) |
| `offset` | int | Pagination offset |

### Response

```json
{
  "results": [
    {
      "id": "event-uuid",
      "entity_type": "contract",
      "entity_id": "contract-uuid",
      "action": "contract.published",
      "actor_id": "user-uuid",
      "actor_type": "human",
      "payload": {
        "version": "1.2.0",
        "asset_fqn": "warehouse.analytics.users"
      },
      "occurred_at": "2025-01-15T10:00:00Z"
    }
  ],
  "total": 500,
  "limit": 50,
  "offset": 0
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
  "entity_type": "contract",
  "entity_id": "contract-uuid",
  "action": "contract.published",
  "actor_id": "user-uuid",
  "actor_type": "human",
  "payload": {
    "version": "1.2.0",
    "asset_fqn": "warehouse.analytics.users",
    "changes": ["property_added: email"]
  },
  "occurred_at": "2025-01-15T10:00:00Z"
}
```

## Get Entity History

```http
GET /api/v1/audit/entities/{entity_type}/{entity_id}/history
```

Get all audit events for a specific entity. Supports `limit`/`offset` pagination.

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
      "entity_type": "asset",
      "entity_id": "asset-uuid",
      "action": "asset.created",
      "actor_id": "user-uuid",
      "actor_type": "human",
      "payload": {},
      "occurred_at": "2025-01-10T10:00:00Z"
    },
    {
      "id": "event-uuid-2",
      "entity_type": "asset",
      "entity_id": "asset-uuid",
      "action": "asset.updated",
      "actor_id": "user-uuid",
      "actor_type": "human",
      "payload": {},
      "occurred_at": "2025-01-15T10:00:00Z"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

## Action Types

### User Actions

| Action | Description |
|--------|-------------|
| `user.login` | User logged in |
| `user.logout` | User logged out |
| `user.created` | User created |
| `user.updated` | User updated |
| `user.deleted` | User deleted |
| `user.reactivated` | Deleted user reactivated |

### Team Actions

| Action | Description |
|--------|-------------|
| `team.created` | Team created |
| `team.updated` | Team updated |
| `team.deleted` | Team deleted |
| `team.restored` | Deleted team restored |

### Asset Actions

| Action | Description |
|--------|-------------|
| `asset.created` | New asset created |
| `asset.updated` | Asset metadata updated |
| `asset.deleted` | Asset deleted |
| `asset.restored` | Deleted asset restored |

### Contract Actions

| Action | Description |
|--------|-------------|
| `contract.published` | New contract version published |
| `contract.deprecated` | Contract deprecated |
| `contract.force_published` | Contract force-published (bypassed acknowledgment) |
| `contract.guarantees_updated` | Contract guarantees updated |

### Proposal Actions

| Action | Description |
|--------|-------------|
| `proposal.created` | Breaking change proposal created |
| `proposal.acknowledged` | Consumer acknowledged a proposal |
| `proposal.approved` | Proposal fully approved by all consumers |
| `proposal.rejected` | Proposal rejected |
| `proposal.published` | Proposal published as new contract |
| `proposal.withdrawn` | Proposal withdrawn by producer |
| `proposal.force_approved` | Proposal force-approved (bypassed acknowledgment) |
| `proposal.expired` | Proposal expired |
| `proposal.objection_filed` | Consumer filed an objection to a proposal |

### Registration Actions

| Action | Description |
|--------|-------------|
| `registration.created` | Consumer registered for a contract |
| `registration.updated` | Registration updated |
| `registration.deleted` | Registration removed |

### API Key Actions

| Action | Description |
|--------|-------------|
| `api_key.created` | API key created |
| `api_key.revoked` | API key revoked |
| `api_key.used` | API key used |

### Dependency Actions

| Action | Description |
|--------|-------------|
| `dependency.created` | Dependency created |
| `dependency.deleted` | Dependency deleted |

### Bulk Actions

| Action | Description |
|--------|-------------|
| `bulk.assets_reassigned` | Assets reassigned in bulk |
| `bulk.owner_assigned` | Owner assigned in bulk |

### Sync Actions

| Action | Description |
|--------|-------------|
| `repo.created` | Repository created |
| `repo.updated` | Repository updated |
| `repo.deleted` | Repository deleted |
| `repo.sync_triggered` | Repository sync triggered |
| `repo.synced` | Repository synced successfully |
| `repo.sync_failed` | Repository sync failed |
| `dbt.sync_upload` | dbt manifest uploaded for sync |

### Service Actions

| Action | Description |
|--------|-------------|
| `service.created` | Service created |
| `service.updated` | Service updated |
| `service.deleted` | Service deleted |

### Discovery Actions

| Action | Description |
|--------|-------------|
| `discovery.confirmed` | Discovery confirmed |
| `discovery.rejected` | Discovery rejected |
| `preflight.checked` | Preflight check performed |

### OTEL Actions

| Action | Description |
|--------|-------------|
| `otel_config.created` | OTEL config created |
| `otel_config.updated` | OTEL config updated |
| `otel_config.deleted` | OTEL config deleted |
| `otel_sync.completed` | OTEL sync completed |
| `otel_sync.failed` | OTEL sync failed |

### Slack Actions

| Action | Description |
|--------|-------------|
| `slack_config.created` | Slack config created |
| `slack_config.updated` | Slack config updated |
| `slack_config.deleted` | Slack config deleted |
| `slack_config.tested` | Slack config test sent |
