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

## Authentication

For local development, the easiest option is to disable authentication:

```bash
# In your .env or docker-compose.override.yml
AUTH_DISABLED=true
```

For production or to test authentication, set a bootstrap API key:

```bash
BOOTSTRAP_API_KEY=your-secret-api-key
```

Use this key in the `Authorization: Bearer` header for API requests.

## Access the Web UI

Open [http://localhost:8000](http://localhost:8000) in your browser.

With `AUTH_DISABLED=true`, you can access the UI without logging in. Otherwise, create an admin user via the API or use the bootstrap API key.

## Create Your First Contract

### 1. Create a Team

```bash
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -d '{"name": "data-platform"}'
```

Save the returned `id` as `TEAM_ID`.

### 2. Create an Asset

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "warehouse.analytics.users",
    "owner_team_id": "TEAM_ID"
  }'
```

Save the returned `id` as `ASSET_ID`.

### 3. Publish a Contract

```bash
curl -X POST "http://localhost:8000/api/v1/assets/ASSET_ID/contracts?published_by=TEAM_ID" \
  -H "Content-Type: application/json" \
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

Another team can register as a consumer of your contract:

```bash
curl -X POST http://localhost:8000/api/v1/registrations \
  -H "Content-Type: application/json" \
  -d '{
    "contract_id": "CONTRACT_ID",
    "consumer_team_id": "CONSUMER_TEAM_ID"
  }'
```

If authentication is enabled, add `-H "Authorization: Bearer YOUR_API_KEY"` to all requests.

## Sync from dbt

If you have a dbt project, you can sync your models automatically:

```bash
# Generate your manifest
cd your-dbt-project
dbt compile

# Upload to Tessera
curl -X POST http://localhost:8000/api/v1/sync/dbt/upload \
  -H "Content-Type: application/json" \
  -d "{
    \"manifest\": $(cat target/manifest.json),
    \"owner_team_id\": \"TEAM_ID\",
    \"auto_publish_contracts\": true
  }"
```

This will:
- Create assets for each model, source, seed, and snapshot
- Extract column schemas from your YAML definitions
- Publish contracts automatically

## What's Next?

- [Installation Guide](installation.md) - Install without Docker
- [Configuration](configuration.md) - Environment variables and settings
- [dbt Integration](../guides/dbt-integration.md) - Deep dive on dbt sync
- [Concepts](../concepts/overview.md) - Understand how Tessera works
