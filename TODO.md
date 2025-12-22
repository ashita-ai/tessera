# TODO (Outstanding Work + Priority)

This is the actionable backlog derived from `MISSING_FEATURES.md`. It is written to be implementation-ready (what to do, where, and why).

## P0 — Must do (Security / correctness blockers)

- [x] **Fix authorization gaps (Issue #73)**
  - **Goal**: Require API keys + scopes on all endpoints; verify team-level authorization where applicable.
  - **Work**:
    - Add `Auth` + `RequireRead/RequireWrite/RequireAdmin` dependencies across read/write endpoints:
      - `src/tessera/api/proposals.py` (currently readable without auth)
      - `src/tessera/api/assets.py` (most reads currently open)
      - `src/tessera/api/contracts.py` (reads currently open)
      - `src/tessera/api/registrations.py` (create/update/delete currently open)
      - `src/tessera/api/sync.py` (likely should be write/admin)
      - `src/tessera/api/webhooks.py` (delivery inspection should be admin/read)
    - Add **resource-level authorization** (beyond scopes):
      - Producers should only mutate assets/contracts/proposals they own (owner team == auth.team_id), unless admin.
      - Consumers should only acknowledge on behalf of their own team (consumer_team_id == auth.team_id), unless admin.
      - Registrations: consumer_team_id must match auth.team_id (unless admin).
  - **DoD**: New tests with `AUTH_DISABLED=false` verify 401 (no key) and 403 (wrong scope/team) behavior for all endpoints.

- [x] **Rate limiting (Issue #72)**
  - **Goal**: Prevent brute force / abuse; return 429 with `Retry-After`.
  - **Work**:
    - Add middleware for per-API-key rate limiting (preferred) and/or per-IP.
    - Define sane defaults:
      - `Read` scope: 1000 req / 1 min
      - `Write` scope: 100 req / 1 min
      - `Admin` scope: 50 req / 1 min
      - Global (IP-based): 5000 req / 1 min
    - Add config knobs in `src/tessera/config.py`.
  - **Dependencies**: If using `slowapi`, update `pyproject.toml` accordingly.
  - **DoD**: Tests confirm 429 response when limits exceeded; headers include `Retry-After`.

- [x] **CORS production restrictions (Issue #76)**
  - **Goal**: Avoid permissive CORS in prod.
  - **Work**:
    - Make `cors_origins` environment-aware (allowlist only specified domains in prod).
    - Restrict `allow_methods` to `["GET", "POST", "PATCH", "DELETE"]` in prod (no `["*"]`).
    - Document recommended prod settings in README / deployment guide.
  - **DoD**: Prod config rejects non-allowlisted origins and non-standard methods.

- [x] **Input validation & sanitization (Issue #77)**
  - **Goal**: Prevent invalid identifiers and DoS-by-payload.
  - **Work**:
    - Add FQN validation in `src/tessera/models/asset.py` (pattern + length).
    - Enforce semver and bounds in `src/tessera/models/contract.py` (already has regex, add max length).
    - Add schema size limits (max bytes / max properties) for `schema` payloads.
    - Add team name constraints in `src/tessera/models/team.py`.
  - **DoD**: API returns 422 for oversized payloads or malformed identifiers.

## P1 — High (Performance + core product capabilities)

- [x] **Caching integration (Issue #74)**
  - **Goal**: Use existing Redis cache layer to reduce DB load.
  - **Work**:
    - Wire `src/tessera/services/cache.py` into hot read paths:
      - `GET /contracts/{id}` (TTL: 10m)
      - `POST /contracts/compare` and/or schema diff operations (TTL: 1h)
      - `GET /assets/search`, `GET /assets/{id}`, `GET /assets/{id}/contracts` (TTL: 5m)
    - Implement cache invalidation triggers:
      - `POST /assets/{id}/contracts` -> Invalidate asset & contract cache.
      - `PATCH /assets/{id}` -> Invalidate asset cache.
      - `PATCH /teams/{id}` -> Invalidate team cache.
    - Add tests that confirm cache hit paths are safe when Redis is absent.
  - **DoD**: Cache hits verified in logs/instrumentation; invalidation confirmed on mutation.

- [x] **Recursive impact analysis (Issue #99)**
  - **Goal**: Blast radius should traverse `AssetDependencyDB` downstream, not just direct registrations.
  - **Work**:
    - Extend `POST /assets/{id}/impact` to:
      - compute affected downstream assets (graph traversal)
      - include impacted teams from downstream registrations/contracts
      - provide depth/limits (Default: 5 levels; Max: 10) + cycle protection.
  - **DoD**: Tests verify impact analysis identifies assets 3+ levels deep and handles circular dependencies safely.

- [x] **Native environment support (Issue #98)**
  - **Goal**: Model `dev/staging/prod` explicitly instead of encoding in FQN.
  - **Work** (requires migrations):
    - Add `environment` field (likely on `AssetDB`; possibly on `ContractDB` too).
    - Add filtering in list/search endpoints.
    - Define “promotion” linkage (same logical asset across envs).
  - **DoD**: Same FQN can exist in multiple environments; filtering works in API.

- [x] **List registrations endpoint (Issue #106)**
  - **Goal**: Implement `GET /registrations` as described in spec with filters + pagination.
  - **Work**:
    - Add endpoint in `src/tessera/api/registrations.py`
    - Add tests + pagination behavior.
  - **DoD**: API supports filtering by consumer team, contract, and status.

## P2 — Medium (DX / compliance / roadmap)

- [x] **Audit trail query API (Issue #90)**
  - **Goal**: Make `audit.events` queryable.
  - **Work**:
    - Create `src/tessera/api/audit.py` with list/get endpoints.
    - Support filters: `entity_type`, `entity_id`, `action`, `actor_id`, `from` (ISO date), `to` (ISO date).
    - Add router in `src/tessera/main.py`.
    - Add tests.
  - **DoD**: Comprehensive tests in `tests/test_audit.py` covering all filter combinations and pagination.

- [x] **Soft deletes (Issue #100)**
  - **Goal**: Avoid hard deletes; preserve audit history and references.
  - **Work** (requires migrations):
    - Add `deleted_at` to `TeamDB`, `AssetDB` (and any other externally referenced entity).
    - Update queries to exclude deleted entities by default.
    - Add `POST /{entity}/{id}/restore` endpoint (admin only).
    - Clarify: Purge (hard delete) behavior is out of scope for now.
  - **DoD**: Deleting an entity returns 404 on subsequent GETs but record remains in DB with `deleted_at` set.

- [x] **Teams PUT vs PATCH (Issue #107)**
  - **Goal**: Provide `PUT /teams/{id}` or update spec/docs to reflect PATCH.
  - **Work**:
    - Either add `PUT` alias to existing patch behavior, or align docs/spec.

## Notes on current status vs this list

- **All items in this implementation-ready backlog have been completed.** This includes core security (auth, rate limiting, CORS, validation), performance (caching), and key product features (recursive impact, environment support, registrations list, audit API, and soft deletes).


