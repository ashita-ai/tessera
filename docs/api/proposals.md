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
| `status` | string | Filter by status (pending, approved, published, rejected) |
| `page` | int | Page number |
| `page_size` | int | Results per page |

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
      "total_consumers": 3,
      "acknowledgment_count": 1,
      "proposed_at": "2025-01-15T10:00:00Z",
      "proposed_by": "team-uuid"
    }
  ]
}
```

## Get Proposal

```http
GET /api/v1/proposals/{proposal_id}
```

### Response

```json
{
  "id": "proposal-uuid",
  "asset_id": "asset-uuid",
  "asset_fqn": "warehouse.analytics.users",
  "status": "pending",
  "change_type": "major",
  "proposed_schema": {...},
  "breaking_changes": [
    {
      "type": "property_removed",
      "path": "$.properties.email",
      "description": "Property 'email' was removed"
    }
  ],
  "consumers": [
    {
      "team_id": "team-uuid",
      "team_name": "Analytics",
      "acknowledged": true,
      "acknowledged_at": "2025-01-16T10:00:00Z",
      "notes": "Updated our dashboards"
    },
    {
      "team_id": "team-uuid-2",
      "team_name": "Finance",
      "acknowledged": false
    }
  ],
  "proposed_at": "2025-01-15T10:00:00Z",
  "proposed_by": "team-uuid"
}
```

## Acknowledge Proposal

```http
POST /api/v1/proposals/{proposal_id}/acknowledge
```

Acknowledge that your team is ready for the breaking change.

### Request Body

```json
{
  "notes": "We've updated our dashboards to handle this change"
}
```

### Response

```json
{
  "acknowledged": true,
  "acknowledged_at": "2025-01-16T10:00:00Z",
  "remaining_consumers": 1
}
```

## Get Proposal Status

```http
GET /api/v1/proposals/{proposal_id}/status
```

Quick check of acknowledgment progress.

### Response

```json
{
  "status": "pending",
  "total_consumers": 3,
  "acknowledged": 2,
  "remaining": 1,
  "can_publish": false
}
```

## Force Publish

```http
POST /api/v1/proposals/{proposal_id}/force-publish
```

Publish without waiting for all acknowledgments (admin only).

### Request Body

```json
{
  "reason": "Critical security fix, cannot wait for all acknowledgments"
}
```

### Response

```json
{
  "published": true,
  "contract_id": "new-contract-uuid",
  "contract_version": "2.0.0"
}
```

!!! warning "Audit Trail"
    Force publishing is logged with the reason. Use sparingly.

## Reject Proposal

```http
POST /api/v1/proposals/{proposal_id}/reject
```

Reject a proposal (producer only).

### Request Body

```json
{
  "reason": "Decided to take a different approach"
}
```

## Withdraw Proposal

```http
DELETE /api/v1/proposals/{proposal_id}
```

Withdraw a pending proposal (producer only).

Returns `204 No Content` on success.
