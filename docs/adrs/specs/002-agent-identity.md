# Spec 002: Agent Identity

**ADR**: 001-ai-enablement
**Priority**: 2
**Status**: Draft (partially superseded by PR #407)

## Supersession Note

PR #407 introduced `UserType` (HUMAN/BOT) and `user_id` on `APIKeyDB`. Bot users authenticate exclusively via API keys and are blocked from web login. This covers the core "machine identity" use case that this spec originally addressed. What remains from this spec:

- `agent_name` and `agent_framework` on APIKeyDB (not yet implemented — provides richer metadata than BOT user type alone)
- `actor_type` on AuditEventDB (not yet implemented — can be derived from the API key's user_type)
- Separate rate limit tiers for agent vs human keys (not yet implemented)

The bot user model is the foundation; this spec adds metadata and observability on top.

## Overview

Extend the API key model so that keys can represent AI agents. This gives full audit trail visibility into agent vs. human actions without introducing a separate agent entity model.

## Schema Changes

### APIKeyDB

Add two nullable columns:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `agent_name` | `String(255)` | `NULL` | Human-readable agent name (e.g., "dbt-codegen-agent", "analytics-copilot") |
| `agent_framework` | `String(100)` | `NULL` | Agent framework identifier (e.g., "claude-code", "cursor", "langchain", "custom") |

A key is considered an "agent key" when `agent_name IS NOT NULL`.

### AuditEventDB

Add one column:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `actor_type` | `String(20)` | `'human'` | `"human"` or `"agent"` |

Populated automatically from the API key used in the request.

### Migration

Alembic migration adding the three columns. All nullable, no data backfill needed. Existing keys remain human keys.

## API Changes

### Create API Key

`POST /api/v1/api-keys`

Add optional fields to request body:

```json
{
  "name": "analytics-copilot-prod",
  "team_id": "uuid",
  "scopes": ["READ", "WRITE"],
  "agent_name": "analytics-copilot",
  "agent_framework": "claude-code",
  "expires_at": "2026-06-12T00:00:00Z"
}
```

### List API Keys

`GET /api/v1/api-keys`

Add query parameter:
- `is_agent` (bool, optional): filter to agent keys only or human keys only

Response includes `agent_name` and `agent_framework` fields.

### Audit Events

`GET /api/v1/audit/events`

Add query parameter:
- `actor_type` (string, optional): filter by `"human"` or `"agent"`

Response includes `actor_type` field.

## Middleware Changes

In `auth.py`, after validating the API key, attach agent metadata to the request state:

```python
request.state.is_agent = api_key.agent_name is not None
request.state.agent_name = api_key.agent_name
request.state.agent_framework = api_key.agent_framework
```

The audit logging service reads these from request state when recording events.

## Rate Limiting

Agent keys get a separate rate limit tier. Default configuration:

| Tier | Requests/minute | Burst |
|------|-----------------|-------|
| Human | 60 | 120 |
| Agent | 300 | 600 |

Configurable via environment variables `RATE_LIMIT_HUMAN` and `RATE_LIMIT_AGENT`.

Rationale: agents make more frequent, smaller requests (check-before-write pattern). Throttling them at human rates would make the pre-flight check workflow impractical.

## Scoping (Future)

The ADR mentions per-asset and per-team scoping for agent keys. This spec does NOT implement that — it's deferred to a follow-up. The current team-scoped model is sufficient for the initial rollout.

If needed later, this would be:
- `allowed_asset_ids` (JSON array, nullable) on `APIKeyDB`
- Authorization middleware checks the request's target asset against the allowlist
- `NULL` means "all assets for this team" (current behavior)

## Testing

| Test case | Assertion |
|-----------|-----------|
| Create agent key | `agent_name` and `agent_framework` persisted |
| Create human key | `agent_name` is NULL |
| Audit event from agent key | `actor_type = "agent"` |
| Audit event from human key | `actor_type = "human"` |
| Filter audit events by actor_type | Only matching events returned |
| Filter API keys by is_agent | Only matching keys returned |
| Agent rate limit applied | Agent key gets higher rate limit |
| Human rate limit applied | Human key gets standard rate limit |
