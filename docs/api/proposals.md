# Proposals API

Manage breaking change proposals in Tessera.

## List Proposals

```http
GET /api/v1/proposals
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `asset_id` | uuid | Filter by asset |
| `status` | string | Filter by status (pending, approved, published, rejected, withdrawn, expired) |
| `change_type` | string | Filter by change type |
| `proposed_by` | uuid | Filter by proposer team ID |
| `consumer_team_id` | uuid | Filter by consumer team (returns proposals affecting contracts where this team is registered) |
| `pending_ack_for` | uuid | Filter to pending proposals needing acknowledgment from this team |
| `limit` | int | Results per page (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "results": [
    {
      "id": "proposal-uuid",
      "asset_id": "asset-uuid",
      "asset_fqn": "warehouse.analytics.users",
      "status": "pending",
      "change_type": "major",
      "breaking_changes_count": 2,
      "proposed_by": "team-uuid",
      "proposed_at": "2025-01-15T10:00:00Z",
      "acknowledgment_count": 1,
      "total_consumers": 3
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## Get Pending Proposals for Team

```http
GET /api/v1/proposals/pending/{team_id}
```

Returns proposals awaiting acknowledgment from a specific team. Excludes expired proposals and proposals already acknowledged by the team. Team-scoped: the API key's team must match `team_id`, or the key must have admin scope.

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Proposal status to filter by (default: pending) |
| `limit` | int | Results per page (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Response

```json
{
  "pending_proposals": [
    {
      "proposal_id": "proposal-uuid",
      "asset_id": "asset-uuid",
      "asset_fqn": "warehouse.analytics.users",
      "proposed_by_team": "data-platform",
      "proposed_at": "2025-01-15T10:00:00Z",
      "expires_at": "2025-02-15T10:00:00Z",
      "breaking_changes_summary": ["property_removed: email"],
      "total_consumers": 3,
      "acknowledged_count": 1,
      "your_team_status": "AWAITING_RESPONSE"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## Get Proposal

```http
GET /api/v1/proposals/{proposal_id}
```

Returns the full Proposal object.

### Response

```json
{
  "id": "proposal-uuid",
  "asset_id": "asset-uuid",
  "proposed_schema": {},
  "change_type": "major",
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "$.properties.email",
      "message": "Property 'email' was removed"
    }
  ],
  "status": "pending",
  "proposed_by": "team-uuid",
  "proposed_by_user_id": null,
  "proposed_at": "2025-01-15T10:00:00Z",
  "resolved_at": null,
  "expires_at": "2025-02-15T10:00:00Z",
  "auto_expire": false
}
```

## Get Proposal Status

```http
GET /api/v1/proposals/{proposal_id}/status
```

Detailed status of a proposal including acknowledgment progress.

### Response

```json
{
  "proposal_id": "proposal-uuid",
  "status": "pending",
  "asset_fqn": "warehouse.analytics.users",
  "change_type": "major",
  "breaking_changes": [],
  "proposed_by": {
    "team_id": "team-uuid",
    "team_name": "data-platform",
    "user_id": null,
    "user_name": null
  },
  "proposed_at": "2025-01-15T10:00:00Z",
  "resolved_at": null,
  "consumers": {
    "total": 3,
    "acknowledged": 2,
    "pending": 1,
    "blocked": 0
  },
  "acknowledgments": [
    {
      "consumer_team_id": "team-uuid",
      "consumer_team_name": "Analytics",
      "acknowledged_by_user_id": "user-uuid",
      "acknowledged_by_user_name": "Jane Doe",
      "response": "approved",
      "responded_at": "2025-01-16T10:00:00Z",
      "notes": "Updated our dashboards"
    }
  ],
  "pending_consumers": [
    {
      "team_id": "team-uuid-2",
      "team_name": "Finance",
      "registered_at": "2025-01-10T10:00:00Z"
    }
  ],
  "audit_status": null,
  "warnings": []
}
```

## Acknowledge Proposal

```http
POST /api/v1/proposals/{proposal_id}/acknowledge
```

Acknowledge a proposal as a consumer team. The API key's team must match `consumer_team_id`, or the key must have admin scope.

If the response is `blocked`, the proposal is rejected. If all registered consumers acknowledge (none blocked), the proposal is auto-approved.

### Request Body

```json
{
  "consumer_team_id": "team-uuid",
  "acknowledged_by_user_id": "user-uuid",
  "response": "approved",
  "migration_deadline": "2025-03-01T00:00:00Z",
  "notes": "We've updated our dashboards to handle this change"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `consumer_team_id` | uuid | yes | Team acknowledging the proposal |
| `acknowledged_by_user_id` | uuid | no | User performing the acknowledgment |
| `response` | string | yes | One of: `approved`, `blocked`, `migrating` |
| `migration_deadline` | datetime | no | Deadline for completing migration |
| `notes` | string | no | Free-text notes (max 2000 chars) |

### Response (201)

Returns the created Acknowledgment object.

```json
{
  "id": "ack-uuid",
  "proposal_id": "proposal-uuid",
  "consumer_team_id": "team-uuid",
  "acknowledged_by_user_id": "user-uuid",
  "response": "approved",
  "migration_deadline": "2025-03-01T00:00:00Z",
  "notes": "We've updated our dashboards to handle this change",
  "responded_at": "2025-01-16T10:00:00Z"
}
```

## File Objection

```http
POST /api/v1/proposals/{proposal_id}/object
```

File a non-blocking objection to a proposal. Objections don't prevent approval but are visible to all parties. Only teams listed in the proposal's `affected_teams` can file objections.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `objector_team_id` | uuid | yes | Team ID filing the objection |
| `objector_user_id` | uuid | no | User ID filing the objection |

### Request Body

```json
{
  "reason": "This change will break our nightly ETL pipeline"
}
```

### Response (201)

```json
{
  "action": "objection_filed",
  "proposal_id": "proposal-uuid",
  "asset_fqn": "warehouse.analytics.users",
  "objection": {
    "team_id": "team-uuid",
    "team_name": "Analytics",
    "reason": "This change will break our nightly ETL pipeline",
    "objected_at": "2025-01-16T10:00:00Z",
    "objected_by_user_id": "user-uuid",
    "objected_by_user_name": "Jane Doe"
  },
  "total_objections": 1,
  "note": "Objections are non-blocking. The proposal can still be approved, but objections are visible to all parties to facilitate coordination."
}
```

## Force Approve

```http
POST /api/v1/proposals/{proposal_id}/force
```

Force-approve a proposal, bypassing consumer acknowledgments. Requires admin scope.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `actor_id` | uuid | yes | Team ID of the actor forcing approval |

### Response

Returns the updated Proposal object with status `approved`.

!!! warning "Audit Trail"
    Force approval is logged in the audit trail. Use sparingly.

## Publish from Proposal

```http
POST /api/v1/proposals/{proposal_id}/publish
```

Publish a contract from an approved proposal. Only works on proposals with status `approved`. Creates a new contract with the proposed schema and deprecates the previous active contract.

### Request Body

```json
{
  "version": "2.0.0",
  "published_by": "team-uuid",
  "published_by_user_id": "user-uuid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | yes | Semantic version for the new contract |
| `published_by` | uuid | yes | Team ID publishing the contract |
| `published_by_user_id` | uuid | no | User ID publishing the contract |

### Response

```json
{
  "action": "published",
  "proposal_id": "proposal-uuid",
  "contract": {
    "id": "contract-uuid",
    "asset_id": "asset-uuid",
    "version": "2.0.0",
    "status": "active",
    "schema_def": {},
    "published_by": "team-uuid",
    "published_at": "2025-01-17T10:00:00Z"
  },
  "deprecated_contract_id": "old-contract-uuid"
}
```

An `audit_warning` field is included if the asset's most recent audit run is not passing.

## Withdraw Proposal

```http
POST /api/v1/proposals/{proposal_id}/withdraw
```

Withdraw a pending proposal. The API key's team must match the proposer team, or the key must have admin scope.

### Response

Returns the updated Proposal object with status `withdrawn`.

## Expire Proposal

```http
POST /api/v1/proposals/{proposal_id}/expire
```

Manually expire a single pending proposal. The API key's team must be the proposer team, the asset owner team, or have admin scope.

### Response

Returns the updated Proposal object with status `expired`.

## Expire Pending Proposals (Bulk)

```http
POST /api/v1/proposals/expire-pending
```

Expire all pending proposals that have passed their `expires_at` deadline. Requires admin scope. Designed to be called periodically via cron.

### Response

```json
{
  "expired_count": 3,
  "expired_proposal_ids": ["proposal-uuid-1", "proposal-uuid-2", "proposal-uuid-3"]
}
```
