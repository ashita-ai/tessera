# Spec 001: Preflight-to-Inference Pipeline

**Strategy doc**: [Passive Discovery](../strategy/passive-discovery.md), Phase 1
**Priority**: 1 (implement first — zero new infrastructure, highest ROI)
**Status**: Draft
**Estimated effort**: 1-2 weeks

## Overview

Mine the existing audit trail for dependency signals. Every `preflight.checked` event records which team checked which asset. Aggregating these into inferred dependencies surfaces real consumption patterns without requiring manual registration.

This is the cheapest possible validation of passive discovery. If it works, it justifies investing in warehouse connectors. If it doesn't, we learn that before writing Snowflake integrations.

## Data Source

The `log_preflight_checked()` function in `services/audit.py` already records:

```python
{
    "entity_type": "asset",
    "entity_id": asset_id,         # UUID of the asset
    "action": "preflight.checked",
    "actor_id": team_id,           # UUID of the consuming team (from API key)
    "actor_type": "agent" | "human",
    "payload": {
        "asset_fqn": "warehouse.analytics.orders",
        "contract_version": "2.1.0",
        "freshness_status": "fresh" | "stale",
        "guarantees_checked": true | false,
        "consumer_type": "agent" | "human" | "pipeline" | null
    }
}
```

Every field needed for inference already exists. No schema changes to the audit table.

## New Database Model

### Migration 017: Inferred Dependencies

```python
class InferredDependencyStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InferredDependencyDB(Base):
    __tablename__ = "inferred_dependencies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=False, index=True
    )
    consumer_team_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("teams.id"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType), default=DependencyType.CONSUMES
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g., "preflight_audit", "warehouse_query_logs", "dbt_column_lineage"

    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Source-specific: {"preflight_calls_30d": 142, "actor_type": "agent", ...}

    status: Mapped[InferredDependencyStatus] = mapped_column(
        Enum(InferredDependencyStatus),
        default=InferredDependencyStatus.PENDING,
        index=True,
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    promoted_registration_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("registrations.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("asset_id", "consumer_team_id", "source",
                         name="uq_inferred_dep_asset_team_source"),
    )
```

**Soft delete**: Not needed. Rejected inferences use `status=REJECTED`. Expired ones use `status=EXPIRED`. The row stays for suppression logic (don't re-infer rejected pairs).

## Service Layer

### `services/discovery.py`

```python
async def run_preflight_inference(
    session: AsyncSession,
    lookback_days: int = 30,
    min_calls: int = 5,
    min_confidence: float = 0.5,
) -> list[InferredDependencyDB]:
    """Scan preflight audit events and create/update inferred dependencies.

    Steps:
    1. Query audit_events WHERE action = 'preflight.checked'
       AND created_at > now() - lookback_days
    2. Group by (entity_id, actor_id) → (asset_id, team_id)
    3. For each group:
       a. Skip if team already has an active registration for this asset
       b. Skip if an inferred dependency with status=REJECTED exists
       c. Compute confidence score
       d. If confidence >= min_confidence: upsert InferredDependencyDB
    4. Expire stale inferences (last_observed_at > 2x lookback_days ago)
    5. Return new/updated inferences
    """
```

### Confidence Scoring

For the preflight source, confidence is a function of:

```python
def compute_preflight_confidence(
    call_count: int,
    distinct_days: int,
    days_since_last_call: int,
    is_agent: bool,
    lookback_days: int = 30,
) -> float:
    """Score a preflight-inferred dependency.

    Factors:
    - Frequency:    call_count / lookback_days (normalized to 0-1, capped at 1.0)
    - Regularity:   distinct_days / lookback_days (how many days had at least one call)
    - Recency:      1.0 - (days_since_last_call / lookback_days) (decays linearly)
    - Agent bonus:  +0.1 if is_agent (agents are more likely to be systematic consumers)

    Weights: frequency=0.35, regularity=0.30, recency=0.25, agent=0.10
    """
```

**Examples:**

| Scenario | Calls | Distinct days | Last call | Agent? | Score |
|----------|-------|---------------|-----------|--------|-------|
| Daily CI agent | 300 | 30 | 0 days ago | yes | ~0.95 |
| Weekly dashboard refresh | 8 | 4 | 2 days ago | no | ~0.55 |
| One-off ad-hoc query | 1 | 1 | 25 days ago | no | ~0.12 |
| Nightly ML pipeline | 30 | 28 | 0 days ago | yes | ~0.90 |

## API Endpoints

### Trigger Scan

```
POST /api/v1/discovery/scan
```

Request body:
```json
{
  "source": "preflight_audit",
  "lookback_days": 30,
  "min_calls": 5,
  "min_confidence": 0.5
}
```

Response (200):
```json
{
  "source": "preflight_audit",
  "scan_duration_ms": 342,
  "events_scanned": 12847,
  "pairs_evaluated": 89,
  "inferred_new": 14,
  "inferred_updated": 23,
  "inferred_expired": 3,
  "skipped_already_registered": 41,
  "skipped_previously_rejected": 8
}
```

**Authorization**: ADMIN scope. This is an operational action, not a consumer workflow.

### List Inferred Dependencies

```
GET /api/v1/discovery/inferred
```

Query parameters:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `asset_id` | UUID | — | Filter by asset |
| `team_id` | UUID | — | Filter by consumer team |
| `status` | string | `pending` | Filter: pending, confirmed, rejected, expired |
| `min_confidence` | float | 0.0 | Minimum confidence threshold |
| `source` | string | — | Filter by source (preflight_audit, etc.) |
| `limit` | int | 50 | Pagination |
| `offset` | int | 0 | Pagination |

Response (200):
```json
{
  "inferred_dependencies": [
    {
      "id": "uuid",
      "asset_id": "uuid",
      "asset_fqn": "warehouse.analytics.orders",
      "consumer_team_id": "uuid",
      "consumer_team_name": "ml-features",
      "dependency_type": "CONSUMES",
      "confidence": 0.91,
      "source": "preflight_audit",
      "status": "pending",
      "evidence": {
        "preflight_calls_30d": 285,
        "distinct_days": 29,
        "days_since_last_call": 0,
        "actor_type": "agent",
        "agent_names": ["feature-store-agent"]
      },
      "first_observed_at": "2026-02-28T00:00:00Z",
      "last_observed_at": "2026-03-29T08:15:00Z"
    }
  ],
  "total": 14
}
```

**Authorization**: READ scope. Team-scoped: non-admin keys only see inferences for their own team.

### Confirm Inference

```
POST /api/v1/discovery/inferred/{id}/confirm
```

Request body:
```json
{
  "dependency_type": "CONSUMES",
  "pinned_version": null
}
```

Response (200):
```json
{
  "inferred_dependency_id": "uuid",
  "status": "confirmed",
  "promoted_registration": {
    "registration_id": "uuid",
    "contract_id": "uuid",
    "consumer_team_id": "uuid",
    "status": "ACTIVE"
  }
}
```

**What happens on confirm:**
1. Set `InferredDependencyDB.status = CONFIRMED`, `confirmed_at = now()`, `confirmed_by = auth.user_id`.
2. Find the active contract for the inferred asset.
3. Create a `RegistrationDB` for the consumer team on that contract.
4. Store the registration ID in `promoted_registration_id`.
5. Log `discovery.confirmed` audit event.

If a registration already exists (race condition), return the existing registration without creating a duplicate.

**Authorization**: WRITE scope. Team-scoped: the confirming team must match the inferred `consumer_team_id`, or the key must have ADMIN scope.

### Reject Inference

```
POST /api/v1/discovery/inferred/{id}/reject
```

Request body:
```json
{
  "reason": "This is an ad-hoc exploration, not a real dependency"
}
```

Response (200):
```json
{
  "inferred_dependency_id": "uuid",
  "status": "rejected"
}
```

**What happens on reject:**
1. Set `InferredDependencyDB.status = REJECTED`.
2. Log `discovery.rejected` audit event with reason.
3. Future scans skip this (asset_id, consumer_team_id, source) tuple.

**Authorization**: WRITE scope. Team-scoped.

### Coverage Report

```
GET /api/v1/discovery/coverage
```

Response (200):
```json
{
  "total_assets": 342,
  "assets_with_registrations": 127,
  "assets_with_inferred_only": 89,
  "assets_with_no_known_consumers": 126,
  "coverage_registered": 0.37,
  "coverage_with_inferred": 0.63,
  "highest_risk_gaps": [
    {
      "asset_id": "uuid",
      "asset_fqn": "warehouse.core.users",
      "preflight_calls_30d": 2341,
      "distinct_consumer_teams": 12,
      "registrations": 0,
      "inferred_pending": 8
    }
  ]
}
```

`highest_risk_gaps` returns the top 20 assets with the most preflight activity and zero registrations — the assets most likely to cause surprise breakages.

**Authorization**: READ scope. ADMIN-only for the full report; team-scoped for non-admin (only shows assets the team owns or consumes).

## Integration with Existing Systems

### Affected Parties

`services/affected_parties.py` currently checks:
1. `AssetDependencyDB` table
2. `metadata_.depends_on` fallback

After this spec, it should also check:
3. Confirmed `InferredDependencyDB` records (which have been promoted to registrations)

No change needed — confirmed inferences are promoted to standard registrations, which are already picked up by the existing proposal notification logic.

**PENDING inferred dependencies are NOT included in affected parties.** Unconfirmed inferences should not block publishing. They should be surfaced in impact preview as a warning: "N unconfirmed consumers may also be affected."

### Impact Preview

Extend the impact preview response to include:

```json
{
  "unconfirmed_consumers": [
    {
      "consumer_team_name": "ml-features",
      "confidence": 0.91,
      "source": "preflight_audit",
      "status": "pending"
    }
  ]
}
```

This tells a producer: "There are consumers we think exist but haven't confirmed. You might want to reach out before shipping this change."

## Testing

| Test case | Assertion |
|-----------|-----------|
| Scan with preflight events | Creates InferredDependencyDB records for above-threshold pairs |
| Scan skips existing registrations | No inference for teams already registered |
| Scan skips rejected pairs | No re-inference for previously rejected (asset, team, source) |
| Scan updates existing inferences | `last_observed_at` and `confidence` updated on re-scan |
| Scan expires stale inferences | Inferences not refreshed in 2x lookback window expire |
| Confidence: daily agent | Score > 0.9 |
| Confidence: one-off human | Score < 0.3 (below min_confidence, not stored) |
| Confirm inference | Creates registration, sets status=CONFIRMED |
| Confirm when registration exists | Returns existing registration, no duplicate |
| Reject inference | Sets status=REJECTED, future scans skip |
| Coverage report | Correct counts for registered, inferred, and gap assets |
| Impact preview includes unconfirmed | `unconfirmed_consumers` populated for assets with pending inferences |
| Team scoping | Non-admin keys only see their own team's inferences |

## Rollout Plan

1. **Migration 017**: Add `inferred_dependencies` table.
2. **Service**: `services/discovery.py` with scan logic and confidence scoring.
3. **API**: `api/discovery.py` with scan, list, confirm, reject, coverage endpoints.
4. **Integration**: Extend impact preview to include `unconfirmed_consumers`.
5. **Tests**: Full coverage of scan, scoring, confirm/reject, coverage report.
6. **Documentation**: Add discovery guide to docs site.

No scheduled/cron execution in this spec. The `POST /discovery/scan` is triggered manually or by an external scheduler (cron, Airflow, etc.). Automated scheduling is a future enhancement once the pipeline is validated.
