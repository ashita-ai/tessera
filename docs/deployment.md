# Deployment Guide

This guide covers deploying Tessera from local development to production Kubernetes clusters.

## Quick Reference

| Deployment | Best For | Complexity |
|------------|----------|------------|
| [Docker Compose](#docker-compose) | Local dev, small teams | Low |
| [Single Server](#single-server-docker) | MVPs, demos | Low |
| [Kubernetes](#kubernetes) | Production, scale | Medium |
| [Helm](#helm-chart) | GitOps, multi-env | Medium |

---

## Docker Compose

The fastest way to run Tessera with all dependencies.

### Start Services

```bash
# Clone and start
git clone https://github.com/ashita-ai/tessera.git
cd tessera
docker compose up -d

# Verify
curl http://localhost:8000/health
```

### Services

| Service | Port | Purpose |
|---------|------|---------|
| api | 8000 | Tessera API |
| db | 5432 | PostgreSQL 16 |
| redis | 6379 | Caching |
| webhook-receiver | 5555 | Dev webhook testing |

### Configuration

Override settings via environment:

```bash
# .env.local
BOOTSTRAP_API_KEY=your-admin-key
ENVIRONMENT=development
```

```bash
docker compose --env-file .env.local up -d
```

### Data Persistence

Volumes persist across restarts:
- `postgres_data`: Database files
- `redis_data`: Cache data

Reset everything:
```bash
docker compose down -v  # -v removes volumes
docker compose up -d
```

---

## Single Server (Docker)

Deploy Tessera with an external database.

### Prerequisites

- Docker installed
- PostgreSQL 14+ accessible
- Redis 6+ (optional, for caching)

### Build and Run

```bash
# Build image
docker build -t tessera:latest .

# Run with external database
docker run -d \
  --name tessera \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@db-host:5432/tessera \
  -e REDIS_URL=redis://redis-host:6379/0 \
  -e BOOTSTRAP_API_KEY=your-secure-key \
  -e ENVIRONMENT=production \
  tessera:latest
```

### Health Checks

```bash
# Liveness (app running)
curl http://localhost:8000/health/live

# Readiness (database connected)
curl http://localhost:8000/health/ready
```

---

## Kubernetes

Production deployment with horizontal scaling.

### Prerequisites

- Kubernetes 1.24+
- kubectl configured
- PostgreSQL (managed or self-hosted)
- Redis (managed or self-hosted)
- Container registry access

### Namespace and Secrets

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tessera
---
# secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: tessera-secrets
  namespace: tessera
type: Opaque
stringData:
  DATABASE_URL: postgresql+asyncpg://user:password@postgres:5432/tessera
  REDIS_URL: redis://redis:6379/0
  BOOTSTRAP_API_KEY: your-secure-bootstrap-key
```

```bash
kubectl apply -f namespace.yaml
kubectl apply -f secrets.yaml
```

### ConfigMap

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tessera-config
  namespace: tessera
data:
  ENVIRONMENT: "production"
  API_HOST: "0.0.0.0"
  API_PORT: "8000"
  RATE_LIMIT_ENABLED: "true"
  RATE_LIMIT_READ: "1000/minute"
  RATE_LIMIT_WRITE: "100/minute"
  CORS_ORIGINS: "https://your-domain.com"
  DB_POOL_SIZE: "20"
  DB_MAX_OVERFLOW: "10"
```

### Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tessera
  namespace: tessera
  labels:
    app: tessera
spec:
  replicas: 3
  selector:
    matchLabels:
      app: tessera
  template:
    metadata:
      labels:
        app: tessera
    spec:
      containers:
        - name: tessera
          image: your-registry/tessera:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: tessera-config
            - secretRef:
                name: tessera-secrets
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
```

### Service

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: tessera
  namespace: tessera
spec:
  selector:
    app: tessera
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
```

### Ingress

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tessera
  namespace: tessera
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - tessera.your-domain.com
      secretName: tessera-tls
  rules:
    - host: tessera.your-domain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: tessera
                port:
                  number: 80
```

### Apply All

```bash
kubectl apply -f namespace.yaml
kubectl apply -f secrets.yaml
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
```

### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: tessera
  namespace: tessera
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tessera
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

---

## Helm Chart

For GitOps workflows and multi-environment deployments.

### Chart Structure

```
helm/tessera/
├── Chart.yaml
├── values.yaml
├── values-staging.yaml
├── values-production.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    ├── secret.yaml
    ├── hpa.yaml
    └── _helpers.tpl
```

### Chart.yaml

```yaml
apiVersion: v2
name: tessera
description: Data contract coordination for warehouses
version: 0.1.0
appVersion: "0.1.0"
```

### values.yaml

```yaml
replicaCount: 2

image:
  repository: your-registry/tessera
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: true
  className: nginx
  host: tessera.example.com
  tls: true

resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilization: 70

config:
  environment: production
  rateLimitEnabled: true
  dbPoolSize: 20

secrets:
  # Set via --set or external secret management
  databaseUrl: ""
  redisUrl: ""
  bootstrapApiKey: ""
```

### Installation

```bash
# Install
helm install tessera ./helm/tessera \
  --namespace tessera \
  --create-namespace \
  --set secrets.databaseUrl=postgresql+asyncpg://user:pass@host:5432/db \
  --set secrets.bootstrapApiKey=your-key

# Upgrade
helm upgrade tessera ./helm/tessera \
  --namespace tessera \
  --set image.tag=v1.2.0

# Environment-specific
helm install tessera ./helm/tessera \
  -f values-production.yaml \
  --namespace tessera-prod
```

---

## Environment Variables

Complete reference for all configuration options.

### Core Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | `development`, `staging`, `production` | `development` |
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `REDIS_URL` | Redis connection string | Optional |
| `API_HOST` | Bind address | `0.0.0.0` |
| `API_PORT` | Listen port | `8000` |

### Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_DISABLED` | Skip auth (dev only) | `false` |
| `BOOTSTRAP_API_KEY` | Initial admin key | Required for setup |

### Security

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Allowed origins (comma-separated) | `*` in dev |
| `CORS_ALLOW_METHODS` | Allowed HTTP methods | `GET,POST,PATCH,DELETE,OPTIONS` |

### Rate Limiting

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `RATE_LIMIT_READ` | Read endpoint limit | `1000/minute` |
| `RATE_LIMIT_WRITE` | Write endpoint limit | `100/minute` |
| `RATE_LIMIT_ADMIN` | Admin endpoint limit | `50/minute` |
| `RATE_LIMIT_GLOBAL` | Global fallback | `5000/minute` |

### Database Pool

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_POOL_SIZE` | Connection pool size | `20` |
| `DB_MAX_OVERFLOW` | Max extra connections | `10` |
| `DB_POOL_TIMEOUT` | Connection timeout (seconds) | `30` |
| `DB_POOL_RECYCLE` | Recycle connections after (seconds) | `3600` |

### Caching

| Variable | Description | Default |
|----------|-------------|---------|
| `CACHE_TTL` | Default cache TTL (seconds) | `300` |
| `CACHE_TTL_CONTRACT` | Contract cache TTL | `600` |
| `CACHE_TTL_ASSET` | Asset cache TTL | `300` |
| `CACHE_TTL_TEAM` | Team cache TTL | `300` |
| `CACHE_TTL_SCHEMA` | Schema cache TTL | `3600` |

### Resource Limits

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_SCHEMA_SIZE_BYTES` | Max schema payload size | `1000000` |
| `MAX_SCHEMA_PROPERTIES` | Max properties per schema | `1000` |
| `MAX_FQN_LENGTH` | Max asset FQN length | `1000` |
| `MAX_TEAM_NAME_LENGTH` | Max team name length | `255` |

### Webhooks

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBHOOK_URL` | Webhook endpoint URL | Optional |
| `WEBHOOK_SECRET` | Signing secret for webhooks | Optional |

---

## Database Setup

### PostgreSQL

Tessera uses three schemas: `core`, `workflow`, and `audit`.

**Managed PostgreSQL (recommended):**
- AWS RDS, Google Cloud SQL, or Azure Database for PostgreSQL
- Enable SSL connections in production
- Configure automated backups

**Connection String:**
```
postgresql+asyncpg://user:password@host:5432/tessera?sslmode=require
```

### Migrations

Tessera uses Alembic for schema migrations.

```bash
# Run migrations
alembic upgrade head

# Generate new migration
alembic revision --autogenerate -m "description"

# Check current version
alembic current
```

### Initial Bootstrap

1. Start Tessera with `BOOTSTRAP_API_KEY` set
2. Use the bootstrap key to create your first team and API key:

```bash
# Create admin team
curl -X POST http://localhost:8000/api/v1/teams \
  -H "X-API-Key: $BOOTSTRAP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Platform"}'

# Create admin API key
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "X-API-Key: $BOOTSTRAP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "admin", "scopes": ["read", "write", "admin"]}'
```

3. Store the returned API key securely
4. Remove `BOOTSTRAP_API_KEY` from production config

---

## Security Checklist

### Pre-Production

- [ ] **TLS enabled** - All traffic over HTTPS
- [ ] **BOOTSTRAP_API_KEY removed** - Not set in production
- [ ] **AUTH_DISABLED=false** - Authentication enforced
- [ ] **CORS restricted** - Only allowed origins listed
- [ ] **Rate limiting enabled** - Prevents abuse
- [ ] **Database credentials rotated** - Changed from defaults
- [ ] **Secrets in secret manager** - Not in env files or code

### Network

- [ ] **Database not public** - Only accessible from app subnet
- [ ] **Redis not public** - Internal network only
- [ ] **Ingress has WAF** - Web application firewall
- [ ] **Pod security policies** - Restrict container capabilities

### Monitoring

- [ ] **Health checks configured** - Liveness and readiness probes
- [ ] **Metrics exported** - Prometheus or similar
- [ ] **Audit logging enabled** - Track all changes
- [ ] **Alerts configured** - Error rates, latency, availability

---

## Monitoring

### Prometheus Metrics

Tessera exposes standard FastAPI/Starlette metrics. Add a ServiceMonitor for Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: tessera
  namespace: tessera
spec:
  selector:
    matchLabels:
      app: tessera
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### Recommended Alerts

```yaml
# alerts.yaml (PrometheusRule)
groups:
  - name: tessera
    rules:
      - alert: TesseraHighErrorRate
        expr: |
          sum(rate(http_requests_total{app="tessera",status=~"5.."}[5m]))
          / sum(rate(http_requests_total{app="tessera"}[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on Tessera API"

      - alert: TesseraHighLatency
        expr: |
          histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{app="tessera"}[5m])) by (le)) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High latency on Tessera API (p95 > 1s)"

      - alert: TesseraDatabaseDown
        expr: probe_success{job="tessera-db"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Tessera database unreachable"
```

### Grafana Dashboard

Key panels to include:
- Request rate by endpoint
- Error rate by status code
- Latency percentiles (p50, p95, p99)
- Database connection pool usage
- Cache hit rate (if using Redis)
- Active proposals and pending acknowledgments

---

## Scaling Considerations

### Horizontal Scaling

Tessera is stateless - scale horizontally by adding replicas:

```bash
kubectl scale deployment tessera --replicas=5 -n tessera
```

### Database Connections

Each Tessera instance maintains a connection pool. With defaults:
- Pool size: 20
- Max overflow: 10
- **Max per instance: 30 connections**

For 5 replicas, ensure PostgreSQL supports 150+ connections:
```sql
ALTER SYSTEM SET max_connections = 200;
```

### Redis

Redis is optional but recommended for:
- Caching frequently accessed data
- Rate limiting across instances
- Session storage (future)

### Load Testing

Before production, verify capacity:
```bash
# Install k6
brew install k6

# Run load test
k6 run --vus 50 --duration 5m load-test.js
```

---

## Disaster Recovery

### Backup Strategy

**PostgreSQL:**
```bash
# Logical backup (small databases)
pg_dump -h host -U user tessera > backup.sql

# Physical backup (large databases)
pg_basebackup -h host -U replication -D /backups/tessera
```

**Managed services:**
- Enable automated backups (daily)
- Configure point-in-time recovery
- Test restoration quarterly

### Recovery Procedures

1. **Application failure**: Kubernetes automatically restarts pods
2. **Database failure**: Restore from backup, replay WAL logs
3. **Complete cluster failure**:
   - Restore database from backup
   - Redeploy Tessera (stateless)
   - Verify data integrity

### High Availability

For zero-downtime requirements:
- **Database**: Use managed HA (RDS Multi-AZ, Cloud SQL HA)
- **Redis**: Redis Sentinel or managed Redis with replication
- **Application**: Multiple replicas across availability zones

```yaml
# Pod anti-affinity for zone distribution
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app: tessera
          topologyKey: topology.kubernetes.io/zone
```

---

## Troubleshooting

### Common Issues

**"Database connection refused"**
- Verify DATABASE_URL is correct
- Check network connectivity to database
- Ensure database is running and accepting connections

**"Redis connection failed"**
- Redis is optional - app works without it (no caching)
- Verify REDIS_URL if caching is needed

**"Unauthorized (401)"**
- Check X-API-Key header is set
- Verify API key exists and is not revoked
- Ensure key has required scope

**"Rate limited (429)"**
- Reduce request frequency
- Request higher limits via admin API key
- Consider caching responses client-side

### Debug Mode

For troubleshooting, enable debug logging:
```bash
docker run -e LOG_LEVEL=DEBUG tessera:latest
```

### Health Check Endpoints

```bash
# Is the app running?
curl http://localhost:8000/health/live

# Is the database connected?
curl http://localhost:8000/health/ready

# General health
curl http://localhost:8000/health
```
