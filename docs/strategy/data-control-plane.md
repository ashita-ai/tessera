# Data Control Plane Pivot

**Status:** Draft
**Date:** 2026-03-29
**Author:** Evan Volgas

## The Argument

Compute has Kubernetes. Networking has service meshes. Storage has S3 lifecycle policies. Data has nothing.

There is no system that manages the lifecycle, interfaces, and dependencies of data assets across an organization. Catalogs describe what exists (Atlan, DataHub, Collibra). Quality tools check what arrived (Monte Carlo, Soda, Great Expectations). Observability tools detect when things broke (Monte Carlo, Bigeye). None of them coordinate change. None of them manage the operational relationship between producers and consumers.

"Data contract coordination" describes what Tessera does. "Data control plane" describes what Tessera is becoming. The distinction matters because:

- **"Data contracts"** sounds like a governance obligation. It connotes compliance, process, overhead. The buyer is a data governance lead who needs to check a box.
- **"Data control plane"** sounds like infrastructure. It connotes reliability, automation, operational intelligence. The buyer is a platform engineering lead who needs to keep things running.

Same product. Different frame. Different buyer. Different market size.

---

## What Is a Data Control Plane?

By analogy to Kubernetes (the compute control plane):

| Kubernetes | Data Control Plane | Tessera Today |
|------------|-------------------|---------------|
| Knows what pods exist | Knows what data assets exist | Assets with FQN, type, team ownership |
| Knows pod health (liveness/readiness) | Knows data freshness and quality | Preflight checks, audit runs, guarantees |
| Knows who depends on what (services → pods) | Knows who consumes what data | Registrations, dependency graph |
| Manages rollout of changes (rolling update) | Manages rollout of schema changes | Proposal-acknowledgment workflow |
| Detects breaking changes (failed health check → rollback) | Detects breaking schema changes | Schema diff engine, compatibility modes |
| Tracks who changed what (audit log) | Tracks who published what | Audit trail with actor_type |
| Exposes an API for all operations | Exposes an API for all operations | 30+ REST endpoints, CLI, SDK |
| Has a control loop (desired state → actual state) | Has a control loop (contract → actual schema) | WAP gate, BigQuery connector validation |

Tessera already implements most of these primitives. What's missing is the operational intelligence layer — the part that observes the actual state of the data ecosystem and reconciles it with the declared state.

---

## What Tessera Already Has (Control Plane Primitives)

### Asset Registry (What Exists)
- Assets with FQN, resource type, environment, team ownership, tags
- Multi-format schema support (JSON Schema, Avro, OpenAPI, GraphQL, gRPC)
- Search by FQN, tag, team, resource type
- Soft-delete lifecycle

### Interface Contracts (What's Promised)
- Schema contracts with semantic versioning
- Data quality guarantees (not-null, unique, accepted_values, freshness, volume)
- Compatibility modes (backward, forward, full, none)
- Field-level semantic metadata (descriptions, tags, PII labels)

### Dependency Graph (Who Depends on What)
- Consumer registrations with dependency types (CONSUMES, REFERENCES, TRANSFORMS)
- dbt-inferred dependencies from manifest sync
- Impact analysis with recursive graph traversal
- Pinned versions for consumers not ready to upgrade

### Change Coordination (How Changes Propagate)
- Three-path publishing (first/compatible/breaking)
- Proposal-acknowledgment workflow with state machine
- Force publish with audit trail
- Migration suggestions for breaking changes
- Webhook notifications with HMAC signing

### Operational Visibility (What Happened)
- Append-only audit trail with actor_type (human/agent)
- Audit runs tracking data quality test results
- Preflight endpoint for consumption-time checks
- Prometheus metrics for monitoring

### Identity & Access (Who Can Do What)
- API keys with scopes (READ, WRITE, ADMIN)
- Agent identity (name, framework) with separate rate limiting
- Team-based ownership model

---

## What's Missing (The Gap to Control Plane)

### 1. Observability of Actual State

Tessera knows the declared state (contracts, registrations) but not the actual state (what's really happening in the warehouse). The gap:

| Question | Can Tessera answer it today? |
|----------|------------------------------|
| What schema does this table actually have right now? | Partially (BigQuery connector can fetch, but not automatically) |
| Is this contract's schema in sync with the actual table? | Only via manual BigQuery connector call |
| Who actually queries this table? | No (see [Passive Discovery](passive-discovery.md)) |
| Which columns are actually used? | No |
| When was this table last updated? | Only if freshness guarantee is configured and audited |
| Is this table growing normally? | No (volume anomaly detection doesn't exist) |

A control plane must reconcile declared state with actual state. Tessera currently trusts declarations. That's governance. A control plane verifies.

**What to build:** Scheduled reconciliation that fetches actual schemas from warehouses and compares them to the active contract. Drift detection: "the `orders` table in Snowflake has a column `discount_code` that doesn't exist in the contract." This is the data equivalent of Kubernetes detecting a pod that doesn't match its deployment spec.

### 2. Passive Discovery

Covered in detail in [Passive Discovery](passive-discovery.md). In the control plane frame: a control plane that only knows about explicitly registered dependencies is like Kubernetes only knowing about pods you manually tell it about. The system must discover what exists.

### 3. Automated Remediation

Tessera detects breaking changes and coordinates human/agent acknowledgment. But it doesn't fix anything automatically.

Control plane behavior would be:
- **Drift detected** (schema in warehouse doesn't match contract) → auto-publish a new contract version capturing the drift, notify consumers.
- **Freshness SLA violated** → surface in preflight, optionally trigger a webhook to the producing team's alerting system.
- **Unused columns detected** (from passive discovery) → suggest deprecation to the producer. After N days with zero queries, auto-deprecate.
- **Consumer query pattern changed** → update column-level dependencies automatically.

This is the difference between a passive coordination tool (wait for humans to publish) and an active control plane (detect, react, reconcile).

### 4. Policy Engine

Acknowledgment policies (from the [Agent Opportunity](agent-opportunity.md) doc) generalize into a broader policy engine:

- **Acknowledgment policies:** "Auto-approve proposals that only add nullable columns."
- **Publishing policies:** "Block any contract that removes a not-null guarantee on a P1 asset."
- **Discovery policies:** "Auto-confirm inferred dependencies with confidence > 0.9 for this team."
- **Freshness policies:** "If `orders` is staler than 2 hours, mark preflight as `fresh: false`."
- **Deprecation policies:** "If a column hasn't been queried in 90 days, flag for deprecation."

Policies are declarative rules that the control plane evaluates continuously. They replace manual decisions with automated ones, which is exactly what makes a control plane a control plane rather than a dashboard.

### 5. Federation

A single Tessera instance covers one deployment. Large organizations have multiple data platforms (Snowflake + BigQuery, production + analytics warehouse, US + EU). A control plane needs to span these.

Federation means: multiple Tessera instances that share a dependency graph. An asset in Instance A can register a dependency on an asset in Instance B. A breaking change in Instance B creates a proposal visible in Instance A.

This is a later-stage feature but it's architecturally significant. The current single-instance model should be designed to not preclude federation.

---

## The Pivot Path

This is not a big-bang repositioning. It's a gradual expansion of scope, where each step adds a control plane capability and the messaging shifts to match.

### Stage 1: Coordination Tool (Today — v0.2)

**What it is:** Schema change coordination between teams.
**Messaging:** "Data contract coordination for warehouses."
**Buyer:** Data engineering leads who feel the pain of uncoordinated schema changes.
**What proves it works:** Teams using the proposal workflow. Breaking changes caught before deployment.

### Stage 2: Coordination + Intelligence (Next — v0.3)

**What to add:**
- Preflight-to-inference pipeline (passive discovery Phase 1)
- Coverage report (graph completeness visibility)
- MCP server (agent distribution)
- Dependency graph unification

**Messaging shift:** "Data contract coordination with dependency intelligence."
**Buyer:** Same, but now platform engineering is interested because of the coverage report and agent integration.
**What proves it works:** Dependency graph coverage >60% on deployed instances. Agents connecting via MCP.

### Stage 3: Intelligence + Observability (Later — v0.4)

**What to add:**
- Warehouse connector for schema drift detection (Snowflake first)
- Passive discovery from query logs
- Column-level dependency tracking
- Reconciliation loop (declared vs actual schema)

**Messaging shift:** "The data control plane — know what you have, who depends on it, and what's changing."
**Buyer:** Platform engineering leads. The pitch is no longer "coordinate schema changes" but "operational visibility and control over your data ecosystem."
**What proves it works:** Schema drift detection catches real discrepancies. Impact analysis uses column-level dependencies from query logs.

### Stage 4: Full Control Plane (v1.0)

**What to add:**
- Policy engine (acknowledgment, publishing, discovery, deprecation policies)
- Automated remediation (drift → auto-publish, stale → alert, unused → deprecate)
- Additional warehouse connectors (BigQuery, Databricks, Redshift)
- Federation between instances

**Messaging:** "The control plane for your data ecosystem."
**Buyer:** VP of Data / Head of Platform Engineering. The pitch is: "You have Kubernetes for compute, Terraform for infrastructure, Tessera for data."
**What proves it works:** Organizations running Tessera as infrastructure (always-on, multiple teams, policy-driven) rather than a tool (used occasionally for specific changes).

---

## What Not to Do

### Don't Build a Catalog

Catalogs (Atlan, DataHub, Collibra) are well-funded, well-established, and have large engineering teams. Tessera should not try to replace them. The differentiation is:

- Catalogs answer: "What data do we have?"
- Tessera answers: "What happens when this data changes?"

These are complementary, not competitive. Tessera should integrate with catalogs (push contract metadata to DataHub, pull asset descriptions from Atlan) rather than replace them.

### Don't Build a Data Quality Tool

Monte Carlo, Soda, and Great Expectations own data quality monitoring. Tessera tracks quality guarantees and gates publishing on audit results — it doesn't run the audits. The `triggered_by` field on `AuditRunDB` reflects this: Tessera receives results from dbt tests, GX checkpoints, or Soda scans. It doesn't compete with them.

### Don't Build a Lineage Visualizer

Lineage visualization is a catalog feature. Tessera has lineage data (the dependency graph), and it should expose this data via API for other tools to visualize. But building a lineage UI is a distraction from the control plane mission.

### Don't Generalize Beyond Data (Yet)

The panel discussion surfaced the idea that Tessera's coordination model could apply to any schema-bearing interface (APIs, ML models, event streams). This is true in principle but dangerous in practice. Generalizing prematurely diffuses focus. Win data first. The generalization is a reward, not a strategy.

---

## Competitive Implications

### Against Catalogs (Atlan, DataHub, Collibra)

**Position:** "Catalogs describe. Tessera coordinates." Tessera is not a replacement for a catalog — it's the operational layer that catalogs don't provide. Integrate, don't compete. The ideal outcome is that Atlan/DataHub users also run Tessera for change management.

### Against Data Quality (Monte Carlo, Soda)

**Position:** "Quality tools detect failures after the fact. Tessera prevents them before deployment." Monte Carlo tells you your dashboard broke. Tessera prevents the schema change that would have broken it.

### Against dbt

**Position:** "dbt transforms data. Tessera coordinates the interfaces between transforms." Tessera is dbt's coordination layer, not its competitor. The dbt integration is the most important wedge. The risk (dbt builds native coordination) is mitigated by Tessera's cross-system support.

### Against Schema Registries (Confluent)

**Position:** "Schema registries handle one transport (Kafka). Tessera handles the whole ecosystem." A single data org has warehouse tables, REST APIs, event streams, and GraphQL endpoints. A schema registry covers one of these. Tessera covers all of them.

---

## The Portfolio Case

For Tessera as a portfolio piece, the control plane framing elevates the project from "a useful tool" to "a system design achievement."

What evaluators should notice:
1. **The primitive model is complete.** Assets, contracts, registrations, proposals, acknowledgments, audit events — these are the right primitives for a data control plane, analogous to pods, services, deployments, and events in Kubernetes.
2. **The coordination workflow is novel.** No other open-source tool implements proposal-acknowledgment for data schema changes. This is a genuinely new design pattern.
3. **The architecture anticipates scale.** Async-first, separate rate limiting for agents, circuit breakers on webhooks, bounded queues, recursive graph traversal with depth limits — these are production concerns, not prototype concerns.
4. **The agent integration is forward-looking.** Agent identity, preflight checks, semantic metadata, and MCP readiness position the project at the intersection of two trends (data governance + AI agents) before the market has converged.
5. **The ADR trail documents reasoning.** 13 ADRs explaining not just what was built but why, with alternatives considered and tradeoffs acknowledged. This is how staff engineers think.

The control plane frame makes these qualities visible to someone evaluating the project in 30 minutes.

---

## Success Criteria for the Pivot

The pivot is working when:

| Signal | Meaning |
|--------|---------|
| Users describe Tessera as "infrastructure" not "a tool" | It's perceived as always-on, not occasionally-used |
| Platform engineering teams adopt it (not just data engineering) | The buyer has expanded beyond the original niche |
| Dependency graph coverage exceeds 80% on deployed instances | Passive discovery is working; the graph is trusted |
| Agent traffic exceeds 30% of total API calls | Agents are first-class participants, not an afterthought |
| At least 3 warehouse connectors in production use | Cross-system coverage is real, not just dbt |
| Policy engine handles >50% of acknowledgments automatically | Automation has replaced manual coordination for routine changes |

None of these require abandoning the current product. Each is an incremental addition that shifts the value proposition from coordination tool to control plane. The code doesn't pivot. The framing does.
