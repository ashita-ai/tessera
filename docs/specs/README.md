# Tessera Specs

Technical specifications for planned features. These implement the strategy outlined in [`docs/strategy/`](../strategy/).

Distinct from the implementation specs under `docs/adrs/specs/` which are tied to ADR-001 (AI enablement) and several of which are already implemented.

## Specs

| Spec | Status | Strategy | Effort | Description |
|------|--------|----------|--------|-------------|
| [001 Preflight Inference Pipeline](001-preflight-inference-pipeline.md) | Draft | [Passive Discovery](../strategy/passive-discovery.md) Phase 1 | 1-2 weeks | Mine audit trail for dependency signals. Zero new infrastructure. |
| [002 Dependency Graph Unification](002-dependency-graph-unification.md) | Draft | [Passive Discovery](../strategy/passive-discovery.md) Phase 3 | 2-3 weeks | Single source of truth for asset-to-asset edges. Prerequisite for warehouse connectors. |
| [003 MCP Resources](003-mcp-resources.md) | Draft | [Agent Opportunity](../strategy/agent-opportunity.md) | 1 week | Subscribable schema/guarantee/proposal resources for agents. Extends MCP tool server. |

## Build Order

```
Spec 001 (preflight inference)  ─────────────────────────────────┐
                                                                  ├──► warehouse connectors (future spec)
Spec 002 (graph unification)    ─────────────────────────────────┘

ADR-001/Spec 005 (MCP tools)    ──► Spec 003 (MCP resources)     ──► acknowledgment policies (future spec)
```

Specs 001 and 002 can be built in parallel. Spec 003 depends on the MCP tool server (ADR-001/Spec 005) being built first.
