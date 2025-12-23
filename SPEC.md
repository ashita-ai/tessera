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

### APIKey

```
APIKey
├── id (uuid)
├── key_hash (string)          # SHA-256 hash of the key
├── key_prefix (string)        # First few chars for identification (e.g., "tess_live_abc1")
├── name (string)              # Human-readable name
├── team_id (uuid -> Team)
├── scopes (json)              # List of permissions: read, write, admin
├── created_at (timestamp)
├── expires_at (nullable timestamp)
├── last_used_at (nullable timestamp)
└── revoked_at (nullable timestamp)
```

### AuditRun (WAP)

```
AuditRun
├── id (uuid)
├── asset_id (uuid -> Asset)
├── run_id (string)            # External run identifier (dbt run_id, etc.)
├── status (passed | failed | partial)
├── triggered_by (string)      # "dbt_test", "great_expectations", "soda", etc.
├── total_checks (int)
├── passed_checks (int)
├── failed_checks (int)
├── guarantee_results (json)   # Per-guarantee pass/fail details
├── details (json)             # Additional context (errors, warnings)
├── started_at (timestamp)
├── completed_at (timestamp)
└── reported_at (timestamp)
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

All endpoints under `/api/v1`. Authentication via `Authorization: Bearer <api_key>` header.

### Teams

```
POST   /teams              # Create team
GET    /teams              # List teams (paginated)
GET    /teams/{id}         # Get team
PUT    /teams/{id}         # Update team
```

### Assets

```
POST   /assets                      # Create asset
GET    /assets                      # List assets (paginated)
GET    /assets/{id}                 # Get asset
POST   /assets/{id}/contracts       # Publish contract
POST   /assets/{id}/impact          # Impact analysis
POST   /assets/{id}/audit           # Report WAP audit run
GET    /assets/{id}/audit-history   # Get audit history (paginated)
GET    /assets/{id}/audit-trends    # Get audit trends and alerts
```

### Contracts

```
GET    /contracts                   # List contracts (paginated)
GET    /contracts/{id}              # Get contract
```

### Registrations

```
POST   /registrations?contract_id=  # Register as consumer
GET    /registrations/{id}          # Get registration
PATCH  /registrations/{id}          # Update registration
DELETE /registrations/{id}          # Unregister
```

### Proposals

```
GET    /proposals                   # List proposals
GET    /proposals/{id}              # Get proposal
POST   /proposals/{id}/acknowledge  # Acknowledge breaking change
```

### Sync (dbt integration)

```
POST   /sync/push          # Export contracts to git (requires GIT_SYNC_PATH)
POST   /sync/pull          # Import contracts from git (requires GIT_SYNC_PATH)
POST   /sync/dbt           # Sync from dbt manifest
POST   /sync/dbt/impact    # CI/CD impact analysis
```

### Schemas

```
POST   /schemas/validate   # Validate JSON Schema
```

### API Keys

```
POST   /api-keys           # Create API key (admin only)
GET    /api-keys           # List API keys
GET    /api-keys/{id}      # Get API key
DELETE /api-keys/{id}      # Revoke API key (admin only)
```

### Health

```
GET    /health             # Basic health check
GET    /health/ready       # Readiness probe (checks database)
GET    /health/live        # Liveness probe
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
POST /registrations?contract_id={contract_id}
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
POST /assets/{asset_id}/impact
{
  "proposed_schema": {...}
}

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
- api_keys
- dependencies
- audit_runs (WAP data quality runs)

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

## Authentication

API key-based authentication with three scopes:

| Scope | Permissions |
|-------|-------------|
| read | GET endpoints, list/view operations |
| write | POST/PUT/PATCH, create/update operations |
| admin | DELETE, API key management, team management |

Keys are prefixed with `tess_{environment}_` (e.g., `tess_live_abc123...`).

Bootstrap flow:
1. Set `BOOTSTRAP_API_KEY` environment variable
2. Create first team using bootstrap key
3. Create admin API key for that team
4. Use admin key for ongoing operations

Development mode: Set `AUTH_DISABLED=true` to skip authentication (uses first team in database).

## Resolved Design Decisions

- **Schema format**: JSON Schema
- **Auth model**: API keys per team with read/write/admin scopes
- **Notification delivery**: Webhook-first (configurable via `WEBHOOK_URL`)
- **dbt integration**: Parse manifest.json via `/sync/dbt` endpoint
