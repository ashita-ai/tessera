# Quickstart

Get Tessera running in 5 minutes with Docker.

## Prerequisites

- Docker and Docker Compose
- A dbt project (optional, for manifest sync)

## Start Tessera

```bash
# Clone the repository
git clone https://github.com/ashita-ai/tessera.git
cd tessera

# Start with Docker Compose
docker compose up -d

# Check it's running
curl http://localhost:8000/health
```

Tessera is now running at `http://localhost:8000`.

## Access the Web UI

Open [http://localhost:8000](http://localhost:8000) in your browser.

Default credentials:
- **Email**: `admin@example.com`
- **Password**: `admin`

## Create Your First Contract

### 1. Create a Team

```bash
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TESSERA_BOOTSTRAP_KEY" \
  -d '{"name": "data-platform"}'
```

### 2. Create an Asset

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -d '{
    "fqn": "warehouse.analytics.users",
    "owner_team_id": "YOUR_TEAM_ID"
  }'
```

### 3. Publish a Contract

```bash
curl -X POST http://localhost:8000/api/v1/assets/YOUR_ASSET_ID/contracts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -d '{
    "schema": {
      "type": "object",
      "properties": {
        "user_id": {"type": "integer"},
        "email": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"}
      },
      "required": ["user_id", "email"]
    },
    "compatibility_mode": "backward"
  }'
```

### 4. Register as a Consumer

Another team can register as a consumer of your asset:

```bash
curl -X POST http://localhost:8000/api/v1/registrations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CONSUMER_API_KEY" \
  -d '{
    "contract_id": "YOUR_CONTRACT_ID",
    "consumer_team_id": "CONSUMER_TEAM_ID"
  }'
```

## Sync from dbt

If you have a dbt project, you can sync your models automatically:

```bash
# Generate your manifest
cd your-dbt-project
dbt compile

# Upload to Tessera
curl -X POST http://localhost:8000/api/v1/sync/dbt \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TESSERA_API_KEY" \
  -d @target/manifest.json
```

This will:
- Create assets for each model
- Extract column schemas from your YAML definitions
- Publish contracts automatically

## What's Next?

- [Installation Guide](installation.md) - Install without Docker
- [Configuration](configuration.md) - Environment variables and settings
- [dbt Integration](../guides/dbt-integration.md) - Deep dive on dbt sync
- [Concepts](../concepts/overview.md) - Understand how Tessera works
