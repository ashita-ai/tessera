# CLI Reference

Tessera provides a command-line interface for managing data contracts.

## Installation

```bash
uv sync --all-extras
```

## Commands

### `tessera serve`

Start the API server.

```bash
tessera serve --host 0.0.0.0 --port 8000
```

### `tessera version`

Show Tessera version.

---

## Team Management

### `tessera team create`

Create a new team.

```bash
tessera team create --name "Data Platform" --slug data-platform
```

### `tessera team list`

List all teams.

```bash
tessera team list
```

### `tessera team get`

Get team details.

```bash
tessera team get <team-id>
```

---

## Asset Management

### `tessera asset create`

Create a new asset.

```bash
tessera asset create \
  --team <team-id> \
  --fqn warehouse.schema.table \
  --type table
```

### `tessera asset list`

List assets with optional filters.

```bash
tessera asset list --team <team-id>
```

### `tessera asset get`

Get asset details.

```bash
tessera asset get <asset-id>
```

### `tessera asset search`

Search assets by fully-qualified name.

```bash
tessera asset search --fqn warehouse.schema.%
```

---

## Contract Management

### `tessera contract publish`

Publish a new contract version.

```bash
tessera contract publish \
  --asset <asset-id> \
  --schema @schema.json \
  --compatibility backward
```

Options:
- `--compatibility`: `backward` (default), `forward`, `full`, `none`
- `--force`: Skip breaking change workflow

### `tessera contract list`

List contracts for an asset.

```bash
tessera contract list --asset <asset-id>
```

### `tessera contract diff`

Show differences between contract versions.

```bash
tessera contract diff --asset <asset-id> --from v1 --to v2
```

### `tessera contract impact`

Analyze impact of a proposed schema change.

```bash
tessera contract impact --asset <asset-id> --schema @new-schema.json
```

---

## Consumer Registration

### `tessera register`

Register as a consumer of an asset.

```bash
tessera register --asset <asset-id> --team <consumer-team-id>
```

Options:
- `--pin`: Pin to a specific contract version

---

## Proposal Management

### `tessera proposal list`

List breaking change proposals.

```bash
tessera proposal list --asset <asset-id> --status pending
```

### `tessera proposal get`

Get proposal details.

```bash
tessera proposal get <proposal-id>
```

### `tessera proposal status`

Get proposal acknowledgment status.

```bash
tessera proposal status <proposal-id>
```

### `tessera proposal acknowledge`

Acknowledge a breaking change proposal.

```bash
tessera proposal acknowledge <proposal-id> \
  --team <team-id> \
  --response approved
```

Responses: `approved`, `blocked`, `will_migrate`

### `tessera proposal withdraw`

Withdraw a pending proposal.

```bash
tessera proposal withdraw <proposal-id>
```

### `tessera proposal force`

Force approve a proposal (skips consumer acknowledgment).

```bash
tessera proposal force <proposal-id>
```

### `tessera proposal publish`

Publish an approved proposal as a new contract.

```bash
tessera proposal publish <proposal-id>
```

---

## dbt Integration

### `tessera dbt sync`

Sync dbt models with Tessera.

```bash
tessera dbt sync --manifest target/manifest.json --team <team-id>
```

### `tessera dbt check`

Check dbt models for schema changes against registered contracts.

```bash
tessera dbt check --manifest target/manifest.json
```

### `tessera dbt register`

Register as a consumer of upstream dependencies.

```bash
tessera dbt register --manifest target/manifest.json --team <team-id>
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TESSERA_API_URL` | API server URL | `http://localhost:8000` |
| `TESSERA_API_KEY` | API key for authentication | - |
| `DATABASE_URL` | Database connection string | - |

---

## Shell Completion

```bash
# Bash
tessera --install-completion bash

# Zsh
tessera --install-completion zsh

# Fish
tessera --install-completion fish
```
