# Consumer Registration

Consumer registration tracks which teams depend on which assets.

## Why Register?

When you register as a consumer:

1. You're notified of breaking changes before they happen
2. Your acknowledgment is required before changes go live
3. You have visibility into upcoming schema changes

## Registering as a Consumer

```bash
curl -X POST http://localhost:8000/api/v1/registrations \
  -H "Authorization: Bearer $CONSUMER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contract_id": "contract-uuid",
    "consumer_team_id": "your-team-uuid"
  }'
```

## Viewing Registrations

### For a Contract

```bash
curl http://localhost:8000/api/v1/contracts/{id}/registrations \
  -H "Authorization: Bearer $API_KEY"
```

### For Your Team

```bash
curl http://localhost:8000/api/v1/teams/{id}/registrations \
  -H "Authorization: Bearer $API_KEY"
```

## Registration Status

| Status | Description |
|--------|-------------|
| `active` | Registration is active |
| `inactive` | Registration was deactivated |

## Automatic Registration (Coming Soon)

Tessera can automatically register consumers based on:

- dbt `ref()` dependencies
- Query logs from your warehouse
- Lineage metadata

See [Issue #125](https://github.com/ashita-ai/tessera/issues/125) for progress.

## Unregistering

To stop receiving notifications:

```bash
curl -X DELETE http://localhost:8000/api/v1/registrations/{id} \
  -H "Authorization: Bearer $API_KEY"
```

## Impact Analysis

Before making changes, check who will be affected:

```bash
curl -X POST http://localhost:8000/api/v1/assets/{id}/impact \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "proposed_schema": { ... }
  }'
```

Response:

```json
{
  "breaking_changes": [...],
  "affected_consumers": [
    {
      "team_id": "team-uuid",
      "team_name": "Analytics",
      "registration_date": "2025-01-15"
    }
  ],
  "total_affected": 3
}
```
