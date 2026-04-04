# Spec-009: Service Dependency Graph API

**Related ADR:** ADR-014 (Service Contract Pivot)
**Depends on:** Spec-006 (Repo and Service Registry), Spec-007 (OTEL Discovery)
**Status:** Draft
**Date:** 2026-04-02

## Overview

A read API that returns the service-to-service dependency graph for visualization in the React frontend. This is the data source for the dashboard's interactive dependency graph component.

The graph is derived from two sources:
1. **Declared dependencies** — `asset_dependencies` records linked to services via `assets.service_id`
2. **Observed dependencies** — OTEL-discovered edges (Spec-007) resolved to services

This spec does not create new data — it aggregates existing data into a graph-friendly format.

## API Endpoints

### `GET /api/v1/graph/services`

Returns the full service dependency graph.

**Query parameters:**
- `team_id` (UUID, optional) — filter to services owned by this team and their direct neighbors
- `min_confidence` (float, optional, default 0.0) — minimum confidence for OTEL edges
- `include_unregistered` (bool, optional, default false) — include OTEL-observed services not yet registered in Tessera

**Response (200 OK):**

```json
{
    "nodes": [
        {
            "id": "uuid",
            "name": "order-service",
            "repo_id": "uuid",
            "repo_name": "acme/order-service",
            "team_id": "uuid",
            "team_name": "Commerce",
            "asset_count": 12,
            "has_breaking_proposal": true,
            "last_synced_at": "2026-04-01T12:00:00Z",
            "sync_status": "ok"
        },
        {
            "id": "uuid",
            "name": "payment-service",
            "repo_id": "uuid",
            "repo_name": "acme/payment-service",
            "team_id": "uuid",
            "team_name": "Commerce",
            "asset_count": 6,
            "has_breaking_proposal": false,
            "last_synced_at": "2026-04-01T11:30:00Z",
            "sync_status": "ok"
        }
    ],
    "edges": [
        {
            "source": "uuid (order-service)",
            "target": "uuid (payment-service)",
            "dependency_type": "CONSUMES",
            "source_type": "otel",
            "confidence": 0.92,
            "call_count": 24511,
            "asset_level_edges": 3
        }
    ],
    "unregistered_services": [
        {
            "otel_name": "legacy-billing-api",
            "connected_to": ["order-service", "payment-service"],
            "total_call_count": 8200
        }
    ],
    "metadata": {
        "node_count": 10,
        "edge_count": 15,
        "teams": ["Commerce", "Platform", "Data"],
        "last_otel_sync": "2026-04-01T10:00:00Z"
    }
}
```

### Node fields

| Field | Source | Description |
|-------|--------|-------------|
| `id` | `services.id` | Service UUID |
| `name` | `services.name` | Service name |
| `repo_id`, `repo_name` | `services` → `repos` | Parent repo |
| `team_id`, `team_name` | `services` → `repos` → `teams` | Owning team (derived through repo) |
| `asset_count` | `COUNT(assets WHERE service_id)` | Number of assets |
| `has_breaking_proposal` | Subquery | Any pending proposal on this service's assets |
| `last_synced_at` | `repos.last_synced_at` (via service → repo) | Last successful repo sync |
| `sync_status` | Derived from repo | `"ok"`, `"error"`, `"never"`, `"stale"` |

### Edge fields

| Field | Source | Description |
|-------|--------|-------------|
| `source` | Service UUID | The service that depends on the target |
| `target` | Service UUID | The service being depended on |
| `dependency_type` | `asset_dependencies.dependency_type` | CONSUMES, REFERENCES, TRANSFORMS |
| `source_type` | `asset_dependencies.source` | `"manual"`, `"otel"`, `"inferred"` |
| `confidence` | `asset_dependencies.confidence` | For OTEL edges; NULL for manual |
| `call_count` | `asset_dependencies.call_count` | For OTEL edges |
| `asset_level_edges` | COUNT | Number of asset-to-asset edges that make up this service-level edge |

### Edge aggregation

Asset-level dependencies are aggregated to service-level:

```
order-service.rest.POST_/orders → payment-service.rest.POST_/payments  (CONSUMES)
order-service.rest.GET_/orders  → payment-service.rest.GET_/status     (CONSUMES)
order-service.grpc.ProcessOrder → payment-service.grpc.ChargeCard      (CONSUMES)
```

Becomes one service-level edge:

```
order-service → payment-service (CONSUMES, asset_level_edges: 3)
```

Aggregation rules:
- If multiple dependency types exist between two services, return one edge per type
- Confidence = max confidence across asset-level edges
- Call count = sum across asset-level edges

### `GET /api/v1/graph/services/{id}/neighborhood`

Returns a focused subgraph: the specified service, its direct upstream dependencies, and its direct downstream dependents. Useful for the service detail page.

**Response:** Same format as `/graph/services` but filtered to the 1-hop neighborhood.

### `GET /api/v1/graph/impact/{asset_id}`

Returns the subgraph of services affected by a potential change to the given asset. Highlights the impact propagation path.

**Query parameters:**
- `depth` (int, optional, default 3) — how many hops of transitive impact to show

**Response:**

```json
{
    "source_asset": {
        "id": "uuid",
        "fqn": "order-service.rest.POST_/orders",
        "service_name": "order-service"
    },
    "affected_services": [
        {
            "id": "uuid",
            "name": "shipping-service",
            "team_name": "Logistics",
            "depth": 1,
            "path": ["order-service", "shipping-service"]
        },
        {
            "id": "uuid",
            "name": "analytics-service",
            "team_name": "Data",
            "depth": 2,
            "path": ["order-service", "shipping-service", "analytics-service"]
        }
    ],
    "impact_edges": [
        {
            "source": "order-service",
            "target": "shipping-service",
            "depth": 1
        },
        {
            "source": "shipping-service",
            "target": "analytics-service",
            "depth": 2
        }
    ]
}
```

## Implementation

### Query strategy

The graph is small enough (tens to low hundreds of services) to load entirely and process in memory. No need for a graph database.

```python
async def build_service_graph(
    session: AsyncSession,
    team_id: UUID | None = None,
    min_confidence: float = 0.0,
) -> ServiceGraph:
    # 1. Load all services (or filtered by team + neighbors)
    # 2. Load all asset_dependencies WHERE source/target assets have service_id
    # 3. Aggregate asset-level edges to service-level
    # 4. Load pending proposals for breaking-proposal flag
    # 5. Return graph
```

Two queries:
1. Services with asset counts: `SELECT s.*, COUNT(a.id) FROM services s LEFT JOIN assets a ON a.service_id = s.id GROUP BY s.id`
2. Service-level edges: `SELECT DISTINCT a1.service_id as source, a2.service_id as target, d.dependency_type, d.source, MAX(d.confidence), SUM(d.call_count), COUNT(*) FROM asset_dependencies d JOIN assets a1 ON ... JOIN assets a2 ON ... WHERE a1.service_id IS NOT NULL AND a2.service_id IS NOT NULL GROUP BY ...`

### Caching

The graph changes infrequently (only on sync or OTEL discovery). Cache the response in Redis with a 60-second TTL. Invalidate on:
- Service created/deleted
- Asset dependency created/deleted
- OTEL sync completed

### Performance target

- <100ms for graphs with <100 services
- <500ms for graphs with <500 services
- If graphs exceed 500 services, the team filter becomes essential

## Acceptance Criteria

- [ ] `GET /graph/services` endpoint with full node/edge response
- [ ] Edge aggregation from asset-level to service-level
- [ ] Team filter narrows to team's services + direct neighbors
- [ ] Confidence filter excludes low-confidence OTEL edges
- [ ] Unregistered services section shows OTEL names not yet in Tessera
- [ ] `GET /graph/services/{id}/neighborhood` returns 1-hop subgraph
- [ ] `GET /graph/impact/{asset_id}` returns impact propagation subgraph
- [ ] Redis caching with invalidation
- [ ] Test: two services with asset-level dependencies → one aggregated edge
- [ ] Test: OTEL edge with confidence below threshold → excluded
- [ ] Test: service with pending breaking proposal → `has_breaking_proposal: true`
- [ ] Test: team filter returns team's services + neighbors only
- [ ] Test: impact graph traverses transitive dependencies up to depth
