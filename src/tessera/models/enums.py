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
