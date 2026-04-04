# Quickstart

Get Tessera running in 5 minutes with Docker.

## Prerequisites

- Docker and Docker Compose
- An OpenAPI spec, GraphQL schema, or dbt manifest (optional, for sync)

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

### Option A: From an OpenAPI Spec

The fastest path if you have an existing OpenAPI spec:

```bash
# 1. Create a team
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -d '{"name": "platform-team"}'
```

Save the returned `id` as `TEAM_ID`.

```bash
# 2. Import your OpenAPI spec
curl -X POST http://localhost:8000/api/v1/sync/openapi \
  -H "Content-Type: application/json" \
  -d "{
    \"spec\": $(cat openapi.yaml | python3 -c 'import sys,json,yaml; json.dump(yaml.safe_load(sys.stdin), sys.stdout)'),
    \"owner_team_id\": \"TEAM_ID\",
    \"auto_publish_contracts\": true
  }"
```

This creates one asset per endpoint, extracts request/response schemas, and publishes contracts. Tessera will detect breaking changes on subsequent imports.

### Option B: Manual Contract

Create an asset and contract directly:

```bash
# 1. Create a team
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -d '{"name": "platform-team"}'
```

Save the returned `id` as `TEAM_ID`.

```bash
# 2. Create an asset
curl -X POST http://localhost:8000/api/v1/assets \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "api.users_service.get_users",
    "owner_team_id": "TEAM_ID"
  }'
```

Save the returned `id` as `ASSET_ID`.

```bash
# 3. Publish a contract
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

### Register as a Consumer

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

### Option C: Sync from dbt

If you have a dbt project, you can sync your models:

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

This creates assets for each model, source, seed, and snapshot; extracts column schemas; and publishes contracts.

## What's Next?

- [Installation Guide](installation.md) - Install without Docker
- [Configuration](configuration.md) - Environment variables and settings
- [Sync API](../api/sync.md) - OpenAPI, GraphQL, gRPC, and dbt sync adapters
- [dbt Integration](../guides/dbt-integration.md) - Deep dive on dbt sync
- [Concepts](../concepts/overview.md) - Understand how Tessera works
