# Tessera Strategy

Working documents for strategic analysis and planning.

## Documents

| Document | Status | Topic |
|----------|--------|-------|
| [Agent Opportunity](agent-opportunity.md) | Draft | AI agents as first-class data consumers and producers |
| [Data Control Plane Pivot](data-control-plane.md) | Draft | Reframing from "data contracts" to "data control plane" |
| [Passive Discovery](passive-discovery.md) | Draft | Automatic dependency detection from query logs and lineage |

## How These Connect

The three documents form a coherent strategic picture:

1. **Passive discovery** solves the cold-start problem that limits Tessera's current value. Without a complete dependency graph, coordination is unreliable.
2. **Agent opportunity** expands the user base from human data teams to AI agents — the fastest-growing consumer category. Passive discovery makes agent registration automatic (via preflight audit conversion).
3. **Data control plane** reframes the product from a coordination tool to infrastructure. Passive discovery provides the observability layer. Agent integration provides the automation layer. Together they justify the "control plane" positioning.

Build order: passive discovery (Phase 1: preflight inference) → MCP server → warehouse connectors → policy engine → control plane messaging.
