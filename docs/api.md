# API Reference

Base URL: `/api/v1`

Interactive docs available at `/docs` (Swagger) and `/redoc` (ReDoc).

## Authentication

All endpoints require an API key via `X-API-Key` header.

Scopes: `read`, `write`, `admin`

## Teams

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/teams` | Create team | write |
| GET | `/teams` | List teams | read |
| GET | `/teams/{id}` | Get team | read |
| PATCH | `/teams/{id}` | Update team | write |
| DELETE | `/teams/{id}` | Soft delete team | write |
| POST | `/teams/{id}/restore` | Restore deleted team | write |

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

### Contracts

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/assets/{id}/contracts` | Publish contract | write |
| GET | `/assets/{id}/contracts` | List contracts | read |
| GET | `/assets/{id}/contracts/history` | Version history | read |
| GET | `/assets/{id}/contracts/diff` | Compare versions | read |
| POST | `/assets/{id}/impact` | Impact analysis | read |

### Dependencies

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/assets/{id}/dependencies` | Add dependency | write |
| GET | `/assets/{id}/dependencies` | List dependencies | read |
| DELETE | `/assets/{id}/dependencies/{dep_id}` | Remove dependency | write |
| GET | `/assets/{id}/lineage` | Get lineage graph | read |

## Registrations

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/registrations` | Register as consumer | write |
| GET | `/registrations` | List registrations | read |
| GET | `/registrations/{id}` | Get registration | read |
| PATCH | `/registrations/{id}` | Update registration | write |
| DELETE | `/registrations/{id}` | Unregister | write |

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

## Sync

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/sync/push` | Push schema state | write |
| POST | `/sync/pull` | Pull registered contracts | read |
| POST | `/sync/dbt` | Sync from dbt manifest | write |
| POST | `/sync/dbt/impact` | Analyze dbt manifest changes | read |

## Schemas

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/schemas/validate` | Validate JSON Schema | read |

## API Keys (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| POST | `/api-keys` | Create API key | admin |
| GET | `/api-keys` | List API keys | admin |
| GET | `/api-keys/{id}` | Get API key | admin |
| DELETE | `/api-keys/{id}` | Revoke API key | admin |

## Webhooks (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/webhooks/deliveries` | List deliveries | admin |
| GET | `/webhooks/deliveries/{id}` | Get delivery | admin |

## Audit (Admin)

| Method | Endpoint | Description | Scope |
|--------|----------|-------------|-------|
| GET | `/audit/events` | Query audit events | admin |
| GET | `/audit/events/{id}` | Get audit event | admin |
| GET | `/audit/entities/{type}/{id}/history` | Entity history | admin |

## Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Basic health check | None |
| GET | `/health/ready` | Readiness (DB check) | None |
| GET | `/health/live` | Liveness probe | None |

## Error Responses

All errors return:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {}
  },
  "request_id": "uuid"
}
```

Common codes: `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `UNAUTHORIZED`, `FORBIDDEN`, `RATE_LIMIT_EXCEEDED`
