# CI/CD Integration

Integrate Tessera into your CI/CD pipeline to catch breaking changes before they reach production.

## GitHub Actions

### Check for Breaking Changes

Add this workflow to fail PRs with breaking changes:

```yaml
# .github/workflows/tessera-check.yml
name: Contract Check

on:
  pull_request:
    paths:
      - 'models/**'
      - 'dbt_project.yml'

jobs:
  check-contracts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dbt
        run: pip install dbt-core dbt-postgres

      - name: Compile dbt
        run: dbt compile
        env:
          DBT_PROFILES_DIR: .

      - name: Check for breaking changes
        run: |
          RESPONSE=$(curl -s -X POST "${{ secrets.TESSERA_URL }}/api/v1/sync/dbt?dry_run=true" \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d @target/manifest.json)

          BREAKING=$(echo $RESPONSE | jq '.breaking_changes | length')

          if [ "$BREAKING" -gt 0 ]; then
            echo "::error::Breaking changes detected!"
            echo "$RESPONSE" | jq '.breaking_changes'
            exit 1
          fi

          echo "No breaking changes detected"
```

### Sync on Merge

Automatically sync contracts when changes merge to main:

```yaml
# .github/workflows/tessera-sync.yml
name: Sync Contracts

on:
  push:
    branches: [main]
    paths:
      - 'models/**'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dbt
        run: pip install dbt-core dbt-postgres

      - name: Compile and sync
        run: |
          dbt compile
          curl -X POST "${{ secrets.TESSERA_URL }}/api/v1/sync/dbt" \
            -H "Authorization: Bearer ${{ secrets.TESSERA_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d @target/manifest.json
        env:
          DBT_PROFILES_DIR: .
```

## GitLab CI

```yaml
# .gitlab-ci.yml
stages:
  - check
  - sync

check-contracts:
  stage: check
  image: python:3.11
  script:
    - pip install dbt-core dbt-postgres
    - dbt compile
    - |
      RESPONSE=$(curl -s -X POST "$TESSERA_URL/api/v1/sync/dbt?dry_run=true" \
        -H "Authorization: Bearer $TESSERA_API_KEY" \
        -H "Content-Type: application/json" \
        -d @target/manifest.json)
      BREAKING=$(echo $RESPONSE | jq '.breaking_changes | length')
      if [ "$BREAKING" -gt 0 ]; then
        echo "Breaking changes detected!"
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - models/**/*

sync-contracts:
  stage: sync
  image: python:3.11
  script:
    - pip install dbt-core dbt-postgres
    - dbt compile
    - |
      curl -X POST "$TESSERA_URL/api/v1/sync/dbt" \
        -H "Authorization: Bearer $TESSERA_API_KEY" \
        -H "Content-Type: application/json" \
        -d @target/manifest.json
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - models/**/*
```

## Pre-commit Hooks

Catch issues locally before pushing:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: tessera-check
        name: Check Tessera contracts
        entry: bash -c 'dbt compile && curl -s -X POST "$TESSERA_URL/api/v1/sync/dbt?dry_run=true" -H "Authorization: Bearer $TESSERA_API_KEY" -d @target/manifest.json | jq -e ".breaking_changes | length == 0"'
        language: system
        pass_filenames: false
        files: ^models/.*\.(sql|yml)$
```

## Best Practices

1. **Check on PRs**: Fail builds with breaking changes early
2. **Sync on merge**: Keep Tessera in sync with main branch
3. **Use dry run**: Preview changes before syncing
4. **Store secrets securely**: Use CI/CD secret management
5. **Add status badges**: Show contract status in README
