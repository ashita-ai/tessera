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


class ResourceType(StrEnum):
    """Type of asset resource.

    Tessera supports data warehouse assets (via dbt sync) and API assets
    (via OpenAPI/GraphQL sync). The resource type is set during import
    and used for filtering/display - all types follow the same contract
    and compatibility workflows.

    Implemented types have dedicated sync endpoints:
    - dbt: POST /sync/dbt with manifest.json
    - OpenAPI: POST /sync/openapi with OpenAPI spec
    - GraphQL: POST /sync/graphql with introspection query result

    For streaming assets (Kafka), use schema_format="avro" when publishing
    contracts. The resource_type is just metadata - Avro schema validation
    and conversion happens based on schema_format, not resource_type.
    """

    # Data warehouse types (dbt) - IMPLEMENTED via /sync/dbt
    MODEL = "model"  # dbt model (SELECT-based transformation)
    SOURCE = "source"  # dbt source (external table reference)
    SEED = "seed"  # dbt seed (CSV-loaded reference data)
    SNAPSHOT = "snapshot"  # dbt snapshot (SCD Type 2)

    # API types - IMPLEMENTED via /sync/openapi and /sync/graphql
    API_ENDPOINT = "api_endpoint"  # REST API endpoint (from OpenAPI spec)
    GRAPHQL_QUERY = "graphql_query"  # GraphQL query/mutation (from introspection)

    # Streaming types - use schema_format="avro" for Kafka schemas
    # Resource type is metadata only; no special handling
    KAFKA_TOPIC = "kafka_topic"  # Kafka topic with Avro/JSON schema
    EVENT_STREAM = "event_stream"  # Generic event stream (Pulsar, Kinesis, etc.)

    # Catch-all for manual registration or unrecognized types
    OTHER = "other"
