# Spec 004: Semantic Metadata

**ADR**: 001-ai-enablement
**Priority**: 4
**Status**: Draft

## Overview

Extend assets and contracts to carry business context — descriptions, tags, field-level documentation — so that AI agents (and humans) can reason about what data means, not just its shape.

## Schema Changes

### AssetDB

Add:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `tags` | `JSON` | `[]` | Free-form string labels (e.g., `["pii", "financial", "sla:p1"]`) |

Note: `description` already exists on assets but is underused. No schema change needed — just better population.

### ContractDB

Add:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `field_descriptions` | `JSON` | `{}` | Map of JSON path -> human-readable description |
| `field_tags` | `JSON` | `{}` | Map of JSON path -> list of tags |

Example `field_descriptions`:
```json
{
  "$.properties.customer_id": "Unique identifier for the customer, matches CRM system ID",
  "$.properties.lifetime_value": "Total revenue attributed to this customer since first purchase, in USD",
  "$.properties.churn_risk_score": "ML-predicted probability of churn in next 90 days (0.0-1.0)"
}
```

Example `field_tags`:
```json
{
  "$.properties.customer_id": ["pii", "join-key"],
  "$.properties.email": ["pii", "gdpr-deletable"],
  "$.properties.lifetime_value": ["financial", "derived"]
}
```

### Migration

Alembic migration adding three JSON columns. All nullable with empty defaults. No data backfill.

## API Changes

### Publish Contract

`POST /api/v1/assets/{asset_id}/publish`

Add optional fields to request body:

```json
{
  "schema_def": { "..." },
  "field_descriptions": {
    "$.properties.customer_id": "Unique customer identifier from CRM"
  },
  "field_tags": {
    "$.properties.customer_id": ["pii", "join-key"]
  }
}
```

Field descriptions and tags from the previous contract version carry forward to the new version for fields that still exist. New fields start with no description/tags unless provided. Removed fields' metadata is dropped.

### Update Asset

`PATCH /api/v1/assets/{asset_id}`

Add `tags` to the updatable fields:

```json
{
  "tags": ["pii", "financial", "sla:p1"]
}
```

### Asset Context Endpoint

The Asset Context endpoint (`GET /api/v1/assets/{asset_id}/context`) is fully specified in Spec 001. Its response includes `field_descriptions` and `field_tags` from this spec's schema changes — see the `current_contract` section of the Spec 001 response for how semantic metadata is surfaced.

### Search

`GET /api/v1/search`

Add `tags` as a filter parameter:

```
GET /api/v1/search?q=customer&tags=pii,financial
```

## Sync Endpoint Enhancements

### dbt Sync

Extract from dbt manifest:
- Column `description` fields -> `field_descriptions`
- Column `meta.tags` or `meta.tessera.tags` -> `field_tags`
- Model `description` -> asset `description`
- Model `meta.tags` or `meta.tessera.tags` -> asset `tags`

### OpenAPI Sync

Extract from OpenAPI spec:
- Property `description` fields -> `field_descriptions`
- Operation `tags` -> asset `tags`
- Operation `summary`/`description` -> asset `description`

### GraphQL Sync

Extract from introspection:
- Field `description` -> `field_descriptions`
- Type `description` -> asset `description`

## Testing

| Test case | Assertion |
|-----------|-----------|
| Publish with field_descriptions | Descriptions stored and returned |
| Publish with field_tags | Tags stored and returned |
| Field descriptions carry forward | New version inherits descriptions for unchanged fields |
| Removed field descriptions dropped | Descriptions for removed fields not carried forward |
| Asset tags CRUD | Create, read, update tags on assets |
| Search by tags | Only matching assets returned |
| Context endpoint | All sections populated correctly |
| dbt sync extracts descriptions | Column descriptions mapped to field_descriptions |
| OpenAPI sync extracts descriptions | Property descriptions mapped to field_descriptions |
