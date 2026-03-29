# ADR-012: Semantic Versioning with Dual Parsing and Three Enforcement Modes

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Contract versions must be meaningful. A version bump from 1.2.0 to 2.0.0 should signal a breaking change. A bump to 1.3.0 should signal a backward-compatible addition. If versioning is arbitrary, consumers can't use version numbers to assess risk.

At the same time, version enforcement has different appropriate levels depending on context. A CI pipeline should auto-version without human intervention. A manual publish should suggest a version but let the producer override. An organization with strict governance should enforce that the version matches the detected change level.

## Decision

### Version Detection

The schema diff engine classifies changes into semver components:
- **Major bump:** Breaking changes detected (under the asset's compatibility mode).
- **Minor bump:** Non-breaking additions (new properties, new enum values).
- **Patch bump:** No schema changes (metadata-only updates, guarantee changes).

Pre-release suffixes (alpha, beta, rc) are supported and compared according to semver precedence rules.

### Enforcement Modes

| Mode | Behavior |
|------|----------|
| `AUTO` | System determines the version. Producer doesn't provide one. Used by sync endpoints (dbt, OpenAPI, etc.) for hands-off automation. |
| `SUGGEST` | System suggests a version. Producer can accept or override. Used by CLI and SDK for interactive workflows. |
| `ENFORCE` | Producer provides a version. System validates it matches the detected change level. Used by organizations with strict governance. |

### Dual Parsing Functions

Two parsing functions in `services/versioning.py`:

- **`parse_semver(version: str) → tuple[int, int, int]`** — Strict. Raises `ValueError` on malformed input. Used when validating user-provided versions (API endpoints, ENFORCE mode).
- **`parse_semver_lenient(version: str) → tuple[int, int, int]`** — Returns `(1, 0, 0)` on failure. Used when processing stored versions that may predate validation (bulk publishing, version comparison).

All version logic is consolidated in one module. No other module implements its own parsing.

## Consequences

**Benefits:**
- Version numbers are semantically meaningful. A major bump always means a breaking change.
- Three modes support different governance levels without forcing one approach.
- Lenient parsing prevents crashes on legacy data while strict parsing catches errors at the API boundary.

**Costs:**
- Two parsing functions create a subtle footgun. Using the wrong one in the wrong context either crashes on valid legacy data or silently accepts garbage.
- `SUGGEST` mode allows producers to override the system's suggestion, which means versions can be misleading if the override is incorrect. No guardrails beyond the `ENFORCE` mode.
- Consolidated module is a single point of failure for all versioning logic. Mitigated by thorough test coverage.
