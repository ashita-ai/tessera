# Spec-006: Repo and Service Registry with Repo-Based Discovery

**Related ADR:** ADR-014 (Service Contract Pivot), Phase 1
**Status:** Draft
**Date:** 2026-04-02 (updated 2026-04-03)

## Overview

Add `Repo` and `Service` entities that establish the hierarchy `Team → Repo → Service → Asset → Contract`. Repos are git repositories where API specs live. Services are deployable units within repos. Tessera pulls specs from repos, discovers services, and runs the existing sync logic to create and update contracts automatically.

## Data Model

### New table: `repos`

A repo is a git repository owned by a team. It's the unit of git operations (clone, fetch, poll) and CODEOWNERS parsing.

```sql
CREATE TABLE repos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200) NOT NULL,         -- human-readable (e.g., "order-service", "platform-monorepo")
    owner_team_id   UUID NOT NULL REFERENCES teams(id),
    git_url         VARCHAR(500) NOT NULL,         -- https://github.com/acme/order-service.git
    default_branch  VARCHAR(100) NOT NULL DEFAULT 'main',
    spec_paths      JSONB NOT NULL DEFAULT '[]',   -- ["api/openapi.yaml", "proto/"]
    poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
    last_synced_at  TIMESTAMPTZ,
    last_sync_commit VARCHAR(40),                   -- git SHA of last successful sync
    last_sync_error TEXT,
    sync_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    codeowners_path VARCHAR(200) DEFAULT '.github/CODEOWNERS',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ                    -- soft delete
);

CREATE UNIQUE INDEX uq_repos_name ON repos(name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_repos_git_url ON repos(git_url) WHERE deleted_at IS NULL;
CREATE INDEX ix_repos_owner_team ON repos(owner_team_id);
```

### New table: `services`

A service is a deployable unit within a repo. A single-service repo has one service with `root_path = '/'`. A monorepo has multiple services, each with a distinct root path.

```sql
CREATE TABLE services (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200) NOT NULL,
    repo_id         UUID NOT NULL REFERENCES repos(id),
    root_path       VARCHAR(500) NOT NULL DEFAULT '/',  -- path within repo (e.g., "services/orders/")
    otel_service_name VARCHAR(200),                     -- matches service.name in OTEL traces
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ                         -- soft delete
);

CREATE UNIQUE INDEX uq_services_name ON services(name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_services_repo_root ON services(repo_id, root_path) WHERE deleted_at IS NULL;
CREATE INDEX ix_services_repo ON services(repo_id);
CREATE INDEX ix_services_otel_name ON services(otel_service_name) WHERE otel_service_name IS NOT NULL;
```

### Modified table: `assets`

Add optional foreign key to `services`:

```sql
ALTER TABLE assets ADD COLUMN service_id UUID REFERENCES services(id);
CREATE INDEX ix_assets_service ON assets(service_id) WHERE service_id IS NOT NULL;
```

### Derived ownership

A service's owning team is derived through the repo:
- `service.repo_id → repo.owner_team_id → team`
- No `owner_team_id` on `services` — single source of truth is the repo.
- CODEOWNERS can suggest *different* team ownership per service path within a monorepo. When that happens, the CODEOWNERS-suggested team is stored in `services.metadata.codeowners_team` for display, but `repo.owner_team_id` remains the authoritative owner until overridden.

## API Endpoints

### Repos

#### `POST /api/v1/repos`

Register a new repository.

```json
{
    "name": "order-service",
    "owner_team_id": "uuid",
    "git_url": "https://github.com/acme/order-service",
    "default_branch": "main",
    "spec_paths": ["api/openapi.yaml"],
    "poll_interval_seconds": 300,
    "codeowners_path": ".github/CODEOWNERS"
}
```

Response: `201 Created` with the repo object.

Validation:
- `name` must be unique (case-sensitive, among non-deleted)
- `git_url` must be a valid git URL (https or ssh)
- `spec_paths` must be non-empty
- `owner_team_id` must reference an existing, non-deleted team

On creation, if the repo is accessible:
1. Shallow clone to verify URL and branch are valid
2. Parse CODEOWNERS if present → store suggested team mappings in response
3. Do NOT auto-create services yet — that happens on first sync or explicit registration

#### `GET /api/v1/repos`

List repos. Supports:
- `?owner_team_id=uuid` — filter by team
- `?name=str` — partial match on name
- Pagination: `offset`, `limit` (default 20, max 100)

#### `GET /api/v1/repos/{id}`

Repo detail including:
- Repo metadata
- `service_count` (count of linked services)
- `last_sync_status` (success, error, never)
- `last_sync_commit`
- `codeowners_teams` (parsed CODEOWNERS → team suggestions, if available)

#### `PATCH /api/v1/repos/{id}`

Update mutable fields: `spec_paths`, `default_branch`, `poll_interval_seconds`, `sync_enabled`, `codeowners_path`.

#### `DELETE /api/v1/repos/{id}`

Soft delete. Does not delete linked services or assets (they become orphaned, which is queryable).

#### `POST /api/v1/repos/{id}/sync`

Trigger an immediate sync (bypass polling interval). Returns `202 Accepted` with a sync run ID.

This is the most important endpoint — it does the actual work:

1. Clone or pull the repo at `default_branch`
2. Parse CODEOWNERS (if path exists) and cache team suggestions
3. Walk `spec_paths` and detect file types:
   - `.yaml`/`.json` with `openapi` key → OpenAPI spec
   - `.proto` files → gRPC/protobuf
   - `.graphql`/`.gql` files → GraphQL schema
4. For each spec file, determine which service it belongs to (by matching file path to `services.root_path`)
   - If no matching service exists, create one (auto-discovery)
5. For each service's specs, call the existing sync logic:
   - OpenAPI → `services/openapi.py` → JSON Schema contracts
   - gRPC → `services/grpc.py` → JSON Schema contracts
   - GraphQL → `services/graphql.py` → JSON Schema contracts
6. For each generated asset/contract:
   - Set `service_id` on the asset
   - Set `owner_team_id` from the repo
   - Run schema diff against current active contract
   - Auto-publish compatible changes
   - Create proposals for breaking changes
7. Update `last_synced_at`, `last_sync_commit`
8. Log audit event: `REPO_SYNCED`

#### `GET /api/v1/repos/{id}/services`

List services belonging to this repo.

### Services

#### `POST /api/v1/services`

Manually register a service within a repo.

```json
{
    "name": "order-service",
    "repo_id": "uuid",
    "root_path": "services/orders/",
    "otel_service_name": "order-service"
}
```

Response: `201 Created`.

Validation:
- `name` must be unique (among non-deleted)
- `repo_id` must reference an existing, non-deleted repo
- `root_path` must be unique within the repo (no two services claim the same path)

#### `GET /api/v1/services`

List services. Supports:
- `?repo_id=uuid` — filter by repo
- `?owner_team_id=uuid` — filter by team (via repo.owner_team_id)
- `?name=str` — partial match on name
- `?otel_service_name=str` — exact match
- Pagination: `offset`, `limit` (default 20, max 100)

#### `GET /api/v1/services/{id}`

Service detail including:
- Service metadata
- `repo` (name, git_url, last sync info)
- `owner_team` (derived from repo)
- `asset_count`

#### `PATCH /api/v1/services/{id}`

Update mutable fields: `root_path`, `otel_service_name`, `metadata`.

#### `DELETE /api/v1/services/{id}`

Soft delete.

#### `GET /api/v1/services/{id}/assets`

List assets belonging to this service.

## CODEOWNERS Parser

### Supported formats

GitHub CODEOWNERS format (most common):

```
# Global owners
* @acme/platform-team

# Per-directory
services/orders/    @acme/commerce-team
services/payments/  @acme/commerce-team
services/auth/      @acme/platform-team
proto/              @acme/platform-team
```

Tessera parses this to produce team suggestions:

```json
{
    "suggestions": [
        {"path_pattern": "services/orders/", "github_owner": "@acme/commerce-team", "suggested_team_id": "uuid-or-null"},
        {"path_pattern": "services/payments/", "github_owner": "@acme/commerce-team", "suggested_team_id": "uuid-or-null"}
    ],
    "unresolved_owners": ["@acme/commerce-team"]
}
```

`suggested_team_id` is populated when a Tessera team's name matches the GitHub team name (fuzzy match: strip org prefix, normalize hyphens/underscores). `null` when no match is found — human resolves.

### GitLab CODEOWNERS

Same format but lives at `CODEOWNERS` (root) or `docs/CODEOWNERS`. Detect by checking both paths.

### Limitations

CODEOWNERS parsing is best-effort and advisory. It:
- Does not create teams automatically
- Does not override explicit ownership
- Is re-parsed on each sync (no stale cache)

## Authentication

### Background worker identity

The background sync worker authenticates as a bot user (PR #407). On startup, Tessera creates a system bot user `tessera-sync-bot` with a dedicated API key. All audit events from background syncs are attributed to this bot user, giving clear separation between human-initiated and automated syncs in the audit trail.

### CI webhook identity

When repos trigger sync via CI webhook (future), the webhook should use an API key associated with a bot user created for the CI system (e.g., `github-actions-bot`). This ensures per-system attribution in audit events.

## Background Worker

A background task (asyncio) runs on a configurable interval (default: 60s):

1. Query all repos where `sync_enabled = TRUE` and `last_synced_at < now() - poll_interval_seconds`
2. For each, run the sync logic (same as `POST /repos/{id}/sync`)
3. On error: set `last_sync_error`, do not update `last_synced_at`
4. Concurrency: process one repo at a time (no parallel git clones initially)

## Git Integration

### Cloning strategy

- First sync: shallow clone (`--depth 1`) into a temp directory
- Subsequent syncs: `git fetch --depth 1 origin {branch} && git reset --hard FETCH_HEAD`
- Clone target: `{DATA_DIR}/repos/{repo_id}/` (configurable via `TESSERA_REPO_DIR`)
- Cleanup: repos for deleted repos are removed by the background worker

### Authentication

- Public repos: no auth needed
- Private repos: `TESSERA_GIT_TOKEN` environment variable used as a bearer token in the URL (`https://x-access-token:{token}@github.com/...`)
- Per-repo auth (future): stored in `repos.git_credentials` (encrypted at rest)

### Security

- Validate `git_url` against an allowlist (optional, configurable)
- No arbitrary command execution — use `subprocess` with explicit args, no shell=True
- Timeout on git operations: 120 seconds
- Max repo size: 500MB (configurable)

## Spec Detection Heuristic

Given a list of `spec_paths`, for each path:

1. If path ends with `/` — scan directory recursively
2. For each file found:
   - `.yaml`, `.yml`, `.json`: parse and check for `openapi` key (→ OpenAPI) or `asyncapi` key (→ future)
   - `.proto`: treat as protobuf
   - `.graphql`, `.gql`: treat as GraphQL SDL
3. Skip files that fail to parse (log warning, continue)
4. Files that don't match any known format are ignored

### Service assignment

For each detected spec file, assign it to a service by matching its path:

1. Find the service whose `root_path` is the longest prefix of the spec file's path
2. If no service matches, create a new service:
   - Name: derived from the nearest parent directory (e.g., `services/orders/api/openapi.yaml` → `orders`)
   - `root_path`: the parent directory of the spec file
   - `otel_service_name`: null (set manually later)

## FQN Generation

Assets created by repo sync use the FQN pattern:

```
{service_name}.{spec_type}.{operation_identifier}
```

Examples:
- `order_service.rest.create_order`
- `order_service.grpc.OrderService_CreateOrder`
- `order_service.graphql.Query_getOrder`

## Migration

Alembic migration `017_add_repos_and_services_tables.py`:
- Create `repos` table
- Create `services` table
- Add `service_id` column to `assets`
- Add indexes
- SQLite compatibility: standard CREATE TABLE (no partial indexes — use WHERE clauses only on Postgres)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERA_REPO_DIR` | `./data/repos` | Directory for cloned repositories |
| `TESSERA_GIT_TOKEN` | (none) | Git auth token for private repos |
| `TESSERA_SYNC_INTERVAL` | `60` | Background worker poll interval (seconds) |
| `TESSERA_REPO_MAX_SIZE_MB` | `500` | Max repo size |
| `TESSERA_GIT_TIMEOUT` | `120` | Git operation timeout (seconds) |

## Acceptance Criteria

### Repos
- [ ] `RepoDB` model with all fields above
- [ ] Alembic migration (forward and backward)
- [ ] CRUD endpoints: create, list, get, update, delete
- [ ] Manual sync trigger (`POST /repos/{id}/sync`)
- [ ] Background polling worker
- [ ] Git clone/pull with shallow fetch
- [ ] CODEOWNERS parser (GitHub format)
- [ ] CODEOWNERS team suggestion matching

### Services
- [ ] `ServiceDB` model with all fields above
- [ ] CRUD endpoints: create, list, get, update, delete
- [ ] Auto-discovery of services during repo sync
- [ ] Service ownership derived from repo → team

### Spec Discovery
- [ ] OpenAPI spec detection and sync (reuses existing `services/openapi.py`)
- [ ] Protobuf spec detection and sync (reuses existing `services/grpc.py`)
- [ ] GraphQL spec detection and sync (reuses existing `services/graphql.py`)
- [ ] Spec file → service assignment by path matching

### Integration
- [ ] Assets linked to services via `service_id`
- [ ] Schema diff + auto-publish/proposal on spec changes
- [ ] Audit events: `REPO_CREATED`, `REPO_SYNCED`, `REPO_SYNC_FAILED`, `SERVICE_CREATED`

### Tests
- [ ] Test: register repo → sync → verify services and assets created
- [ ] Test: monorepo with two services → each gets correct assets
- [ ] Test: change spec → re-sync → verify new contract published
- [ ] Test: breaking spec change → re-sync → verify proposal created
- [ ] Test: invalid repo URL returns clear error
- [ ] Test: private repo with token works
- [ ] Test: background worker respects poll interval
- [ ] Test: CODEOWNERS parsed → team suggestions returned
- [ ] Test: spec file assigned to correct service by path prefix
