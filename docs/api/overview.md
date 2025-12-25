# API Reference

Tessera provides a REST API for managing data contracts.

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

All API requests require authentication via Bearer token:

```bash
curl -H "Authorization: Bearer your-api-key" \
  http://localhost:8000/api/v1/assets
```

### API Key Scopes

| Scope | Permissions |
|-------|-------------|
| `read` | Read assets, contracts, proposals |
| `write` | Create/update assets, publish contracts |
| `admin` | Manage teams, users, API keys |

## Response Format

All responses are JSON:

```json
{
  "id": "uuid",
  "field": "value",
  "created_at": "2025-01-15T10:30:00Z"
}
```

### List Responses

List endpoints return paginated results:

```json
{
  "results": [...],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

### Error Responses

```json
{
  "detail": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "field": "optional_field_name"
  }
}
```

## Common HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (missing/invalid auth) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 409 | Conflict (duplicate, etc.) |
| 422 | Unprocessable entity |

## OpenAPI Spec

Interactive API documentation is available at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Endpoints

- [Assets](assets.md) - Manage data assets
- [Contracts](contracts.md) - Publish and manage contracts
- [Teams](teams.md) - Team management
- [Proposals](proposals.md) - Breaking change proposals
