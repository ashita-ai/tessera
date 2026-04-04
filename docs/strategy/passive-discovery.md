# Passive Discovery

**Status:** Draft
**Date:** 2026-03-29
**Author:** Evan Volgas

!!! note "OTEL Discovery Priority"
    Following [ADR-014](../adrs/014-service-contract-pivot.md) (Spec-007), OTEL-based service dependency discovery is now the priority tier for discovering dependencies between services. The OTEL approach queries trace backends (Jaeger, Tempo, Datadog) for service-to-service call edges and maps them to Tessera registrations with confidence scores. Warehouse query log scanning remains relevant for data model dependencies but is no longer the primary discovery mechanism.

## The Problem

Tessera's coordination model is only as good as its dependency graph. If a producer makes a breaking change and Tessera doesn't know about a downstream consumer, that consumer breaks silently — exactly the failure mode Tessera exists to prevent.

Today, the dependency graph is populated by two mechanisms:
1. **Manual registration:** A team calls `POST /registrations` to declare a dependency.
2. **dbt sync:** `depends_on` from dbt manifests creates implicit dependencies during `POST /sync/dbt`.

Both are opt-in. Both require the consumer to take action. Both miss the vast majority of real-world dependencies.

**The cold-start problem is existential.** An incomplete dependency graph is worse than no graph at all — it creates false confidence. A producer checks impact analysis, sees zero affected parties, ships a breaking change, and breaks three dashboards that never registered. The next time someone checks impact analysis, they don't trust it. Trust lost this way is nearly impossible to recover.

### What's Missing

| Dependency source | Current coverage |
|-------------------|-----------------|
| dbt model → dbt model | Covered (dbt sync extracts `depends_on`) |
| dbt model → dbt source | Covered (dbt sync) |
| Dashboard → table | **Not covered** |
| Ad-hoc query → table | **Not covered** |
| Python script → table | **Not covered** |
| AI agent → table | **Not covered** (preflight calls are logged but not converted to registrations) |
| Airflow task → table | **Not covered** |
| Microservice → table | **Not covered** |
| API → table | **Not covered** |

The dbt sync covers maybe 30-40% of real dependencies in a typical data org. The rest are invisible.

---

## Current Infrastructure

### Two Parallel Dependency Systems

Tessera stores dependencies in two places that don't talk to each other:

1. **`AssetDependencyDB` table** — explicit asset-to-asset edges with typed relationships (CONSUMES, REFERENCES, TRANSFORMS). Created manually via `POST /dependencies`. Used by impact analysis graph traversal.

2. **`metadata_.depends_on` JSON array** — list of upstream FQNs stored on each asset. Populated by dbt sync. Used as a fallback by the affected_parties service (LIKE query on JSON column).

The impact analysis endpoint (`POST /assets/{id}/impact`) only traverses the `AssetDependencyDB` table. The affected_parties service checks both but prefers the table. This means dbt-sourced dependencies that only live in metadata are partially invisible to impact analysis.

### What's Already Instrumented

Three data sources that could feed passive discovery already exist:

1. **Preflight call logs.** Every `GET /{fqn}/preflight` call is logged as a `preflight.checked` audit event with `consumer_type` and the requesting API key's team. An agent calling preflight is declaring "I'm about to consume this data." That's a dependency signal.

2. **Warehouse query logs (future).** Connecting to warehouse query log APIs (BigQuery `INFORMATION_SCHEMA.JOBS`, Snowflake `ACCESS_HISTORY`) would reveal which services and users actually read which tables. The connector infrastructure was removed in ADR-014 but the pattern is straightforward to reimplement when needed.

3. **Audit trail with actor_type.** Every action records who did it and whether they're human or agent. This gives us a behavioral signal of who interacts with which assets.

---

## The Passive Discovery Strategy

### Principle: Observe, Then Confirm

Passive discovery should not automatically create hard dependencies. It should observe behavior, infer probable dependencies, and surface them for confirmation. The workflow:

1. **Observe:** Collect signals about who queries what.
2. **Infer:** Map signals to probable dependencies (asset, consumer team, dependency type, confidence).
3. **Surface:** Present inferred dependencies to teams for confirmation.
4. **Promote:** Confirmed dependencies become first-class registrations. Rejected inferences are suppressed.

This is the difference between "we automatically registered you as a consumer" (dangerous — noisy, wrong, erodes trust) and "we think you consume this table — can you confirm?" (helpful — saves manual work, builds trust).

### Signal Sources (Ranked by Value)

#### Tier 0: Highest-Value (Service Dependencies)

**OTEL Trace-Based Discovery** — see [ADR-014, Phase 2](../adrs/014-service-contract-pivot.md). Query OTEL-compatible backends for service-to-service call edges. This is the primary discovery mechanism for service dependencies and is being implemented as part of the service contract pivot.

#### Tier 1: High-Value, Moderate Effort

**1. Warehouse Query Logs**

Every major warehouse keeps query history:
- **Snowflake:** `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` + `ACCESS_HISTORY` (column-level)
- **BigQuery:** `INFORMATION_SCHEMA.JOBS` + audit logs
- **Databricks:** `system.access.audit` + query history
- **Redshift:** `STL_QUERY` + `SVL_QUERY_SUMMARY`

From query logs, you can extract:
- Which tables are read by which queries
- Which columns are referenced (from `ACCESS_HISTORY` on Snowflake, query plans elsewhere)
- The service account or user that ran the query (maps to Tessera team via configuration)
- Frequency and recency (a table queried daily by a service account is a strong dependency signal)

**Implementation shape:**
```
POST /discovery/warehouse-scan
{
  "warehouse_type": "snowflake",
  "connection": { ... },
  "lookback_days": 30,
  "user_to_team_mapping": {
    "svc_analytics": "team-analytics-id",
    "svc_ml_pipeline": "team-ml-id"
  }
}

Response:
{
  "inferred_dependencies": [
    {
      "asset_fqn": "warehouse.analytics.orders",
      "consumer_team": "team-analytics-id",
      "dependency_type": "CONSUMES",
      "confidence": 0.92,
      "evidence": {
        "query_count_30d": 847,
        "distinct_users": 3,
        "columns_accessed": ["order_id", "customer_id", "total_amount", "status"],
        "last_accessed": "2026-03-28T14:22:00Z",
        "sample_query_hash": "a1b2c3..."
      }
    }
  ]
}
```

**Why this is Tier 1:** Query logs are the ground truth of who depends on what. Every other signal is a proxy. Query logs are the actual behavior.

**2. Preflight Call Conversion**

Tessera already logs every preflight call with the requesting team. Convert these into dependency signals:

- An agent that calls `GET /warehouse.analytics.orders/preflight` 100 times in the last 30 days is almost certainly a consumer.
- Group by (asset, team) and threshold on frequency.
- This requires zero new infrastructure — the audit trail already has the data.

**Implementation shape:**
```
POST /discovery/from-audit
{
  "lookback_days": 30,
  "min_preflight_calls": 5
}

Response:
{
  "inferred_dependencies": [
    {
      "asset_fqn": "warehouse.analytics.orders",
      "consumer_team": "team-ml-id",
      "dependency_type": "CONSUMES",
      "confidence": 0.85,
      "evidence": {
        "preflight_calls_30d": 142,
        "actor_type": "agent",
        "agent_name": "feature-store-agent"
      }
    }
  ]
}
```

**Why this is Tier 1:** It's free. The data already exists. The implementation is a query against the audit table. Ship this first.

#### Tier 2: High-Value, Higher Effort

**3. dbt Column Lineage**

dbt's manifest includes column-level lineage (which columns a model reads from which upstream source). Tessera's dbt sync currently extracts model-level `depends_on` but not column-level detail.

Extracting column lineage enables:
- Precise impact analysis: "this change drops column X, which is used by 3 models"
- Column-level dependency tracking on registrations
- Smarter migration suggestions (only suggest changes for affected columns)

**4. Airflow/Dagster/Prefect DAG Parsing**

Orchestration tools define which tasks read/write which tables. Parsing DAG definitions (Airflow's `airflow.models.DAG`, Dagster's `@asset` decorators) can extract dependencies.

This requires a new sync endpoint per orchestrator, similar to the dbt sync.

**5. BI Tool Metadata**

Looker, Tableau, Metabase, and Superset all have metadata APIs that expose which dashboards query which tables. Ingesting this data closes the "dashboard → table" gap, which is one of the largest blind spots.

#### Tier 3: Useful, Speculative

**6. Application Connection Pool Monitoring**

Track which application service accounts connect to which schemas. Lower confidence (a connection doesn't mean a dependency on a specific table), but useful for broad coverage.

**7. Network-Level Query Interception**

A proxy layer between consumers and the warehouse that logs queries in real-time. Extremely high coverage but invasive to deploy.

---

## Data Model Changes

### Inferred Dependencies

A new entity to store discovered-but-unconfirmed dependencies:

```python
class InferredDependencyDB:
    id: UUID
    asset_id: UUID (FK)
    consumer_team_id: UUID (FK)
    dependency_type: DependencyType
    confidence: float  # 0.0-1.0
    source: str  # "warehouse_query_logs", "preflight_audit", "dbt_column_lineage", etc.
    evidence: JSON  # Source-specific evidence (query counts, column lists, etc.)
    status: InferredDependencyStatus  # PENDING, CONFIRMED, REJECTED, EXPIRED
    first_observed_at: datetime
    last_observed_at: datetime
    confirmed_at: datetime | None
    confirmed_by: UUID | None  # User who confirmed
    promoted_registration_id: UUID | None  # FK to registration created on confirmation

    Unique: (asset_id, consumer_team_id, source)
```

### Status Transitions

```
PENDING → CONFIRMED (team confirms the inferred dependency)
PENDING → REJECTED (team says this isn't a real dependency)
PENDING → EXPIRED (inference not refreshed within expiry window)
CONFIRMED → promotes to RegistrationDB (first-class dependency)
REJECTED → suppressed from future inferences for this (asset, team, source) tuple
```

### Column-Level Extension (on Registration)

```python
# Add to RegistrationDB or create new table
class RegistrationColumnUsageDB:
    id: UUID
    registration_id: UUID (FK)
    column_path: str  # JSON path, e.g., "$.properties.customer_id"
    access_type: str  # "read", "filter", "join", "aggregate"
    last_observed_at: datetime
    source: str  # "warehouse_query_logs", "dbt_column_lineage", "manual"
```

This enables the highest-value impact analysis: "you're dropping `customer_id`, which is used as a join key by the analytics team and a filter column by the ML feature pipeline."

---

## API Design

### Discovery Endpoints

```
POST /discovery/scan              # Trigger a discovery scan (warehouse logs, audit trail, etc.)
GET  /discovery/inferred          # List inferred dependencies (filterable by asset, team, status, confidence)
POST /discovery/inferred/{id}/confirm   # Team confirms an inferred dependency → creates registration
POST /discovery/inferred/{id}/reject    # Team rejects an inferred dependency → suppressed
GET  /discovery/coverage          # Coverage report: what % of assets have registered consumers?
```

### Coverage Report

The coverage endpoint is critical for building trust in the dependency graph:

```json
{
  "total_assets": 342,
  "assets_with_registrations": 127,
  "assets_with_inferred_only": 89,
  "assets_with_no_dependencies": 126,
  "coverage_registered": "37%",
  "coverage_with_inferred": "63%",
  "coverage_gap": [
    {"fqn": "warehouse.core.users", "query_count_30d": 2341, "unique_consumers": 12, "registrations": 0},
    {"fqn": "warehouse.core.events", "query_count_30d": 1892, "unique_consumers": 8, "registrations": 0}
  ]
}
```

This tells a data platform team: "here are your most-queried tables with zero registered consumers." That's the list they should focus on.

---

## Warehouse Connector Architecture

### Connector Interface

```python
class WarehouseDiscoveryConnector(Protocol):
    """Interface for warehouse-specific query log parsers."""

    async def discover_dependencies(
        self,
        lookback_days: int,
        user_to_team_mapping: dict[str, UUID],
        known_asset_fqns: set[str],
    ) -> list[InferredDependency]:
        """Parse query logs and return inferred dependencies.

        Only returns dependencies for FQNs that match known_asset_fqns.
        This prevents the system from inferring dependencies on tables
        that Tessera doesn't manage.
        """
        ...

    async def discover_column_usage(
        self,
        asset_fqn: str,
        lookback_days: int,
    ) -> list[ColumnUsage]:
        """Return column-level access patterns for a specific asset."""
        ...
```

### Snowflake Implementation (First Target)

Snowflake's `ACCESS_HISTORY` view provides column-level access tracking:

```sql
SELECT
    query_id,
    user_name,
    direct_objects_accessed,  -- tables/views
    base_objects_accessed,    -- underlying tables
    columns_accessed          -- column-level detail (Snowflake Enterprise+)
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
WHERE query_start_time > DATEADD(day, -30, CURRENT_TIMESTAMP())
```

**Why Snowflake first:**
- Largest market share among modern cloud warehouses for the target audience
- `ACCESS_HISTORY` provides column-level detail without query parsing
- The connector pattern is straightforward; BigQuery follows the same shape

### BigQuery Implementation (Second Target)

BigQuery's `INFORMATION_SCHEMA.JOBS` + audit logs:

```sql
SELECT
    job_id,
    user_email,
    referenced_tables,  -- array of table references
    query,              -- full query text (for column extraction via parsing)
    creation_time
FROM `region-us`.INFORMATION_SCHEMA.JOBS
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
  AND state = 'DONE'
```

BigQuery doesn't provide native column-level access history. Column extraction requires SQL parsing (e.g., `sqlglot`).

---

## Confidence Scoring

Not all inferred dependencies are equal. A service account that queries a table 1,000 times daily is a near-certain dependency. A user who ran one ad-hoc query last month is noise. The confidence score must reflect this.

### Scoring Factors

| Factor | Weight | Signal |
|--------|--------|--------|
| Query frequency (30d) | 0.30 | Daily scheduled queries → high confidence; one-off → low |
| Recency of last access | 0.20 | Accessed yesterday → high; accessed 25 days ago → decaying |
| Distinct users/service accounts | 0.15 | Multiple users from same team → high; single user → lower |
| Query pattern regularity | 0.15 | Same query at same time daily → high (scheduled); irregular → lower |
| Column specificity | 0.10 | Uses specific columns → high confidence it's a real dependency, not exploration |
| Source reliability | 0.10 | Warehouse query logs → highest; preflight audit → high; DAG parsing → moderate |

### Thresholds

| Confidence | Action |
|------------|--------|
| ≥ 0.9 | Auto-confirm (create registration without human approval). Only for well-established patterns. |
| 0.7 – 0.9 | Surface for confirmation. High-confidence inference, team should validate. |
| 0.5 – 0.7 | Surface in coverage report but don't push notifications. Team can explore if curious. |
| < 0.5 | Don't store. Too noisy to be useful. |

Auto-confirmation at ≥ 0.9 is aggressive. It should be opt-in per team, off by default.

---

## Unifying the Dependency Graph

The current two-system split (`AssetDependencyDB` + `metadata_.depends_on`) needs to be resolved before adding a third source (inferred dependencies). Otherwise, impact analysis has three places to look, none authoritative.

### Proposed Unification

1. **`AssetDependencyDB` becomes the single source of truth** for all asset-to-asset edges.
2. **dbt sync writes to `AssetDependencyDB`** instead of (or in addition to) `metadata_.depends_on`. Dependency type: `TRANSFORMS`.
3. **Confirmed inferred dependencies write to `RegistrationDB`** (team-to-asset) and optionally to `AssetDependencyDB` (asset-to-asset, if the consuming asset is known).
4. **`metadata_.depends_on` is retained** for display purposes and backward compatibility, but is no longer used by impact analysis or affected_parties.
5. **Impact analysis traverses one graph**, not two.

This is a prerequisite for passive discovery. Adding inferred dependencies to a fragmented graph makes the fragmentation worse.

---

## Implementation Phases

### Phase 1: Preflight-to-Inference Pipeline (Low Effort, High Signal)

The audit trail already logs preflight calls. Build a batch job that:
1. Queries audit events where `action = 'preflight.checked'` in the last N days
2. Groups by (asset_fqn, team_id)
3. Computes confidence based on frequency and recency
4. Creates `InferredDependencyDB` records for above-threshold pairs
5. Exposes via `GET /discovery/inferred`

**Effort:** 1-2 weeks. No new infrastructure. No warehouse connections.

**Value:** Immediately surfaces agent dependencies (since agents are the primary preflight callers). Validates the inferred dependency UX before investing in warehouse connectors.

### Phase 2: Coverage Report + Confirmation UI

Build the `GET /discovery/coverage` endpoint and the confirm/reject workflow. This gives platform teams:
- A dashboard of graph completeness
- A way to triage inferred dependencies
- Metrics to track coverage improvement over time

**Effort:** 1-2 weeks. API-only (UI can follow later).

### Phase 3: Dependency Graph Unification

Migrate dbt sync to write `AssetDependencyDB` rows. Update impact analysis to use a single graph source. Deprecate `metadata_.depends_on` for impact/affected_parties queries.

**Effort:** 2-3 weeks. Requires migration + careful testing (existing behavior must be preserved).

### Phase 4: Snowflake Connector

Build the first warehouse query log connector. Snowflake first because of `ACCESS_HISTORY` column-level support.

**Effort:** 3-4 weeks. Requires Snowflake integration testing, credential management, and the connector interface design.

### Phase 5: Column-Level Tracking

Add `RegistrationColumnUsageDB`. Populate from Snowflake `ACCESS_HISTORY` and dbt column lineage. Use in impact analysis to produce column-specific impact reports.

**Effort:** 2-3 weeks. Builds on Phase 4 infrastructure.

### Phase 6: BigQuery + Additional Connectors

Build the BigQuery connector (with `sqlglot` for column extraction), then Databricks, Redshift. Each additional connector is ~2 weeks once the interface is established.

---

## Risks

### Risk 1: Noise Overwhelms Signal

If confidence scoring is poorly calibrated, teams get flooded with false-positive inferred dependencies. They reject everything, stop checking, and the feature becomes dead weight.

**Mitigation:** Start with high thresholds (0.7+). Under-report rather than over-report. Build trust with precision before pursuing recall. Let teams tune thresholds per-asset.

### Risk 2: Warehouse Credential Management

Tessera needs read access to warehouse query logs. This means storing warehouse credentials, which is a security surface area increase.

**Mitigation:** Support short-lived credentials (Snowflake key-pair auth, BigQuery service account impersonation). Never store long-lived passwords. Consider a pull model where a warehouse agent pushes scan results to Tessera rather than Tessera pulling from the warehouse.

### Risk 3: Query Log Volume

Large organizations generate millions of queries per day. Scanning 30 days of logs could be slow and expensive.

**Mitigation:** Batch processing with incremental scans (only process queries since last scan). Pre-filter to tables that match known asset FQNs. Run during off-peak hours.

### Risk 4: Privacy Concerns

Query logs may contain sensitive information (query text with PII, user activity patterns). Teams may resist granting access.

**Mitigation:** Tessera never stores raw query text. Only aggregated signals (query count, columns accessed, user identity) are persisted. Make the warehouse connector configurable to exclude specific schemas or users from scanning.

---

## Connection to Other Strategy Docs

**Agent Opportunity:** Passive discovery solves the agent registration cold-start. Agents that call preflight are automatically surfaced as inferred consumers without requiring them to explicitly register. Column-level tracking enables precise impact analysis for agent-generated queries.

**Data Control Plane:** Passive discovery is the intelligence layer that makes the control plane real. A control plane that only knows about explicitly registered dependencies is a governance theater. One that observes actual behavior and reflects it back is operational intelligence.

---

## Success Metrics

| Metric | Target | Meaning |
|--------|--------|---------|
| Dependency graph coverage | >80% of actively-queried assets have ≥1 registration | The graph is comprehensive enough to trust |
| Inference precision | >90% of confirmed inferences are correct | Teams trust the suggestions |
| Time to first registration | <5 minutes after first scan | Low friction adoption |
| Impact analysis accuracy | Zero "surprise" breakages for assets with coverage | The coordination model works |
| Inferred → confirmed conversion rate | >60% | Inferences are useful, not noise |
