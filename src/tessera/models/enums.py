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


class ResourceType(StrEnum):
    """Type of asset resource.

    Supports both data warehouse assets (dbt) and external services (APIs).
    """

    # Data warehouse types (dbt)
    MODEL = "model"  # dbt model
    SOURCE = "source"  # dbt source
    SEED = "seed"  # dbt seed
    SNAPSHOT = "snapshot"  # dbt snapshot

    # API types
    API_ENDPOINT = "api_endpoint"  # REST API endpoint
    GRPC_SERVICE = "grpc_service"  # gRPC service
    GRAPHQL_QUERY = "graphql_query"  # GraphQL query/mutation

    # Other
    EXTERNAL = "external"  # Generic external asset
    UNKNOWN = "unknown"  # Unclassified
