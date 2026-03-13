# Spec 001: New REST Endpoints

**ADR**: 001-ai-enablement
**Priority**: 1 (implement first)
**Status**: Draft

## Overview

Three new REST endpoints that serve both agents (via MCP sidecar) and existing SDK/UI consumers. These fill gaps in the current API that become critical for agent workflows.

---

## Endpoint 1: Impact Preview

```
POST /api/v1/assets/{asset_id}/impact-preview
```

### Request

```json
{
  "proposed_schema": {
    "type": "object",
    "properties": {
      "customer_id": { "type": "string" },
      "lifetime_value": { "type": "number" }
    },
    "required": ["customer_id", "lifetime_value"]
  },
  "proposed_guarantees": {
    "freshness": { "max_stale_hours": 24 },
    "not_null": ["customer_id"]
  },
  "compatibility_mode_override": "backward"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `proposed_schema` | object | yes | The new schema to evaluate |
| `proposed_guarantees` | object | no | New guarantees (compared against current if provided) |
| `compatibility_mode_override` | string | no | Override the asset's default compatibility mode for this check |

### Response (200 OK)

```json
{
  "is_breaking": true,
  "change_type": "MAJOR",
  "compatibility_mode": "backward",
  "current_version": "2.1.0",
  "suggested_version": "3.0.0",
  "breaking_changes": [
    {
      "kind": "PROPERTY_REMOVED",
      "path": "$.properties.user_id",
      "message": "Required property 'user_id' was removed",
      "old_value": { "type": "integer" },
      "new_value": null
    }
  ],
  "non_breaking_changes": [
    {
      "kind": "PROPERTY_ADDED",
      "path": "$.properties.customer_id",
      "message": "New required property 'customer_id' was added"
    }
  ],
  "guarantee_changes": [
    {
      "field": "freshness.max_stale_hours",
      "old_value": 12,
      "new_value": 24,
      "severity": "EXPANDED",
      "message": "Freshness guarantee relaxed from 12h to 24h"
    }
  ],
  "affected_consumers": [
    {
      "registration_id": "uuid",
      "consumer_team_id": "uuid",
      "consumer_team_name": "analytics",
      "contract_id": "uuid",
      "pinned_version": null,
      "status": "ACTIVE"
    }
  ],
  "affected_downstream": [
    {
      "asset_id": "uuid",
      "asset_fqn": "prod.reporting.daily_users",
      "owner_team_name": "reporting",
      "dependency_type": "CONSUMES",
      "depth": 1
    },
    {
      "asset_id": "uuid",
      "asset_fqn": "prod.executive.weekly_summary",
      "owner_team_name": "executive",
      "dependency_type": "TRANSFORMS",
      "depth": 2
    }
  ],
  "migration_suggestions": [
    {
      "strategy": "additive",
      "description": "Add 'customer_id' as optional, keep 'user_id', deprecate in next minor version",
      "confidence": "high",
      "suggested_schema": { "..." : "..." }
    }
  ],
  "would_create_proposal": true,
  "proposal_would_notify": ["analytics", "reporting"]
}
```

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Asset not found or deleted |
| 404 | Asset has no published contracts (nothing to compare against) |
| 422 | `proposed_schema` fails JSON Schema / Avro validation |
| 422 | Unknown `compatibility_mode_override` value |

## Implementation

### Service Layer

New function in `services/impact_preview.py`:

```python
async def preview_impact(
    session: AsyncSession,
    asset_id: UUID,
    proposed_schema: dict,
    proposed_guarantees: dict | None = None,
    compatibility_mode_override: CompatibilityMode | None = None,
) -> ImpactPreviewResult:
```

Steps:
1. Load asset + current active contract (404 if missing)
2. Validate proposed schema (`schema_validator.validate_json_schema` or `avro.validate_avro_schema`)
3. Diff schemas (`schema_diff.diff_schemas`)
4. Diff guarantees (if provided)
5. Classify change type (PATCH/MINOR/MAJOR) using compatibility mode
6. Load registrations for the current contract
7. Run lineage traversal (`affected_parties.get_affected_parties`)
8. Generate migration suggestions (`migration_suggester.suggest_migrations`) if breaking
9. Compute version suggestion (`versioning.compute_version_suggestion`)
10. Return composed result

### Authorization

- Requires READ scope (this is a read-only operation)
- No team restriction — any authenticated caller can preview impact on any asset

### Performance

Steps 6 and 7 (registrations + lineage) can run concurrently with `asyncio.gather`. The schema diff (step 3) is fast and runs first since steps 8-9 depend on its result.

Target latency: <200ms for assets with <100 downstream dependencies. Lineage traversal is the bottleneck for deeply connected graphs — consider a `max_depth` parameter (default 5) if this becomes an issue.

### Testing

| Test case | Assertion |
|-----------|-----------|
| Non-breaking change | `is_breaking=false`, `change_type=MINOR`, empty `breaking_changes` |
| Breaking change, no consumers | `is_breaking=true`, empty `affected_consumers`, `would_create_proposal=false` |
| Breaking change, with consumers | `is_breaking=true`, populated `affected_consumers`, `would_create_proposal=true` |
| Breaking change, with lineage | `affected_downstream` includes transitive dependencies |
| Guarantee relaxation | `guarantee_changes` populated with severity=EXPANDED |
| No current contract | 404 |
| Invalid schema | 422 |
| Compatibility mode override | Uses override instead of asset default |
| Migration suggestions present | `migration_suggestions` non-empty for known breaking change patterns |

---

## Endpoint 2: Pending Proposals for Team

```
GET /api/v1/proposals/pending/{team_id}
```

### Overview

Returns proposals that are waiting for a specific team's acknowledgment. This is the "inbox" for consumer agents and the critical missing piece for the consumer side of the coordination workflow.

Today, discovering pending proposals for a team requires: (1) list all pending proposals, (2) for each, check if this team is an affected consumer, (3) check if this team has already acknowledged. This endpoint composes those steps into a single query.

### Request

Path parameter:
- `team_id` (UUID, required) — the team to check

Query parameters:
- `status` (string, optional, default `PENDING`) — proposal status filter
- `limit` (int, optional, default 20) — pagination
- `offset` (int, optional, default 0) — pagination

### Response (200 OK)

```json
{
  "pending_proposals": [
    {
      "proposal_id": "uuid",
      "asset_id": "uuid",
      "asset_fqn": "prod.core.dim_customers",
      "proposed_by_team": "core-data",
      "proposed_at": "2026-03-10T14:00:00Z",
      "expires_at": "2026-03-17T14:00:00Z",
      "breaking_changes_summary": [
        "Removed property 'user_id'",
        "Added required property 'customer_id'"
      ],
      "total_consumers": 4,
      "acknowledged_count": 2,
      "your_team_status": "AWAITING_RESPONSE"
    }
  ],
  "total": 3
}
```

`your_team_status` values:
- `AWAITING_RESPONSE` — team hasn't acknowledged yet
- `APPROVED` / `BLOCKED` / `MIGRATING` — team's response (included for completeness when `status` filter is broader)

### Implementation

New function in `services/proposals.py` (or extend existing proposal query logic):

```python
async def get_pending_proposals_for_team(
    session: AsyncSession,
    team_id: UUID,
    status: ProposalStatus = ProposalStatus.PENDING,
    limit: int = 20,
    offset: int = 0,
) -> PendingProposalsResult:
```

Query approach:
1. Find all proposals with the given status
2. Join with registrations to find proposals where this team has an active registration on the proposal's asset
3. Left join with acknowledgments to determine if the team has already responded
4. Filter to proposals where the team's acknowledgment is missing (for the default `AWAITING_RESPONSE` case)

This should be a single SQL query with joins, not N+1 queries in the sidecar.

### Authorization

- Requires READ scope
- Team-scoped: the API key's team must match `team_id`, or the key must have ADMIN scope

### Testing

| Test case | Assertion |
|-----------|-----------|
| Team with pending proposals | Returns proposals awaiting this team's ack |
| Team with no pending proposals | Returns empty list |
| Team already acknowledged all | Returns empty list (for AWAITING_RESPONSE filter) |
| Proposal expired | Not included in results |
| Pagination | Correct limit/offset behavior |
| Wrong team (non-admin) | 403 |

---

## Endpoint 3: Asset Context

```
GET /api/v1/assets/{asset_id}/context
```

### Overview

Returns everything an agent needs to understand an asset in a single call: current contract, schema with semantic annotations, consumers, upstream/downstream lineage, recent audit results, and active proposals. Eliminates the need to call 5+ endpoints to build a complete picture.

### Request

Path parameter:
- `asset_id` (UUID, required)

Query parameter:
- `asset_fqn` (string, optional) — alternative to path parameter, resolved via search. Use as `GET /api/v1/assets/context?fqn=prod.analytics.dim_customers`

### Response (200 OK)

```json
{
  "asset": {
    "id": "uuid",
    "fqn": "prod.analytics.dim_customers",
    "description": "Customer dimension table with demographics and LTV metrics",
    "tags": ["pii", "financial"],
    "resource_type": "MODEL",
    "environment": "production",
    "owner_team_id": "uuid",
    "owner_team_name": "analytics",
    "owner_user_name": "jane.doe",
    "compatibility_mode": "backward",
    "semver_mode": "AUTO"
  },
  "current_contract": {
    "id": "uuid",
    "version": "2.1.0",
    "schema_def": { },
    "schema_format": "JSON_SCHEMA",
    "field_descriptions": {
      "$.properties.customer_id": "Unique identifier, matches CRM system ID"
    },
    "field_tags": {
      "$.properties.customer_id": ["pii", "join-key"]
    },
    "guarantees": {
      "freshness": { "max_stale_hours": 12 },
      "not_null": ["customer_id", "created_at"],
      "unique": ["customer_id"]
    },
    "status": "ACTIVE",
    "published_at": "2026-03-01T00:00:00Z"
  },
  "consumers": [
    {
      "registration_id": "uuid",
      "consumer_team_id": "uuid",
      "consumer_team_name": "reporting",
      "pinned_version": null,
      "status": "ACTIVE"
    }
  ],
  "upstream_dependencies": [
    {
      "asset_id": "uuid",
      "asset_fqn": "prod.raw.crm_customers",
      "dependency_type": "CONSUMES",
      "owner_team_name": "ingestion"
    }
  ],
  "downstream_dependents": [
    {
      "asset_id": "uuid",
      "asset_fqn": "prod.reporting.daily_users",
      "dependency_type": "TRANSFORMS",
      "depth": 1,
      "owner_team_name": "reporting"
    }
  ],
  "active_proposals": [
    {
      "proposal_id": "uuid",
      "status": "PENDING",
      "proposed_at": "2026-03-10T14:00:00Z",
      "breaking_changes_count": 2,
      "acknowledged_count": 1,
      "total_consumers": 3
    }
  ],
  "recent_audits": [
    {
      "audit_id": "uuid",
      "status": "PASSED",
      "guarantees_checked": 5,
      "guarantees_passed": 5,
      "guarantees_failed": 0,
      "triggered_by": "dbt_test",
      "run_at": "2026-03-11T12:00:00Z"
    }
  ],
  "contract_history_count": 7
}
```

### Implementation

New function in `services/asset_context.py`:

```python
async def get_asset_context(
    session: AsyncSession,
    asset_id: UUID,
) -> AssetContextResult:
```

Steps (parallelized where possible):
1. Load asset (404 if missing)
2. In parallel via `asyncio.gather`:
   - Load current active contract
   - Load registrations (consumers)
   - Load upstream dependencies
   - Load downstream dependents (reuse `affected_parties` with depth=1)
   - Load active proposals for this asset
   - Load recent audit runs (last 5)
3. Compose result

### Authorization

- Requires READ scope
- No team restriction — any authenticated caller can view any asset's context

### Testing

| Test case | Assertion |
|-----------|-----------|
| Asset with full data | All sections populated |
| Asset with no contract | `current_contract` is null |
| Asset with no consumers | `consumers` is empty list |
| Asset with no lineage | Both dependency lists empty |
| Asset with active proposal | `active_proposals` populated |
| FQN lookup | Resolves FQN to asset ID |
| Deleted asset | 404 |
