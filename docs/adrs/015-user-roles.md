# ADR-015: User Roles for Session-Based Access Control

**Status:** Accepted
**Date:** 2026-04 (retroactive)
**Author:** Evan Volgas

## Context

ADR-003 (Team Ownership Model) rejected RBAC as "premature," and ADR-008 (API Key Auth) stated "No RBAC beyond scope-based access." At the time, Tessera was API-only and all access was service-to-service via API keys with scoped permissions (read, write, admin).

As the platform grew to include a web UI with session-based login, team management pages, and admin operations (bootstrap users, system configuration), scope-based API key auth alone became insufficient. API keys are designed for programmatic access — they identify a service or automation, not a person. Human users logging into the web UI need identity-based access control that answers: "What can this person do?"

## Decision

Introduce a `UserRole` enum with three roles:

| Role | Access |
|------|--------|
| `ADMIN` | Full system access. Can manage all teams, users, assets, and system configuration. Bootstrap admin user is created from environment variables on startup. |
| `TEAM_ADMIN` | Can manage their own team's assets, members, and configurations. Cannot access other teams' admin operations or system-wide settings. |
| `USER` | Read access to all public data. Can manage their own registrations and notification preferences. |

### Interaction with API Key Scopes

Roles and scopes are complementary, not overlapping:

- **API key auth** (service-to-service): Continues to use scopes (`read`, `write`, `admin`). Roles are not checked. This is the path for CI/CD pipelines, SDK clients, and automated agents.
- **Session-based auth** (web UI): Uses roles. The session carries the authenticated user's identity and role. API key scopes are not involved.

A single request is authenticated by one mechanism or the other, never both. The auth middleware determines which path based on whether the request carries an API key header or a session cookie.

### Role Assignment

- Roles are set at user creation time and can be updated by an ADMIN.
- The bootstrap admin user (created from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars) is always assigned the `ADMIN` role.
- New users created via the API default to `USER` role unless explicitly set.

## Consequences

**Benefits:**
- Human users get appropriate access control for the web UI without needing personal API keys.
- Team admins can self-serve team management without requiring a system admin.
- The role set is minimal (3 roles) and maps to clear organizational boundaries.

**Costs:**
- Dual auth model adds complexity: developers must understand that scopes govern API keys and roles govern sessions.
- No per-resource permission granularity within a role. A `TEAM_ADMIN` can manage all of their team's assets — there's no "admin for asset X but not asset Y."
- If roles need to expand (e.g., `VIEWER` for read-only dashboards, `AUDITOR` for compliance), the enum must be extended and a migration run.

## Alternatives Considered

**Personal API keys with admin scope for web UI:** Would work technically but conflates two auth models. API keys are bearer tokens designed for programmatic use — storing them in session cookies creates confused deputy risks and makes revocation harder.

**Full RBAC with permissions matrix:** More flexible but premature. Three roles cover the current use cases. If we need fine-grained permissions later, we can layer them on top of roles without breaking the existing model.
