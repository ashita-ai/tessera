# Tessera Next Steps

## Strategic Direction

Tessera's killer feature is **Git + dbt integration for breaking change coordination**. The core workflow:

```
Developer changes dbt model → CI runs → Tessera identifies affected consumers →
Notifications sent → Consumers acknowledge in PR → PR merges
```

## Phase 1: dbt Integration Polish

### 1.1 Parse `meta.owner` During Sync
Auto-assign asset ownership from dbt model metadata:

```yaml
# In dbt project: models/schema.yml
models:
  - name: customers
    meta:
      owner: evan@example.com      # or team name
      contact: "#data-team"        # Slack channel
```

**Matching strategy (in order):**
1. Exact email match → User
2. Exact name match → User
3. Team name match → Team
4. No match → Log warning, continue (never fail sync)

### 1.2 Auto-Register Consumers from `source()` References
If a dbt project has:
```yaml
sources:
  - name: upstream_team
    tables:
      - name: customers
```

That's a declaration of dependency. Auto-register as consumer during sync.

### 1.3 Add Contact Fields to User Model
```python
class UserDB(Base):
    email: Mapped[str]
    github_username: Mapped[str | None]
    gitlab_username: Mapped[str | None]
    slack_member_id: Mapped[str | None]  # Slack member ID, not handle
```

## Phase 2: CI Integration

### 2.1 GitHub Action
Create a GitHub Action that:
1. Runs on PR when dbt models change
2. Calls `/api/v1/sync/dbt/impact` with new manifest
3. Comments on PR with breaking changes and affected consumers
4. Optionally blocks merge until acknowledgments received

### 2.2 Webhook Improvements
- Reliable delivery with retry
- Delivery status tracking
- Slack/email notification templates

## Phase 3: Launch Prep

### 3.1 README Polish
Structure for 30-second scannability:
```
# Tessera
One sentence: what it does

## The Problem (3 bullets)
## The Solution (screenshot)
## Quick Start (5 lines of code)
## Features (bullets with links)
```

### 3.2 Screenshots/GIFs
- Hero image of the proposal workflow
- Asset detail page
- Breaking change detection

### 3.3 Live Demo
Deploy to Railway/Render with SQLite, seed with example data.

### 3.4 Footer
Change "Tessera — Data Contract Coordination" → "Tessera"

## Architectural Decisions

### Database vs Config Files
**Decision: Hybrid approach**
- Config files for declarations ("I produce X" / "I consume Y")
- Database for coordination (proposals, acknowledgments, history)
- Sync config → database (like we do with dbt manifest)

The coordination problem requires shared state. You can't do "wait for 3 teams to acknowledge" in config files.

### Warehouse Integrations
**Decision: dbt-first, design for extensibility**

dbt already abstracts warehouse differences. Tessera doesn't need direct BigQuery/Snowflake connections.

```python
# Abstract interface for future
class SchemaExtractor(Protocol):
    async def extract_schema(self, asset_fqn: str) -> JSONSchema: ...

class DbtManifestExtractor(SchemaExtractor): ...
class BigQueryExtractor(SchemaExtractor): ...  # Future
```

### GitHub vs GitLab vs Generic
**Decision: Webhooks + GitHub Action first**
- Webhooks let anyone integrate however they want
- GitHub Action covers 80% of the market
- GitLab support via webhooks initially

## Positioning

> "dbt enforces contracts in pipelines. Tessera coordinates contracts between teams."

**What dbt has:**
- Model contracts (enforcement)
- Data tests (validation)
- Meta tags (documentation)

**What Tessera adds:**
- Consumer registry ("who uses my data?")
- Cross-project coordination
- Acknowledgment workflow
- Breaking change negotiation

## Marketing Shots

Each is an opportunity for visibility:

1. **Show HN post** - Focus on the problem, not the solution
2. **Blog post: "The Data Contract Problem"** - Why breaking changes are hard
3. **Blog post: "dbt + Tessera"** - Integration deep-dive

**HN Tips:**
- Post on weekday morning US time
- Don't astroturf (HN detects and kills posts)
- README must be scannable in 30 seconds
- Live demo or screenshots essential

## UI Improvements

### Schema Editor
Current: JSON textarea (painful)
Better options:
- Visual schema builder (add column, set type, required)
- Syntax highlighting + validation
- "Import from dbt" button

**Decision:** Keep manual editing for flexibility, but improve UX. For v1, focus on dbt-first workflow in docs.

## Beyond dbt (Future)

| Tool | Difficulty | Priority |
|------|-----------|----------|
| SQLMesh | Low | Medium |
| Dagster | Medium | Medium |
| Airflow | High | Low |
| Great Expectations | Medium | High |

Strategy: Nail dbt first. Add others based on user demand.

## Implementation Priority

### Immediate (This Week)
1. [ ] Parse `meta.owner` during dbt sync
2. [ ] Auto-register consumers for `source()` references
3. [ ] Add contact fields to User model
4. [ ] Fix footer text
5. [ ] Polish README

### Near-term
6. [ ] GitHub Action for CI integration
7. [ ] PR comment integration
8. [ ] Webhook retry/reliability
9. [ ] Deploy live demo

### Later
10. [ ] Visual schema editor
11. [ ] Slack integration
12. [ ] SQLMesh support
