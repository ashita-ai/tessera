# Configuration

Tessera is configured via environment variables.

## Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `postgresql+asyncpg://user:pass@localhost:5432/tessera` |
| `SECRET_KEY` | Secret key for session encryption | `your-secret-key-min-32-chars` |

## Optional Variables

### Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `BOOTSTRAP_API_KEY` | Initial admin API key for setup | None |
| `AUTH_DISABLED` | Disable auth (dev only) | `false` |

### Server

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Server bind address | `0.0.0.0` |
| `PORT` | Server port | `8000` |
| `DEBUG` | Enable debug mode | `false` |

### Caching

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection for caching | None (disabled) |
| `CACHE_TTL` | Cache TTL in seconds | `300` |

### Notifications

| Variable | Description | Default |
|----------|-------------|---------|
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications | None |

## Example `.env` File

```bash
# Database
DATABASE_URL=postgresql+asyncpg://tessera:tessera@localhost:5432/tessera

# Security
SECRET_KEY=your-super-secret-key-at-least-32-characters
BOOTSTRAP_API_KEY=tsk_bootstrap_key_for_initial_setup

# Optional: Redis caching
REDIS_URL=redis://localhost:6379/0

# Optional: Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Docker Compose Override

For local development, create `docker-compose.override.yml`:

```yaml
services:
  api:
    environment:
      - DEBUG=true
      - AUTH_DISABLED=true
    volumes:
      - ./src:/app/src
```

## Production Recommendations

1. **Use strong secrets**: Generate `SECRET_KEY` with:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Enable HTTPS**: Use a reverse proxy (nginx, Caddy) with TLS

3. **Set up Redis**: For caching in multi-instance deployments

4. **Configure backups**: Regular PostgreSQL backups

5. **Monitor logs**: Tessera logs to stdout in JSON format
