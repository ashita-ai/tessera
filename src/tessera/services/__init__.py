"""Business logic services."""

from tessera.services.audit import (
    AuditAction,
    log_contract_published,
    log_event,
    log_guarantees_updated,
    log_proposal_acknowledged,
    log_proposal_approved,
    log_proposal_created,
    log_proposal_force_approved,
    log_proposal_rejected,
)
from tessera.services.graphql import (
    AssetFromGraphQL,
    GraphQLOperation,
    GraphQLParseResult,
    operations_to_assets,
    parse_graphql_introspection,
)
from tessera.services.graphql import (
    generate_fqn as generate_graphql_fqn,
)
from tessera.services.openapi import (
    AssetFromOpenAPI,
    OpenAPIEndpoint,
    OpenAPIParseResult,
    endpoints_to_assets,
    generate_fqn,
    parse_openapi,
)
from tessera.services.schema_diff import (
    BreakingChange,
    SchemaDiff,
    SchemaDiffResult,
    check_compatibility,
    diff_schemas,
)
from tessera.services.schema_validator import (
    SchemaValidationError,
    check_schema_validity,
    validate_json_schema,
    validate_schema_or_raise,
)

__all__ = [
    # Schema diffing
    "BreakingChange",
    "SchemaDiff",
    "SchemaDiffResult",
    "check_compatibility",
    "diff_schemas",
    # Schema validation
    "SchemaValidationError",
    "check_schema_validity",
    "validate_json_schema",
    "validate_schema_or_raise",
    # Audit logging
    "AuditAction",
    "log_event",
    "log_contract_published",
    "log_guarantees_updated",
    "log_proposal_created",
    "log_proposal_acknowledged",
    "log_proposal_approved",
    "log_proposal_force_approved",
    "log_proposal_rejected",
    # OpenAPI parsing
    "AssetFromOpenAPI",
    "OpenAPIEndpoint",
    "OpenAPIParseResult",
    "endpoints_to_assets",
    "generate_fqn",
    "parse_openapi",
    # GraphQL parsing
    "AssetFromGraphQL",
    "GraphQLOperation",
    "GraphQLParseResult",
    "generate_graphql_fqn",
    "operations_to_assets",
    "parse_graphql_introspection",
]
