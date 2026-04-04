"""Enumerations for Tessera entities."""

from enum import StrEnum


class CompatibilityMode(StrEnum):
    """Schema compatibility modes, borrowed from Kafka schema registries."""

    BACKWARD = "backward"  # New schema can read old data (safe for producers)
    FORWARD = "forward"  # Old schema can read new data (safe for consumers)
    FULL = "full"  # Both directions (strictest)
    NONE = "none"  # No compatibility checks, just notify


class ContractStatus(StrEnum):
    """Lifecycle status of a contract."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RegistrationStatus(StrEnum):
    """Status of a consumer registration."""

    ACTIVE = "active"
    MIGRATING = "migrating"
    INACTIVE = "inactive"


class ChangeType(StrEnum):
    """Semantic versioning change classification."""

    PATCH = "patch"  # Bug fixes, no schema changes
    MINOR = "minor"  # Backward-compatible additions
    MAJOR = "major"  # Breaking changes


class ProposalStatus(StrEnum):
    """Status of a breaking change proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class AcknowledgmentResponseType(StrEnum):
    """Consumer response to a proposal."""

    APPROVED = "approved"
    BLOCKED = "blocked"
    MIGRATING = "migrating"


class DependencyType(StrEnum):
    """Type of asset-to-asset dependency."""

    CONSUMES = "consumes"  # Direct data consumption (SELECT FROM)
    REFERENCES = "references"  # Foreign key or reference
    TRANSFORMS = "transforms"  # Data transformation (dbt model)


class APIKeyScope(StrEnum):
    """API key permission scopes."""

    READ = "read"  # GET endpoints, list/view operations
    WRITE = "write"  # POST/PUT/PATCH, create/update operations
    ADMIN = "admin"  # DELETE, API key management, team management


class WebhookDeliveryStatus(StrEnum):
    """Status of a webhook delivery attempt."""

    PENDING = "pending"  # Queued for delivery
    DELIVERED = "delivered"  # Successfully delivered (2xx response)
    FAILED = "failed"  # Failed after all retries
    DEAD_LETTERED = "dead_lettered"  # Circuit breaker open; queued for replay


class GuaranteeMode(StrEnum):
    """How to treat guarantee changes on an asset."""

    NOTIFY = "notify"  # Log changes, notify subscribers (default)
    STRICT = "strict"  # Treat guarantee removal like schema breaking
    IGNORE = "ignore"  # Don't track guarantee changes


class SemverMode(StrEnum):
    """Semantic versioning enforcement mode for assets.

    Controls how version numbers are handled when publishing contracts.
    """

    AUTO = "auto"  # Automatically assign version based on change type (default)
    SUGGEST = "suggest"  # Return suggested version; user can override
    ENFORCE = "enforce"  # Reject if user-provided version doesn't match change type


class GuaranteeChangeSeverity(StrEnum):
    """Severity of a guarantee change."""

    INFO = "info"  # Adding guarantees - never blocking
    WARNING = "warning"  # Relaxing/removing - notify
    BREAKING = "breaking"  # In strict mode, blocks like schema changes


class UserType(StrEnum):
    """Whether a user is a human or a bot."""

    HUMAN = "human"  # Interactive user who logs in via web UI
    BOT = "bot"  # Automated agent that authenticates via API key only


class UserRole(StrEnum):
    """User role for access control."""

    ADMIN = "admin"  # Tessera admin - full access to everything
    TEAM_ADMIN = "team_admin"  # Team admin - can manage their team
    USER = "user"  # Regular user - can view and set notifications


class AuditRunStatus(StrEnum):
    """Status of a data quality audit run."""

    PASSED = "passed"  # All guarantees passed
    FAILED = "failed"  # One or more guarantees failed
    PARTIAL = "partial"  # Some guarantees skipped or errored


class SchemaFormat(StrEnum):
    """Schema format for contracts."""

    JSON_SCHEMA = "json_schema"  # JSON Schema (default)
    AVRO = "avro"  # Apache Avro schema


class InferredDependencyStatus(StrEnum):
    """Status of an inferred dependency."""

    PENDING = "pending"  # Inferred but not yet confirmed by a human
    CONFIRMED = "confirmed"  # Confirmed and promoted to a registration
    REJECTED = "rejected"  # Rejected by team — suppresses future re-inference
    EXPIRED = "expired"  # Stale inference — no recent audit signals


class OtelBackendType(StrEnum):
    """Supported OTEL trace backend types."""

    JAEGER = "jaeger"
    TEMPO = "tempo"
    DATADOG = "datadog"


class DependencySource(StrEnum):
    """How a dependency was discovered."""

    MANUAL = "manual"  # Explicitly registered by a human or API call
    OTEL = "otel"  # Discovered via OTEL trace data
    INFERRED = "inferred"  # Inferred from audit signals


class ResourceType(StrEnum):
    """Type of asset resource.

    Every sync adapter (OpenAPI, GraphQL, gRPC, dbt) converts its native
    format to JSON Schema, then feeds it into the same contract engine.
    The resource type is set during import and used for filtering/display —
    all types follow identical contract, compatibility, and proposal workflows.

    Sync endpoints:
    - OpenAPI: POST /sync/openapi with OpenAPI spec
    - GraphQL: POST /sync/graphql with introspection query result
    - gRPC:    POST /sync/grpc with .proto file content
    - dbt:     POST /sync/dbt with manifest.json
    """

    # API types - IMPLEMENTED via /sync/openapi and /sync/graphql
    API_ENDPOINT = "api_endpoint"  # REST API endpoint (from OpenAPI spec)
    GRAPHQL_QUERY = "graphql_query"  # GraphQL query/mutation (from introspection)

    # gRPC types - IMPLEMENTED via /sync/grpc
    GRPC_SERVICE = "grpc_service"  # gRPC RPC method (from .proto file)

    # Data warehouse types (dbt) - IMPLEMENTED via /sync/dbt
    MODEL = "model"  # dbt model (SELECT-based transformation)
    SOURCE = "source"  # dbt source (external table reference)
    SEED = "seed"  # dbt seed (CSV-loaded reference data)
    SNAPSHOT = "snapshot"  # dbt snapshot (SCD Type 2)

    # Catch-all for manual registration or unrecognized types
    OTHER = "other"
