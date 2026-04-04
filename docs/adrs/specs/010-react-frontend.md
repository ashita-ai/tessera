# Spec-010: React Frontend

**Related ADR:** ADR-014 (Service Contract Pivot)
**Depends on:** Spec-006, 007, 008, 009 (API endpoints it consumes)
**Status:** Draft
**Date:** 2026-04-02

## Overview

Replace the existing Jinja2/vanilla JS server-rendered UI with a React single-page application. The frontend is the primary interface for understanding service dependencies, reviewing breaking changes, and managing coordination workflows.

The dependency graph visualization is the hero feature — the first thing users see when they open Tessera.

## Technology

| Choice | Rationale |
|--------|-----------|
| React 19 + TypeScript | Type safety, component model, ecosystem |
| Vite 6 | Fast dev server, simple config, ESM-native |
| Tailwind CSS 3 | Utility-first, custom design tokens via CSS variables |
| D3.js 7 | Full control over force-directed graph rendering |
| TanStack Query 5 | Data fetching with stale-while-revalidate, caching |
| React Router 7 | Client-side routing |
| date-fns | Lightweight date formatting |

No component library (shadcn, Radix, etc.) initially. Custom components give full aesthetic control and avoid dependency churn. Reconsider if the number of form-heavy pages grows beyond what's manageable.

## Design System

### Theme

Dark mode default, light mode toggle. CSS custom properties for all colors:

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--surface-0` | `#06090f` | `#f8fafc` | Page background |
| `--surface-1` | `#0c1220` | `#ffffff` | Card/panel background |
| `--surface-2` | `#131c2e` | `#f1f5f9` | Hover/elevated surface |
| `--surface-3` | `#1a2540` | `#e2e8f0` | Deeply nested surface |
| `--accent` | `#06b6d4` | `#0891b2` | Primary accent (cyan) |
| `--danger` | `#ef4444` | `#ef4444` | Breaking changes, errors |
| `--warning` | `#f59e0b` | `#f59e0b` | Proposals, deprecations |
| `--success` | `#10b981` | `#10b981` | Approved, healthy |

### Typography

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| Display | Syne | 600-800 | Page titles, section headers |
| Body | Outfit | 300-600 | UI text, labels, descriptions |
| Mono | Fira Code | 400-600 | FQNs, versions, schemas, code |

### Visual identity

- Subtle noise texture overlay for depth (SVG filter, 3% opacity)
- Grid background on graph area (48px spacing, border-color lines)
- Glow effects on accent elements (box-shadow with accent-glow-alpha)
- Staggered fade-in-up animations on page load (60ms delay per child)

## Project Structure

```
frontend/
├── index.html
├── package.json
├── vite.config.ts               # Proxy /api → backend, build to static/dist
├── tailwind.config.ts           # Custom theme tokens
├── tsconfig.json
├── src/
│   ├── main.tsx                 # React entry + QueryClient
│   ├── App.tsx                  # Router + layout
│   ├── index.css                # Global styles, CSS variables, animations
│   ├── lib/
│   │   ├── api.ts               # Typed API client (fetch-based)
│   │   └── utils.ts             # cn(), formatDate(), truncate()
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Shell.tsx        # App shell (sidebar + header + outlet)
│   │   │   ├── Sidebar.tsx      # Navigation with inline SVG icons
│   │   │   └── Header.tsx       # Theme toggle, user menu
│   │   ├── graph/
│   │   │   └── DependencyGraph.tsx  # D3 force simulation
│   │   └── shared/
│   │       ├── StatCard.tsx     # Dashboard stat tile
│   │       ├── ActivityFeed.tsx # Timeline with severity dots
│   │       └── SchemaViewer.tsx # JSON Schema renderer with diff highlighting
│   ├── pages/
│   │   ├── Dashboard.tsx        # Stats + graph + proposals + activity
│   │   ├── Repos.tsx            # Repo list + register modal
│   │   ├── RepoDetail.tsx       # Repo detail: services, sync history, CODEOWNERS
│   │   ├── Services.tsx         # Service list (filterable by repo, team)
│   │   ├── ServiceDetail.tsx    # Service detail with neighborhood graph
│   │   ├── Assets.tsx           # Asset table with filters
│   │   ├── AssetDetail.tsx      # Contract viewer + consumers + lineage
│   │   ├── Proposals.tsx        # Proposal list with ack progress
│   │   ├── ProposalDetail.tsx   # Full proposal with diff + ack actions
│   │   ├── Teams.tsx            # Team cards
│   │   ├── TeamDetail.tsx       # Team's repos, services, assets, proposals
│   │   └── AuditLog.tsx         # Filterable event timeline
│   └── hooks/
│       ├── useGraph.ts          # Fetches + caches service graph data
│       └── useTheme.ts          # Dark/light mode state
```

## Pages

### Dashboard (`/`)

**Data sources:** `GET /graph/services`, `GET /proposals?status=pending`, `GET /audit/events`

Layout:
- Top: 4 stat cards (services, assets, contracts, pending proposals) — staggered animation on load
- Middle: 2/3 dependency graph + 1/3 sidebar (pending proposals list, recent activity feed)
- Bottom: selected node detail panel (appears on graph node click)

The graph uses demo data until the graph API (Spec-009) is implemented. TanStack Query fetches real data when available and falls back gracefully.

### Repos (`/repos`)

**Data sources:** `GET /repos`

- Card grid showing registered repositories
- Each card: name, git URL, team, service count, sync status, last synced
- Register button opens modal: name, git URL, default branch, spec paths, team
- Graceful "not yet available" state when repo endpoints don't exist

### Repo Detail (`/repos/:id`)

**Data sources:** `GET /repos/{id}`, `GET /repos/{id}/services`

- Repo metadata (git URL, branch, spec paths, poll interval)
- CODEOWNERS team suggestions (if parsed)
- Service list within this repo (card grid)
- Sync history with error details
- Trigger sync button

### Services (`/services`)

**Data sources:** `GET /services`

- Card grid showing registered services
- Each card: name, parent repo, team (derived from repo), OTEL name, asset count
- Filter by repo, team
- Graceful "not yet available" state when service endpoints don't exist

### Service Detail (`/services/:id`)

**Data sources:** `GET /services/{id}`, `GET /services/{id}/assets`, `GET /graph/services/{id}/neighborhood`

- Service metadata (parent repo link, root path, OTEL name)
- Neighborhood graph (D3 — just this service + direct neighbors)
- Asset list (table)
- Link to parent repo's sync history

### Assets (`/assets`)

**Data sources:** `GET /assets`

- Filterable table: FQN search, type filter (dropdown), team filter, service filter
- Type badges with color coding (api=blue, grpc=violet, graphql=purple, kafka=rose)
- Sortable columns
- Pagination

### Asset Detail (`/assets/:id`)

**Data sources:** `GET /assets/{id}/context`

- Contract schema viewer (JSON tree with collapsible nodes, syntax highlighting)
- Version history (list of past contract versions with diff links)
- Consumer list (registered teams)
- Upstream/downstream lineage (miniature D3 graph or simple list)
- Active proposals

### Contracts (diff view, accessed from Asset Detail)

**Data sources:** `GET /contracts/{id}`, compare two contracts

- Side-by-side schema diff
- Breaking changes highlighted in red with explanations
- Compatible changes highlighted in amber
- Unchanged sections collapsed by default
- Migration suggestions (from Spec-003) shown below the diff

### Proposals (`/proposals`)

**Data sources:** `GET /proposals`

- Card list with status badges (pending=amber, approved=green, rejected=red, expired=gray)
- Ack progress bar per proposal
- Breaking changes summary
- Filter by status

### Proposal Detail (`/proposals/:id`)

**Data sources:** `GET /proposals/{id}`

- Full breaking changes list with schema paths
- Per-consumer acknowledgment status (table: team, response, date, comment)
- Action buttons: Approve, Block, Migrating (with comment field)
- Schema diff viewer (old contract vs proposed)

### Teams (`/teams`)

**Data sources:** `GET /teams`

- Card grid: name, asset count, member count
- Created date

### Team Detail (`/teams/:id`)

**Data sources:** `GET /teams/{id}`, `GET /repos?owner_team_id=`, `GET /services?owner_team_id=`, `GET /proposals/pending/{team_id}`

- Owned repos (card grid)
- Owned services (derived from repos)
- Owned assets (table)
- Pending proposals needing this team's ack
- Slack config status

### Audit Log (`/audit`)

**Data sources:** `GET /audit/events`

- Filterable timeline with action-type dropdown
- Severity-colored dots (accent=normal, amber=proposal/deprecation, red=rejection/force)
- Agent badge on events from AI agents
- Expandable detail panel per event (shows full payload)

## Development Workflow

```bash
# Setup
cd frontend && npm install

# Dev (proxies /api to localhost:8000)
npm run dev      # → http://localhost:3000

# Type check
npm run typecheck

# Lint
npm run lint

# Production build (outputs to src/tessera/static/dist/)
npm run build
```

### Backend integration

Vite's dev server proxies `/api` to `http://localhost:8000`. In production, FastAPI serves the built static files:

```python
# In main.py, after API routes:
dist_dir = Path(__file__).parent / "static" / "dist"
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
```

### Transition from Jinja2

The Jinja2 templates and `web/routes.py` remain functional during the transition. Both UIs can run simultaneously:
- `/api/v1/*` — REST API (shared)
- `/` via Jinja2 — old UI (existing routes)
- `/app/*` or localhost:3000 — new React UI

Once the React UI covers all existing pages, the Jinja2 templates are removed.

## Remaining Work (not yet built)

The initial scaffolding includes: Dashboard, Services (list + register), Assets (table), Proposals (list), Teams (list), Audit Log. Still needed:

- [ ] Repos page (list + register modal)
- [ ] Repo Detail page with services, sync history, CODEOWNERS
- [ ] Service Detail page with neighborhood graph
- [ ] Asset Detail page with context view and schema viewer
- [ ] Proposal Detail page with diff view and ack actions
- [ ] Team Detail page
- [ ] Schema diff viewer component (side-by-side comparison)
- [ ] SchemaViewer component (collapsible JSON tree)
- [ ] useGraph hook (fetch from Spec-009 endpoints, fall back to demo data)
- [ ] useTheme hook (persist preference in localStorage)
- [ ] Error boundary component
- [ ] Loading skeleton components
- [ ] 404 page
- [ ] Responsive layout for tablet/mobile
- [ ] Keyboard shortcuts (/ to search, ? for help)
- [ ] Deep linking (URL reflects all filter/sort state)

## Acceptance Criteria

- [ ] All pages listed above render with real API data
- [ ] Dependency graph is interactive (zoom, pan, drag, click, hover highlight)
- [ ] Dark/light mode toggle persists across sessions
- [ ] Type-safe API client with proper error handling
- [ ] Staggered animations on page transitions
- [ ] Schema diff viewer highlights breaking vs compatible changes
- [ ] Proposal ack actions work (approve/block/migrating)
- [ ] Responsive on desktop (1024px+), functional on tablet (768px+)
- [ ] Production build serves correctly from FastAPI
- [ ] No runtime TypeScript errors (strict mode)
- [ ] Lighthouse performance score >80
