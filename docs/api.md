# API Reference

Base URL: `/api/v1`

Interactive docs available at `/docs` (Swagger) and `/redoc` (ReDoc).

## Authentication

All endpoints require an API key via `X-API-Key` header.

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/v1/teams
```

Scopes: `read`, `write`, `admin`

---

## Teams

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/teams` | Create team | write |
| GET | `/teams` | List teams | read |
| GET | `/teams/{id}` | Get team | read |
| PATCH | `/teams/{id}` | Update team | write |
| DELETE | `/teams/{id}` | Soft delete team | write |
| POST | `/teams/{id}/restore` | Restore deleted team | write |

### Create Team

```bash
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"name": "Analytics", "metadata": {"slack": "#analytics"}}'
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Analytics",
  "slug": "analytics",
  "metadata": {"slack": "#analytics"},
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

## Assets

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/assets` | Create asset | write |
| GET | `/assets` | List assets | read |
| GET | `/assets/search` | Search by FQN | read |
| GET | `/assets/{id}` | Get asset | read |
| PATCH | `/assets/{id}` | Update asset | write |
| DELETE | `/assets/{id}` | Soft delete asset | write |
| POST | `/assets/{id}/restore` | Restore deleted asset | write |

### Create Asset

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "fqn": "warehouse.analytics.users",
    "owner_team_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "fqn": "warehouse.analytics.users",
  "owner_team_id": "550e8400-e29b-41d4-a716-446655440000",
  "current_contract_id": null,
  "metadata": {},
  "created_at": "2024-01-15T10:35:00Z"
}
```

### Asset Contracts

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/assets/{id}/contracts` | Publish contract | write |
| GET | `/assets/{id}/contracts` | List contracts | read |
| GET | `/assets/{id}/contracts/history` | Version history | read |
| GET | `/assets/{id}/contracts/diff` | Compare versions | read |
| POST | `/assets/{id}/impact` | Impact analysis | read |

### Publish Contract

```bash
curl -X POST http://localhost:8000/api/v1/assets/{asset_id}/contracts \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "version": "1.0.0",
    "schema": {
      "type": "object",
      "properties": {
        "id": {"type": "integer"},
        "email": {"type": "string"}
      },
      "required": ["id", "email"]
    },
    "compatibility_mode": "backward"
  }'
```

**Response (success):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "asset_id": "660e8400-e29b-41d4-a716-446655440001",
  "version": "1.0.0",
  "schema": {"type": "object", "...": "..."},
  "compatibility_mode": "backward",
  "status": "active",
  "created_at": "2024-01-15T10:40:00Z"
}
```

**Response (breaking change - creates proposal):**
```json
{
  "proposal": {
    "id": "880e8400-e29b-41d4-a716-446655440003",
    "status": "pending",
    "breaking_changes": [
      {"path": "$.properties.email", "change": "removed", "severity": "breaking"}
    ],
    "affected_consumers": ["consumer-team-id"]
  }
}
```

### Asset Dependencies

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/assets/{id}/dependencies` | Add dependency | write |
| GET | `/assets/{id}/dependencies` | List dependencies | read |
| DELETE | `/assets/{id}/dependencies/{dep_id}` | Remove dependency | write |
| GET | `/assets/{id}/lineage` | Get lineage graph | read |

---

## Contracts

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/contracts` | List all contracts | read |
| POST | `/contracts/compare` | Compare two contracts | read |
| GET | `/contracts/{id}` | Get contract by ID | read |
| GET | `/contracts/{id}/registrations` | List contract registrations | read |

### Compare Contracts

```bash
curl -X POST http://localhost:8000/api/v1/contracts/compare \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "old_contract_id": "contract-id-1",
    "new_contract_id": "contract-id-2"
  }'
```

```json
{
  "compatible": false,
  "changes": [
    {"path": "$.properties.status", "change": "type_changed", "old": "string", "new": "integer"}
  ]
}
```

---

## Registrations

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/registrations` | Register as consumer | write |
| GET | `/registrations` | List registrations | read |
| GET | `/registrations/{id}` | Get registration | read |
| PATCH | `/registrations/{id}` | Update registration | write |
| DELETE | `/registrations/{id}` | Unregister | write |

### Register as Consumer

```bash
curl -X POST http://localhost:8000/api/v1/registrations \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "asset_id": "660e8400-e29b-41d4-a716-446655440001",
    "consumer_team_id": "990e8400-e29b-41d4-a716-446655440004"
  }'
```

```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440005",
  "asset_id": "660e8400-e29b-41d4-a716-446655440001",
  "consumer_team_id": "990e8400-e29b-41d4-a716-446655440004",
  "pinned_version": null,
  "created_at": "2024-01-15T11:00:00Z"
}
```

---

## Proposals

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/proposals` | List proposals | read |
| GET | `/proposals/{id}` | Get proposal | read |
| GET | `/proposals/{id}/status` | Acknowledgment status | read |
| POST | `/proposals/{id}/acknowledge` | Submit acknowledgment | write |
| POST | `/proposals/{id}/withdraw` | Withdraw proposal | write |
| POST | `/proposals/{id}/force` | Force approve | admin |
| POST | `/proposals/{id}/publish` | Publish approved proposal | write |

### Acknowledge Proposal

```bash
curl -X POST http://localhost:8000/api/v1/proposals/{proposal_id}/acknowledge \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "consumer_team_id": "990e8400-e29b-41d4-a716-446655440004",
    "response": "approved",
    "notes": "We have migrated to the new schema"
  }'
```

```json
{
  "id": "bb0e8400-e29b-41d4-a716-446655440006",
  "proposal_id": "880e8400-e29b-41d4-a716-446655440003",
  "consumer_team_id": "990e8400-e29b-41d4-a716-446655440004",
  "response": "approved",
  "notes": "We have migrated to the new schema",
  "acknowledged_at": "2024-01-15T12:00:00Z"
}
```

### Proposal Status

```bash
curl http://localhost:8000/api/v1/proposals/{proposal_id}/status \
  -H "X-API-Key: your-key"
```

```json
{
  "proposal_id": "880e8400-e29b-41d4-a716-446655440003",
  "status": "pending",
  "total_consumers": 2,
  "acknowledged": 1,
  "pending": 1,
  "acknowledgments": [
    {"team_id": "team-1", "response": "approved"},
    {"team_id": "team-2", "response": null}
  ]
}
```

---

## Sync

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/sync/push` | Push schema state | write |
| POST | `/sync/pull` | Pull registered contracts | read |
| POST | `/sync/dbt` | Sync from dbt manifest | write |
| POST | `/sync/dbt/impact` | Analyze dbt manifest changes | read |

---

## Schemas

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/schemas/validate` | Validate JSON Schema | read |

---

## API Keys (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/api-keys` | Create API key | admin |
| GET | `/api-keys` | List API keys | admin |
| GET | `/api-keys/{id}` | Get API key | admin |
| DELETE | `/api-keys/{id}` | Revoke API key | admin |

---

## Webhooks (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/webhooks/deliveries` | List deliveries | admin |
| GET | `/webhooks/deliveries/{id}` | Get delivery | admin |

---

## Audit (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/audit/events` | Query audit events | admin |
| GET | `/audit/events/{id}` | Get audit event | admin |
| GET | `/audit/entities/{type}/{id}/history` | Entity history | admin |

---

## Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Basic health check | None |
| GET | `/health/ready` | Readiness (DB check) | None |
| GET | `/health/live` | Liveness probe | None |

---

## Error Responses

All errors return:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Asset with ID 'xxx' not found",
    "details": {}
  },
  "request_id": "req-uuid"
}
```

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Invalid request body |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Resource already exists |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
