# Configuration

Tessera is configured via environment variables.

## Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `postgresql+asyncpg://user:pass@localhost:5432/tessera` |

## Core Settings

### Environment

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Environment name (`development`, `production`) | `development` |
| `AUTO_CREATE_TABLES` | Auto-create DB tables on startup (set `false` in prod) | `true` |

### Logging

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) | `INFO` |
| `LOG_FORMAT` | Log output format: `text` for human-readable, `json` for structured | `text` |

### Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `SESSION_SECRET_KEY` | Secret for session signing (min 32 chars) | Dev default (change in prod!) |
| `BOOTSTRAP_API_KEY` | Initial admin API key for setup | None |
| `AUTH_DISABLED` | Disable auth (dev only) | `false` |

### Admin Bootstrap

For initial setup or Kubernetes deployments, you can bootstrap an admin user:

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMIN_USERNAME` | Bootstrap admin username (both `ADMIN_USERNAME` and `ADMIN_PASSWORD` required) | None |
| `ADMIN_EMAIL` | Bootstrap admin email address | None |
| `ADMIN_PASSWORD` | Bootstrap admin password (both `ADMIN_USERNAME` and `ADMIN_PASSWORD` required) | None |
| `ADMIN_NAME` | Bootstrap admin display name | `Admin` |

### Demo Mode

| Variable | Description | Default |
|----------|-------------|---------|
| `DEMO_MODE` | Show demo credentials on login page | `false` |

### CORS

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000,http://localhost:5173` |
| `CORS_ALLOW_METHODS` | Allowed HTTP methods | `GET,POST,PATCH,DELETE,OPTIONS` |

## Webhooks

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBHOOK_URL` | URL for webhook delivery | None |
| `WEBHOOK_SECRET` | HMAC secret for signing payloads | None |
| `WEBHOOK_ALLOWED_DOMAINS` | Comma-separated domain allowlist for webhook URLs | None (all allowed) |
| `WEBHOOK_DNS_TIMEOUT` | DNS resolution timeout in seconds for webhook URL validation | `5.0` |
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications | None |
| `SLACK_ENABLED` | Enable team-scoped Slack notifications globally | `false` |
| `SLACK_RATE_LIMIT_PER_SECOND` | Max Slack API calls per second (Slack's limit is 1/sec per channel) | `1` |
| `TESSERA_BASE_URL` | Base URL for deep links in Slack messages | `http://localhost:3000` |

## Caching

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection for caching | None (disabled) |
| `REDIS_CONNECT_TIMEOUT` | Redis socket connect timeout in seconds | `0.05` |
| `REDIS_SOCKET_TIMEOUT` | Redis socket operation timeout in seconds | `0.05` |
| `CACHE_TTL` | Default cache TTL in seconds | `300` |
| `CACHE_TTL_CONTRACT` | Contract cache TTL | `600` |
| `CACHE_TTL_ASSET` | Asset cache TTL | `300` |
| `CACHE_TTL_TEAM` | Team cache TTL | `300` |
| `CACHE_TTL_SCHEMA` | Schema cache TTL | `3600` |

## Rate Limiting

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `RATE_LIMIT_READ` | Read endpoint limit | `1000/minute` |
| `RATE_LIMIT_WRITE` | Write endpoint limit | `100/minute` |
| `RATE_LIMIT_ADMIN` | Admin endpoint limit | `50/minute` |
| `RATE_LIMIT_GLOBAL` | Global limit per client | `5000/minute` |
| `RATE_LIMIT_AUTH` | Authentication attempt limit (stricter to prevent brute-force) | `30/minute` |
| `RATE_LIMIT_EXPENSIVE` | Per-team limit for expensive operations (schema diff, lineage) | `20/minute` |
| `RATE_LIMIT_BULK` | Per-team limit for bulk operations | `10/minute` |
| `RATE_LIMIT_AGENT_READ` | Agent read (GET) endpoint limit | `5000/minute` |
| `RATE_LIMIT_AGENT_WRITE` | Agent write (POST/PUT/PATCH) endpoint limit | `500/minute` |
| `RATE_LIMIT_AGENT_ADMIN` | Agent admin (DELETE, key management) endpoint limit | `250/minute` |

## Resource Constraints

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_SCHEMA_SIZE_BYTES` | Maximum schema size | `1000000` (1MB) |
| `MAX_SCHEMA_PROPERTIES` | Maximum properties in schema | `1000` |
| `MAX_SCHEMA_NESTING_DEPTH` | Maximum nesting depth for schema objects | `10` |
| `MAX_FQN_LENGTH` | Maximum FQN length | `1000` |
| `MAX_TEAM_NAME_LENGTH` | Maximum team name length | `255` |
| `DEFAULT_ENVIRONMENT` | Default environment for assets | `production` |

## Pagination

| Variable | Description | Default |
|----------|-------------|---------|
| `PAGINATION_LIMIT_DEFAULT` | Default page size | `50` |
| `PAGINATION_LIMIT_MAX` | Maximum page size | `100` |

## Impact Analysis

| Variable | Description | Default |
|----------|-------------|---------|
| `IMPACT_DEPTH_DEFAULT` | Default dependency depth | `5` |
| `IMPACT_DEPTH_MAX` | Maximum dependency depth | `10` |

## Proposals

| Variable | Description | Default |
|----------|-------------|---------|
| `PROPOSAL_DEFAULT_EXPIRATION_DAYS` | Days until proposals expire | `30` |
| `PROPOSAL_AUTO_EXPIRE_ENABLED` | Enable automatic proposal expiration | `true` |

## Database Connection Pool

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_POOL_SIZE` | Base connection pool size | `20` |
| `DB_MAX_OVERFLOW` | Additional connections under load | `10` |
| `DB_POOL_TIMEOUT` | Connection wait timeout (seconds) | `30` |
| `DB_POOL_RECYCLE` | Connection recycle time (seconds) | `3600` |

## Repo Sync

| Variable | Description | Default |
|----------|-------------|---------|
| `TESSERA_REPO_DIR` | Directory for cloned repositories | `./data/repos` |
| `TESSERA_GIT_TOKEN` | Git auth token for private repos | None |
| `TESSERA_SYNC_INTERVAL` | Background worker poll interval in seconds | `60` |
| `TESSERA_REPO_MAX_SIZE_MB` | Maximum clone size in megabytes | `500` |
| `TESSERA_GIT_TIMEOUT` | Git operation timeout in seconds | `120` |
| `TESSERA_SYNC_TIMEOUT` | Overall sync operation timeout in seconds | `600` |
| `TESSERA_SYNC_CONCURRENCY` | Max repos to sync concurrently | `4` |

## OTEL Dependency Discovery

| Variable | Description | Default |
|----------|-------------|---------|
| `TESSERA_OTEL_ENABLED` | Enable OTEL-based dependency discovery | `false` |
| `TESSERA_OTEL_POLL_INTERVAL` | Default polling interval in seconds for OTEL backends | `3600` |
| `TESSERA_OTEL_MIN_CONFIDENCE` | Minimum confidence score to create an OTEL-discovered dependency | `0.3` |
| `TESSERA_OTEL_STALE_MULTIPLIER` | Mark dependency stale after N * lookback_seconds without observation | `3` |

## Example `.env` File

```bash
# Environment
ENVIRONMENT=production

# Database
DATABASE_URL=postgresql+asyncpg://tessera:tessera@localhost:5432/tessera

# Security
SESSION_SECRET_KEY=your-super-secret-key-at-least-32-characters-long
BOOTSTRAP_API_KEY=tsk_bootstrap_key_for_initial_setup

# Webhooks (optional)
WEBHOOK_URL=https://your-service.com/webhooks/tessera
WEBHOOK_SECRET=your-webhook-signing-secret

# Redis caching (optional)
REDIS_URL=redis://localhost:6379/0

# Slack notifications (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WRITE=100/minute

# Proposals
PROPOSAL_DEFAULT_EXPIRATION_DAYS=30
PROPOSAL_AUTO_EXPIRE_ENABLED=true
```

## Docker Compose Override

For local development, create `docker-compose.override.yml`:

```yaml
services:
  api:
    environment:
      - ENVIRONMENT=development
      - AUTH_DISABLED=true
    volumes:
      - ./src:/app/src
```

## Production Recommendations

1. **Use strong secrets**: Generate `SESSION_SECRET_KEY` with:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Enable HTTPS**: Use a reverse proxy (nginx, Caddy) with TLS

3. **Set up Redis**: For caching in multi-instance deployments

4. **Configure backups**: Regular PostgreSQL backups

5. **Set resource limits**: Configure `MAX_SCHEMA_SIZE_BYTES` based on your needs

6. **Enable rate limiting**: Keep `RATE_LIMIT_ENABLED=true` in production

7. **Secure webhooks**: Always set `WEBHOOK_SECRET` for HMAC signing

8. **Monitor logs**: Tessera logs to stdout in JSON format
