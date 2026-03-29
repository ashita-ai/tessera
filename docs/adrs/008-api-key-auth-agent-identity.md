# ADR-008: API Key Authentication with Agent Identity

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Tessera serves two distinct client types: human users (via CLI, SDK, or UI) and AI agents (via SDK or direct API calls). Both need authentication. Both need rate limiting. But they have different usage patterns and different accountability requirements.

A human makes 10 requests investigating an impact analysis. An agent might make 1,000 requests publishing contracts from a CI pipeline. The rate limiter needs to know the difference. The audit trail needs to know which agent made which change.

## Decision

### API Key Model

API keys have three scopes: `READ`, `WRITE`, `ADMIN`. Admin is a superset — it short-circuits all scope checks.

Keys are hashed with Argon2 before storage (only the prefix is stored in plaintext for identification). Keys have optional expiration dates and can be revoked.

### Agent Identity

API keys optionally carry `agent_name` (e.g., "dbt-ci-publisher") and `agent_framework` (e.g., "langchain", "crewai"). These fields are:
- Recorded in the audit trail alongside every action the key performs.
- Used to select rate limit tiers (agent vs human).
- Queryable for understanding agent behavior patterns.

### Rate Limiting Tiers

Three layers:
1. **Per-key:** Each API key has its own rate limit bucket.
2. **Per-team:** All keys for a team share a bucket, preventing limit bypass via multiple keys.
3. **Agent-aware:** Separate thresholds for human and agent clients. Configurable independently.

The rate limiter identifies client type from a `"agent:"` or `"human:"` prefix on the rate limit key, avoiding a database lookup on every request.

## Consequences

**Benefits:**
- Agent actions are distinguishable from human actions in the audit trail.
- Rate limits can be tuned independently — agents can be throttled harder (or given more headroom) without affecting human users.
- No separate "agent account" model needed. Agent identity is metadata on the key, not a new entity.

**Costs:**
- Agent identity is optional. If omitted, the key is assumed human. This means unidentified agents consume human rate limit budgets and appear as human in audits.
- No RBAC beyond scope-based access. A WRITE key can write to any asset, not just assets owned by the key's team. Mitigated by team ownership checks in business logic.
- In-memory rate limiting (via `slowapi`) doesn't share state across workers. A multi-worker deployment has per-worker limits, not global limits.

## Alternatives Considered

**OAuth2 / JWT tokens:** More standard but heavier. Rejected because Tessera doesn't need the complexity of token refresh flows or third-party identity providers at this stage.

**Separate agent model in the database:** A dedicated `AgentDB` table with its own identity. Rejected as over-engineering — agent identity as key metadata is simpler and sufficient for current needs.

**Centralized rate limiting (Redis):** Share rate limit state across workers via Redis. Deferred — Redis is optional in Tessera, and per-worker limits are acceptable at current scale.
