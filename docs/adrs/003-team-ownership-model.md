# ADR-003: Team-Based Ownership with Optional User Stewardship

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Data assets need clear ownership for coordination to work. When a breaking change is proposed, someone must be notified and empowered to approve or block it. The question is whether that "someone" is a person or a team.

People leave companies. They change roles. They go on vacation. If asset ownership is tied to a user, ownership becomes fragile. If tied to a team, it survives personnel changes.

## Decision

Every asset requires `owner_team_id` (not nullable). Every asset optionally has `owner_user_id` (nullable).

- **Teams** are the unit of organizational responsibility. Proposals notify the owning team. Impact analysis groups by team. Rate limiting is per-team.
- **Users** are optional stewards for accountability. When a user publishes a contract or acknowledges a proposal, their identity is recorded. But no workflow depends on a specific user existing.

This pattern extends to contracts, proposals, and API keys — all reference a team, optionally a user.

## Consequences

**Benefits:**
- Ownership is durable. Teams don't take PTO.
- Impact analysis produces team-level summaries, which maps to how organizations actually coordinate ("the analytics team needs to approve this").
- Users can be deactivated without orphaning assets.

**Costs:**
- Teams must be created before any assets. There's no "default team" or auto-creation.
- Team-level granularity can be too coarse. Two sub-teams within "data engineering" might want separate notification preferences. Mitigated by allowing multiple teams.

## Alternatives Considered

**User-only ownership:** Simpler model but fragile. Rejected because the coordination workflow requires a durable responsible party.

**Role-based ownership (RBAC):** Roles like "data steward" assigned to users. Rejected as premature — the current team + optional user model covers the need without the complexity of a role hierarchy.
