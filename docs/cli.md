# CLI Reference

Tessera provides a command-line interface for managing data contracts.

## Installation

```bash
uv sync --all-extras
```

## Global Options

```bash
tessera --help              # Show all commands
tessera --install-completion # Install shell completion
```

---

## Server

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
tessera team create "Data Platform"
tessera team create "Analytics" --metadata '{"slack": "#analytics"}'
```

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Team name (required) |
| `-m, --metadata` | JSON metadata |

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
tessera asset create warehouse.analytics.users --team <team-id>
tessera asset create warehouse.core.orders --team <team-id> --metadata '{"owner": "jane"}'
```

| Argument/Option | Description |
|-----------------|-------------|
| `FQN` | Fully qualified name (required) |
| `-t, --team` | Owner team ID (required) |
| `-m, --metadata` | JSON metadata |

### `tessera asset list`

List assets with optional filters.

```bash
tessera asset list
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
tessera asset search --fqn warehouse.analytics.%
```

---

## Contract Management

### `tessera contract publish`

Publish a new contract version.

```bash
tessera contract publish \
  --asset <asset-id> \
  --team <team-id> \
  --version 1.0.0 \
  --schema schema.json

# Force breaking change
tessera contract publish \
  --asset <asset-id> \
  --team <team-id> \
  --version 2.0.0 \
  --schema new-schema.json \
  --force
```

| Option | Description |
|--------|-------------|
| `-a, --asset` | Asset ID (required) |
| `-t, --team` | Publisher team ID (required) |
| `-v, --version` | Contract version (required) |
| `-s, --schema` | Path to JSON schema file (required) |
| `-c, --compat` | Compatibility mode: `backward`, `forward`, `full`, `none` (default: backward) |
| `-f, --force` | Force publish breaking changes |

### `tessera contract list`

List contracts for an asset.

```bash
tessera contract list --asset <asset-id>
```

### `tessera contract diff`

Show differences between contract versions.

```bash
tessera contract diff --asset <asset-id> --from 1.0.0 --to 2.0.0
```

### `tessera contract impact`

Analyze impact of a proposed schema change.

```bash
tessera contract impact --asset <asset-id> --schema new-schema.json
```

---

## Consumer Registration

### `tessera register`

Register as a consumer of an asset.

```bash
tessera register --asset <asset-id> --team <consumer-team-id>

# Pin to specific version
tessera register --asset <asset-id> --team <consumer-team-id> --pin 1.0.0
```

| Option | Description |
|--------|-------------|
| `-a, --asset` | Asset ID (required) |
| `-t, --team` | Consumer team ID (required) |
| `-p, --pin` | Pin to specific contract version |

---

## Proposal Management

### `tessera proposal list`

List breaking change proposals.

```bash
tessera proposal list
tessera proposal list --asset <asset-id>
tessera proposal list --status pending
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
tessera proposal acknowledge <proposal-id> --team <team-id>
tessera proposal acknowledge <proposal-id> --team <team-id> --response blocked --notes "Need migration time"
```

| Argument/Option | Description |
|-----------------|-------------|
| `PROPOSAL_ID` | Proposal ID (required) |
| `-t, --team` | Consumer team ID (required) |
| `-r, --response` | Response: `approved`, `blocked`, `migrating` (default: approved) |
| `-n, --notes` | Optional notes |

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
# Basic sync
tessera dbt sync --manifest target/manifest.json --team <team-id>

# Create assets for new models
tessera dbt sync --manifest target/manifest.json --team <team-id> --create-assets

# Auto-publish compatible changes
tessera dbt sync --manifest target/manifest.json --team <team-id> --publish-compatible
```

| Option | Description |
|--------|-------------|
| `-m, --manifest` | Path to manifest.json (default: target/manifest.json) |
| `-t, --team` | Owner team ID for new assets |
| `-c, --create-assets` | Create assets for new models |
| `--publish-compatible` | Auto-publish compatible schema changes |

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

---

## Shell Completion

```bash
tessera --install-completion bash
tessera --install-completion zsh
tessera --install-completion fish
```
