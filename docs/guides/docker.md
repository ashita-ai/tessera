# Docker Deployment

Deploy Tessera with Docker and Docker Compose.

## Quick Start

```bash
git clone https://github.com/ashita-ai/tessera.git
cd tessera
docker compose up -d
```

This starts:
- Tessera API on port 8000
- PostgreSQL on port 5432

## Docker Compose Configuration

### Basic Setup

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://tessera:tessera@db:5432/tessera
      - SECRET_KEY=${SECRET_KEY}
      - BOOTSTRAP_API_KEY=${BOOTSTRAP_API_KEY}
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=tessera
      - POSTGRES_PASSWORD=tessera
      - POSTGRES_DB=tessera
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tessera"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### With Redis Caching

```yaml
services:
  api:
    build: .
    environment:
      - DATABASE_URL=postgresql+asyncpg://tessera:tessera@db:5432/tessera
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - db
      - redis

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=tessera
      - POSTGRES_PASSWORD=tessera
      - POSTGRES_DB=tessera
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### Production Setup

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.prod
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 512M
    environment:
      - DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@db:5432/tessera
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Environment Variables

Create a `.env` file:

```bash
# Required
SECRET_KEY=your-secret-key-at-least-32-characters
BOOTSTRAP_API_KEY=tsk_your_bootstrap_key

# Database
POSTGRES_USER=tessera
POSTGRES_PASSWORD=secure-password
POSTGRES_DB=tessera

# Optional
REDIS_URL=redis://redis:6379/0
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

## Building from Source

```bash
# Build the image
docker build -t tessera:local .

# Run with local build
docker compose -f docker-compose.yml up -d
```

## Database Migrations

Migrations run automatically on startup. To run manually:

```bash
docker compose exec api alembic upgrade head
```

## Logs

```bash
# All services
docker compose logs -f

# Just API
docker compose logs -f api
```

## Backup & Restore

### Backup

```bash
docker compose exec db pg_dump -U tessera tessera > backup.sql
```

### Restore

```bash
cat backup.sql | docker compose exec -T db psql -U tessera tessera
```

## Health Checks

```bash
# API health
curl http://localhost:8000/health
```
