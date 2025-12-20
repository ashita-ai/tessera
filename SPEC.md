# Tessera Specification

Technical specification for the Tessera data contract coordination service.

## Core Concepts

- **Producer**: A team or system that owns a data asset (table, view, model)
- **Consumer**: A team or system that depends on a data asset
- **Contract**: A versioned schema definition plus guarantees (freshness, nullability, valid values)
- **Registration**: A consumer's declaration that they depend on a specific contract version
- **Proposal**: A producer's request to change a contract. Triggers impact analysis and consumer notification

## Entities

### Team

```
Team
├── id (uuid)
├── name (string)
├── created_at (timestamp)
└── metadata (json)
```

### Asset

```
Asset
├── id (uuid)
├── fqn (e.g., "snowflake.analytics.dim_customers")
├── owner_team_id (uuid -> Team)
├── created_at (timestamp)
└── metadata (json)
```

### Contract

```
Contract
├── id (uuid)
├── asset_id (uuid -> Asset)
├── version (semver string)
├── schema (json)
├── compatibility_mode (backward | forward | full | none)
├── guarantees (json)
├── status (active | deprecated | retired)
├── published_at (timestamp)
└── published_by (uuid -> Team)
```

### Registration

```
Registration
├── id (uuid)
├── contract_id (uuid -> Contract)
├── consumer_team_id (uuid -> Team)
├── pinned_version (nullable string)  # null = track latest compatible
├── status (active | migrating | inactive)
├── registered_at (timestamp)
└── acknowledged_at (nullable timestamp)
```

### Proposal

```
Proposal
├── id (uuid)
├── asset_id (uuid -> Asset)
├── proposed_schema (json)
├── change_type (patch | minor | major)
├── breaking_changes (json)  # list of specific incompatibilities
├── status (pending | approved | rejected | withdrawn)
├── proposed_by (uuid -> Team)
├── proposed_at (timestamp)
└── resolved_at (nullable timestamp)
```

### Acknowledgment

```
Acknowledgment
├── id (uuid)
├── proposal_id (uuid -> Proposal)
├── consumer_team_id (uuid -> Team)
├── response (approved | blocked | migrating)
├── migration_deadline (nullable timestamp)
├── responded_at (timestamp)
└── notes (nullable string)
```

## Compatibility Modes

| Mode | Add column | Drop column | Rename column | Widen type | Narrow type |
|------|------------|-------------|---------------|------------|-------------|
| backward | yes | no | no | yes | no |
| forward | no | yes | no | no | yes |
| full | no | no | no | no | no |
| none | yes | yes | yes | yes | yes |

- **backward**: New schema can read old data (safe for producers to evolve)
- **forward**: Old schema can read new data (safe for consumers)
- **full**: Both directions (strictest)
- **none**: No compatibility checks, just notify

Default: `backward`

## Guarantees

Beyond schema, contracts can specify guarantees:

```json
{
  "freshness": {
    "max_staleness_minutes": 60,
    "measured_by": "column:updated_at"
  },
  "volume": {
    "min_rows": 1000,
    "max_row_delta_pct": 50
  },
  "nullability": {
    "customer_id": "never",
    "email": "allowed"
  },
  "accepted_values": {
    "status": ["active", "churned", "pending"]
  }
}
```

## API Surface

### Teams

```
POST   /teams
GET    /teams
GET    /teams/{id}
PATCH  /teams/{id}
```

### Assets

```
POST   /assets
GET    /assets
GET    /assets/{id}
GET    /assets?owner={team_id}
```

### Contracts

```
POST   /assets/{asset_id}/contracts
GET    /assets/{asset_id}/contracts
GET    /contracts/{id}
GET    /contracts/{id}/registrations
```

### Registrations

```
POST   /contracts/{contract_id}/registrations
GET    /registrations/{id}
PATCH  /registrations/{id}
DELETE /registrations/{id}
```

### Proposals

```
POST   /assets/{asset_id}/proposals
GET    /proposals/{id}
POST   /proposals/{id}/acknowledge
POST   /proposals/{id}/withdraw
POST   /proposals/{id}/force
```

### Analysis

```
GET    /assets/{asset_id}/impact?proposed_schema={...}
GET    /assets/{asset_id}/lineage
```

### Git Sync

```
POST   /sync/push    # Export database state to git-friendly format
POST   /sync/pull    # Import git-friendly format into database
```

## Key Workflows

### 1. Producer publishes a new contract

```
POST /assets/{asset_id}/contracts
{
  "schema": {...},
  "guarantees": {...},
  "compatibility_mode": "backward"
}
```

Tessera:
1. Diffs against current active contract
2. Classifies change type (patch/minor/major)
3. If non-breaking under compatibility mode: auto-publish
4. If breaking: create Proposal, notify consumers

### 2. Consumer registers

```
POST /contracts/{contract_id}/registrations
{
  "consumer_team_id": "ml-features",
  "pinned_version": null
}
```

Consumer is now in the dependency graph. Gets notified on proposals.

### 3. Breaking change proposal flow

```
Producer                    Tessera                     Consumers
   |                           |                            |
   |-- propose change -------->|                            |
   |                           |-- notify (N consumers) --->|
   |                           |                            |
   |                           |<-- ack: approved ----------|
   |                           |<-- ack: migrating (30d) ---|
   |                           |<-- ack: blocked -----------|
   |                           |                            |
   |<-- status: 2/3 acked -----|                            |
   |                           |                            |
   # Producer decides: wait, withdraw, or force
```

Force-publish is allowed but logged. Social pressure, not hard blocks.

### 4. Impact analysis (CI integration)

```
GET /assets/{asset_id}/impact?proposed_schema={...}

Response:
{
  "change_type": "major",
  "breaking_changes": [
    {"type": "dropped_column", "column": "legacy_score"}
  ],
  "impacted_consumers": [
    {"team": "ml-features", "status": "active", "pinned": "v2"},
    {"team": "reporting", "status": "active", "pinned": null}
  ],
  "safe_to_publish": false
}
```

## Database Schemas

### core
- teams
- assets
- contracts
- registrations

### workflow
- proposals
- acknowledgments

### audit
- events (append-only)

```sql
CREATE TABLE audit.events (
  id uuid PRIMARY KEY,
  entity_type text,
  entity_id uuid,
  action text,
  actor_id uuid,
  payload jsonb,
  occurred_at timestamptz DEFAULT now()
);
```

## Open Questions

- **Schema format**: JSON Schema for warehouse use cases
- **Auth model**: Start simple with API keys per team
- **Notification delivery**: Webhook-first, let consumers route as needed
- **dbt integration**: Parse manifest.json to auto-register assets
