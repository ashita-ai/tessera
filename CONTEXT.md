# Context

Strategic context for Tessera development.

## Differentiators

- **Coordination, not validation.** Existing tools tell you something is wrong. Tessera tells you what to do about it—who to notify, who must acknowledge, what the migration path is.
- **Producer/consumer protocol.** Schema registries solved this for Kafka. Warehouses have nothing equivalent. This is the gap.
- **The dependency graph.** Once teams register, the graph becomes the moat. Ownership, dependencies, impact analysis—all queryable.

## Hard Questions

1. **Who registers first?** Producers create assets. Consumers need protection. Neither has incentive to move first without the other.
2. **What happens when Tessera is wrong?** A "safe" change that breaks production. How does trust recover?
3. **Can coordination feel like acceleration?** Every step is friction. If it feels like bureaucracy, teams will route around it.
4. **Where do you go deep?** dbt? Snowflake? Temporal? Picking one loses others. Not picking loses all.

## Resolved

- **Auth model**: API keys per team with read/write/admin scopes. Bootstrap key for initial setup. Development mode for local testing.

## Risks

- **Cold start.** Network effects require density. A registry with three assets is useless.
- **Governance trap.** Explicit contracts can calcify systems. If changing a contract is painful, shadow pipelines emerge.
- **Platform risk.** If Snowflake or dbt builds this natively, Tessera becomes a feature, not a product.
- **Incentive asymmetry.** Producers bear the cost (registration, proposals, waiting). Consumers get the value (protection).
- **Classification errors.** "Backward compatible" is a judgment call. Conservative = slow. Permissive = blamed for outages.

## Vital to Get Right

- **Friction budget.** Breaking changes need coordination. Everything else must flow through untouched. If 90% of changes are frictionless, the 10% feel like protection.
- **First integration.** dbt manifest.json can seed the graph automatically. Zero-friction onboarding for the first producer.
- **Failure modes.** Build so failures are informative. If it doesn't work, know why—wrong abstraction, wrong buyer, wrong ecosystem.
- **The 3am story.** Marketing must center on the avoided incident, not the feature set. Find the frustrated early adopter. Let them tell the story.
