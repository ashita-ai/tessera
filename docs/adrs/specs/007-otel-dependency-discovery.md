# Spec-007: OTEL-Based Dependency Discovery

**Related ADR:** ADR-014 (Service Contract Pivot), Phase 2
**Depends on:** Spec-006 (Repo and Service Registry)
**Status:** Not Yet Implemented
**Date:** 2026-04-02

## Overview

Automatically discover service-to-service dependencies by querying OpenTelemetry trace data from an observability backend. Instead of requiring teams to manually register consumer dependencies, Tessera observes which services actually call each other and creates dependency records with confidence scores.

## Problem

Manual dependency registration is the biggest adoption barrier. Teams don't know all their dependencies, registrations go stale, and new dependencies appear without anyone updating the registry. The result: when a breaking change happens, Tessera can't notify all affected consumers because it doesn't know about them.

OTEL traces already contain this information. Every instrumented HTTP/gRPC call generates a span with `service.name` on both the client and server side. The call graph is there — Tessera just needs to read it.

## Architecture

```
OTEL Collector ──► Jaeger/Tempo ◄── Tessera (query API)
                                         │
                                         ▼
                                  AssetDependencyDB
                                  (source: "otel", confidence: 0.85)
```

Tessera does **not** receive raw spans. It queries a trace backend's aggregation API periodically to extract service dependency edges.

### Why query, not ingest

- No need to handle span volume (millions/sec) — the backend already does this
- No storage duplication — traces stay in Jaeger/Tempo/Datadog
- Simpler deployment — no collector pipeline changes
- The dependency graph is a derivative of traces, not the traces themselves

## Supported Backends

### Phase 1: Jaeger

Jaeger exposes a dependency API:

```
GET /api/dependencies?endTs={unix_ms}&lookback={duration_ms}
```

Response:
```json
[
  { "parent": "order-service", "child": "payment-service", "callCount": 4521 },
  { "parent": "order-service", "child": "user-service", "callCount": 12034 }
]
```

This is the simplest integration point. One HTTP call returns the full dependency graph.

### Phase 2 (future): Grafana Tempo

Tempo's metrics-generator can produce `traces_service_graph_request_total` Prometheus metrics. Tessera can query Prometheus for these.

### Phase 3 (future): Datadog

Datadog's Service Map API returns a similar dependency structure.

## Data Model

### New table: `otel_sync_configs`

```sql
CREATE TABLE otel_sync_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200) NOT NULL,
    backend_type    VARCHAR(50) NOT NULL,  -- 'jaeger', 'tempo', 'datadog'
    endpoint_url    VARCHAR(500) NOT NULL, -- e.g., http://jaeger:16686
    auth_header     VARCHAR(500),          -- optional auth
    lookback_seconds INTEGER NOT NULL DEFAULT 86400,  -- 24h
    poll_interval_seconds INTEGER NOT NULL DEFAULT 3600,  -- 1h
    min_call_count  INTEGER NOT NULL DEFAULT 10,       -- ignore edges below this
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at  TIMESTAMPTZ,
    last_sync_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Modified table: `asset_dependencies`

The existing `asset_dependencies` table already has the fields needed. We add:

```sql
ALTER TABLE asset_dependencies ADD COLUMN source VARCHAR(50) NOT NULL DEFAULT 'manual';
-- source: 'manual' | 'otel' | 'inferred'

ALTER TABLE asset_dependencies ADD COLUMN confidence FLOAT;
-- 0.0-1.0, NULL for manual registrations

ALTER TABLE asset_dependencies ADD COLUMN last_observed_at TIMESTAMPTZ;
-- when OTEL last saw this edge

ALTER TABLE asset_dependencies ADD COLUMN call_count INTEGER;
-- observed call count in the lookback window
```

## API Endpoints

### `POST /api/v1/otel/configs`

Register an OTEL backend.

```json
{
    "name": "production-jaeger",
    "backend_type": "jaeger",
    "endpoint_url": "http://jaeger-query:16686",
    "lookback_seconds": 86400,
    "poll_interval_seconds": 3600,
    "min_call_count": 10
}
```

### `GET /api/v1/otel/configs`

List configured backends.

### `POST /api/v1/otel/configs/{id}/sync`

Trigger immediate dependency discovery. Returns `202 Accepted`.

### `GET /api/v1/otel/dependencies`

List OTEL-discovered dependencies. Supports filters:
- `?service_name=str` — filter by source or target service
- `?min_confidence=float` — filter by confidence threshold
- `?stale=true` — show dependencies not observed in last sync

### `GET /api/v1/dependencies/reconciliation`

Compare declared (manual) dependencies against observed (OTEL) dependencies. Returns:

```json
{
    "declared_only": [
        {
            "dependency": { "source": "order-service", "target": "legacy-api" },
            "status": "possibly_stale",
            "note": "Not observed in OTEL traces in last 7 days"
        }
    ],
    "observed_only": [
        {
            "dependency": { "source": "analytics-service", "target": "user-service" },
            "status": "undeclared",
            "call_count": 8432,
            "confidence": 0.91,
            "note": "Observed in traces but no explicit registration exists"
        }
    ],
    "both": [
        {
            "dependency": { "source": "order-service", "target": "payment-service" },
            "status": "confirmed",
            "call_count": 24511,
            "confidence": 0.98
        }
    ]
}
```

This is the key insight endpoint — it shows teams what they're missing and what might be stale.

## Discovery Algorithm

### Step 1: Fetch edges from backend

```python
async def fetch_jaeger_dependencies(config: OtelSyncConfig) -> list[ServiceEdge]:
    url = f"{config.endpoint_url}/api/dependencies"
    params = {
        "endTs": int(time.time() * 1000),
        "lookback": config.lookback_seconds * 1000,
    }
    response = await httpx.get(url, params=params, headers=auth_headers(config))
    return [
        ServiceEdge(parent=dep["parent"], child=dep["child"], call_count=dep["callCount"])
        for dep in response.json()
    ]
```

### Step 2: Resolve service names to Tessera services

For each edge `(parent_name, child_name)`:

1. Look up `parent_name` in `services.otel_service_name` (service belongs to a repo, which belongs to a team — the full hierarchy is available)
2. Look up `child_name` in `services.otel_service_name`
3. If both resolve → create/update dependency
4. If one doesn't resolve → log as "unregistered service" (visible in reconciliation endpoint)

Note: The `services` table is joined through `repos` to get team ownership. An OTEL edge between two services implicitly tells you which teams are coupled.

### Step 3: Compute confidence

Confidence is a function of:
- **Call count**: higher count → higher confidence (logarithmic scale)
- **Consistency**: seen in N of last M syncs → higher confidence
- **Recency**: last observed recently → higher confidence

```python
def compute_confidence(call_count: int, syncs_seen: int, total_syncs: int) -> float:
    count_score = min(math.log10(max(call_count, 1)) / 4, 1.0)  # 10k calls = 1.0
    consistency_score = syncs_seen / max(total_syncs, 1)
    return round(0.6 * count_score + 0.4 * consistency_score, 2)
```

### Step 4: Upsert dependencies

For each resolved edge:
- If dependency exists with `source='otel'`: update `call_count`, `last_observed_at`, `confidence`
- If dependency exists with `source='manual'`: don't overwrite, but update `last_observed_at` (confirms the manual registration)
- If no dependency exists: create with `source='otel'`

### Step 5: Mark stale

Dependencies with `source='otel'` where `last_observed_at < now() - 3 * lookback_seconds` are marked with a low confidence score. They are not deleted — stale dependencies are visible in the reconciliation endpoint.

## Background Worker

Runs alongside the service registry worker:

1. Query all `otel_sync_configs` where `enabled = TRUE` and `last_synced_at < now() - poll_interval_seconds`
2. For each, run the discovery algorithm
3. On error: set `last_sync_error`, do not update `last_synced_at`
4. Audit event: `OTEL_SYNC_COMPLETED` with edge count

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERA_OTEL_ENABLED` | `false` | Enable OTEL dependency discovery |
| `TESSERA_OTEL_POLL_INTERVAL` | `3600` | Default poll interval (seconds) |
| `TESSERA_OTEL_MIN_CONFIDENCE` | `0.3` | Minimum confidence to create a dependency |
| `TESSERA_OTEL_STALE_MULTIPLIER` | `3` | Mark stale after N * lookback without observation |

## Security

- `endpoint_url` validated: must be HTTP/HTTPS, no file:// or other schemes
- `auth_header` stored encrypted (if configured)
- SSRF protection: validate against internal network allowlist (reuse webhook SSRF logic)
- Rate limit: max 1 sync per config per 5 minutes

## Acceptance Criteria

- [ ] `OtelSyncConfigDB` model and migration
- [ ] `asset_dependencies` schema additions (source, confidence, last_observed_at, call_count)
- [ ] Jaeger backend client
- [ ] CRUD endpoints for OTEL configs
- [ ] Manual sync trigger
- [ ] Background polling worker
- [ ] Service name → Tessera service resolution
- [ ] Confidence scoring
- [ ] Dependency upsert (create, update, mark stale)
- [ ] Reconciliation endpoint (declared vs observed)
- [ ] Audit events for OTEL syncs
- [ ] Test: mock Jaeger API → verify dependencies created
- [ ] Test: confidence scoring with varying call counts
- [ ] Test: stale dependency detection
- [ ] Test: reconciliation shows declared-only, observed-only, and confirmed
- [ ] Test: unregistered services logged but don't create broken references
- [ ] Test: SSRF protection on endpoint URL
