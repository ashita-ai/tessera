"""GraphQL schema introspection parser and converter.

Parses GraphQL introspection responses and SDL schemas, converting them
to Tessera assets with JSON Schema contracts.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from tessera.models.enums import ResourceType


class GraphQLOperation(BaseModel):
    """Parsed GraphQL query or mutation."""

    name: str
    operation_type: str  # "query" or "mutation"
    description: str | None
    args: list[dict[str, Any]]  # List of argument definitions
    return_type: dict[str, Any]  # JSON Schema for return type
    combined_schema: dict[str, Any]  # Combined args + return for contract


class GraphQLParseResult(BaseModel):
    """Result of parsing a GraphQL schema."""

    schema_name: str
    description: str | None
    operations: list[GraphQLOperation]
    types: dict[str, dict[str, Any]]  # Type name -> JSON Schema
    errors: list[str]


# GraphQL scalar to JSON Schema type mapping
SCALAR_MAPPING: dict[str, dict[str, Any]] = {
    "String": {"type": "string"},
    "Int": {"type": "integer"},
    "Float": {"type": "number"},
    "Boolean": {"type": "boolean"},
    "ID": {"type": "string"},
    # Common custom scalars
    "DateTime": {"type": "string", "format": "date-time"},
    "Date": {"type": "string", "format": "date"},
    "Time": {"type": "string", "format": "time"},
    "JSON": {"type": "object"},
    "JSONObject": {"type": "object"},
    "BigInt": {"type": "integer"},
    "Decimal": {"type": "number"},
    "UUID": {"type": "string", "format": "uuid"},
    "URL": {"type": "string", "format": "uri"},
    "Email": {"type": "string", "format": "email"},
}


def _graphql_type_to_json_schema(
    type_ref: dict[str, Any],
    types_map: dict[str, dict[str, Any]],
    depth: int = 0,
) -> tuple[dict[str, Any], bool]:
    """Convert a GraphQL type reference to JSON Schema.

    Returns:
        Tuple of (schema, is_required) where is_required indicates NON_NULL wrapping
    """
    if depth > 10:
        return {"type": "object"}, False

    kind = type_ref.get("kind", "")
    name = type_ref.get("name")
    of_type = type_ref.get("ofType")

    if kind == "NON_NULL":
        # Non-null wrapping - recurse and mark as required
        inner_schema, _ = _graphql_type_to_json_schema(of_type or {}, types_map, depth + 1)
        return inner_schema, True

    if kind == "LIST":
        # List type - wrap in array
        inner_schema, _ = _graphql_type_to_json_schema(of_type or {}, types_map, depth + 1)
        return {"type": "array", "items": inner_schema}, False

    if kind == "SCALAR":
        # Map scalar to JSON Schema type
        return SCALAR_MAPPING.get(name or "", {"type": "string"}), False

    if kind == "ENUM":
        # Enum - get values from types map
        type_def = types_map.get(name or "", {})
        enum_values = type_def.get("enumValues", [])
        if enum_values:
            return {
                "type": "string",
                "enum": [v.get("name") for v in enum_values if v.get("name")],
            }, False
        return {"type": "string"}, False

    if kind in ("OBJECT", "INPUT_OBJECT", "INTERFACE"):
        # Object types - build properties from fields
        type_def = types_map.get(name or "", {})
        fields = type_def.get("fields") or type_def.get("inputFields") or []

        properties: dict[str, Any] = {}
        required: list[str] = []

        for field in fields:
            field_name = field.get("name")
            if not field_name:
                continue
            field_type = field.get("type", {})
            field_schema, is_required = _graphql_type_to_json_schema(
                field_type, types_map, depth + 1
            )
            properties[field_name] = field_schema
            if is_required:
                required.append(field_name)

        result: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        return result, False

    if kind == "UNION":
        # Union type - use anyOf
        type_def = types_map.get(name or "", {})
        possible_types = type_def.get("possibleTypes", [])
        if possible_types:
            any_of: list[dict[str, Any]] = []
            for pt in possible_types:
                pt_schema, _ = _graphql_type_to_json_schema(
                    {"kind": "OBJECT", "name": pt.get("name")},
                    types_map,
                    depth + 1,
                )
                any_of.append(pt_schema)
            return {"anyOf": any_of}, False
        return {"type": "object"}, False

    # Fallback for named types (lookup in types_map)
    if name:
        # Try to resolve from types_map
        type_def = types_map.get(name, {})
        type_kind = type_def.get("kind", "")
        if type_kind:
            return _graphql_type_to_json_schema(
                {"kind": type_kind, "name": name},
                types_map,
                depth + 1,
            )

    return {"type": "object"}, False


def _build_types_map(introspection_types: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a map of type name -> type definition from introspection."""
    types_map: dict[str, dict[str, Any]] = {}
    for type_def in introspection_types:
        name = type_def.get("name")
        if name and not name.startswith("__"):
            types_map[name] = type_def
    return types_map


def _extract_operations(
    type_def: dict[str, Any] | None,
    operation_type: str,
    types_map: dict[str, dict[str, Any]],
) -> list[GraphQLOperation]:
    """Extract operations from Query or Mutation type."""
    if not type_def:
        return []

    operations: list[GraphQLOperation] = []
    fields = type_def.get("fields") or []

    for field in fields:
        name = field.get("name")
        if not name:
            continue

        description = field.get("description")
        args = field.get("args", [])

        # Build args schema
        args_properties: dict[str, Any] = {}
        args_required: list[str] = []
        args_list: list[dict[str, Any]] = []

        for arg in args:
            arg_name = arg.get("name")
            if not arg_name:
                continue
            arg_type = arg.get("type", {})
            arg_schema, is_required = _graphql_type_to_json_schema(arg_type, types_map)
            args_properties[arg_name] = arg_schema
            if is_required:
                args_required.append(arg_name)
            args_list.append(
                {
                    "name": arg_name,
                    "description": arg.get("description"),
                    "type": arg_schema,
                    "required": is_required,
                }
            )

        args_schema: dict[str, Any] = {"type": "object", "properties": args_properties}
        if args_required:
            args_schema["required"] = args_required

        # Build return type schema
        return_type = field.get("type", {})
        return_schema, _ = _graphql_type_to_json_schema(return_type, types_map)

        # Combined schema for contract
        combined: dict[str, Any] = {
            "type": "object",
            "properties": {
                "arguments": args_schema,
                "response": return_schema,
            },
        }

        operations.append(
            GraphQLOperation(
                name=name,
                operation_type=operation_type,
                description=description,
                args=args_list,
                return_type=return_schema,
                combined_schema=combined,
            )
        )

    return operations


def parse_graphql_introspection(introspection: dict[str, Any]) -> GraphQLParseResult:
    """Parse a GraphQL introspection response.

    The introspection should be the result of the standard introspection query:
    { __schema { ... } }

    Args:
        introspection: The introspection response dict with __schema or data.__schema

    Returns:
        GraphQLParseResult with parsed operations and any errors
    """
    errors: list[str] = []
    operations: list[GraphQLOperation] = []

    # Handle different response formats
    # Could be: {"__schema": {...}}, {"data": {"__schema": {...}}}, or just the schema
    schema = introspection.get("__schema")
    if not schema:
        data = introspection.get("data", {})
        schema = data.get("__schema")
    if not schema:
        # Maybe the introspection IS the schema
        if "types" in introspection and "queryType" in introspection:
            schema = introspection

    if not schema:
        errors.append("No __schema found in introspection response")
        return GraphQLParseResult(
            schema_name="unknown",
            description=None,
            operations=[],
            types={},
            errors=errors,
        )

    # Build types map
    introspection_types = schema.get("types", [])
    types_map = _build_types_map(introspection_types)

    # Convert types to JSON Schema
    json_schema_types: dict[str, dict[str, Any]] = {}
    for name, type_def in types_map.items():
        if type_def.get("kind") in ("OBJECT", "INPUT_OBJECT", "INTERFACE", "ENUM"):
            schema_def, _ = _graphql_type_to_json_schema(
                {"kind": type_def.get("kind"), "name": name},
                types_map,
            )
            json_schema_types[name] = schema_def

    # Extract Query operations
    query_type_name = (schema.get("queryType") or {}).get("name")
    if query_type_name:
        query_type = types_map.get(query_type_name)
        operations.extend(_extract_operations(query_type, "query", types_map))

    # Extract Mutation operations
    mutation_type_name = (schema.get("mutationType") or {}).get("name")
    if mutation_type_name:
        mutation_type = types_map.get(mutation_type_name)
        operations.extend(_extract_operations(mutation_type, "mutation", types_map))

    # Get schema description from Query type if available
    schema_description = None
    if query_type_name:
        query_type = types_map.get(query_type_name)
        if query_type:
            schema_description = query_type.get("description")

    # Determine schema name - use the API name if provided, otherwise default
    schema_name = "GraphQL API"
    # Check for common directives or extensions that might have a name
    description = schema.get("description")
    if description and isinstance(description, str):
        schema_name = description[:50]  # Truncate if too long

    return GraphQLParseResult(
        schema_name=schema_name,
        description=schema_description,
        operations=operations,
        types=json_schema_types,
        errors=errors,
    )


def generate_fqn(schema_name: str, operation_name: str, operation_type: str) -> str:
    """Generate a fully qualified name for a GraphQL operation.

    Format: graphql.<schema_name>.<type>_<operation_name>
    Example: graphql.users_api.query_list_users

    Args:
        schema_name: The schema/API name
        operation_name: The operation name (e.g., listUsers)
        operation_type: "query" or "mutation"

    Returns:
        A valid FQN string
    """
    # Normalize schema name: lowercase, replace spaces/hyphens with underscores
    normalized_name = schema_name.lower().replace(" ", "_").replace("-", "_")
    # Remove any characters that aren't alphanumeric or underscore
    normalized_name = "".join(c if c.isalnum() or c == "_" else "" for c in normalized_name)
    # Remove consecutive underscores
    while "__" in normalized_name:
        normalized_name = normalized_name.replace("__", "_")
    normalized_name = normalized_name.strip("_")
    if not normalized_name:
        normalized_name = "unknown"

    # Normalize operation name
    normalized_op = operation_name.lower()
    normalized_op = "".join(c if c.isalnum() or c == "_" else "_" for c in normalized_op)
    while "__" in normalized_op:
        normalized_op = normalized_op.replace("__", "_")
    normalized_op = normalized_op.strip("_")
    if not normalized_op:
        normalized_op = "unknown"

    return f"graphql.{normalized_name}.{operation_type}_{normalized_op}"


class AssetFromGraphQL(BaseModel):
    """Asset to be created from a GraphQL operation."""

    fqn: str
    resource_type: ResourceType
    metadata: dict[str, Any]
    schema_def: dict[str, Any]


def operations_to_assets(
    result: GraphQLParseResult,
    owner_team_id: UUID,
    environment: str = "production",
    schema_name_override: str | None = None,
) -> list[AssetFromGraphQL]:
    """Convert parsed GraphQL operations to Tessera asset definitions.

    Args:
        result: The parsed GraphQL result
        owner_team_id: The team that will own these assets
        environment: The environment for the assets
        schema_name_override: Optional override for the schema name in FQN generation

    Returns:
        List of AssetFromGraphQL ready to be created
    """
    assets: list[AssetFromGraphQL] = []
    schema_name = schema_name_override or result.schema_name

    for op in result.operations:
        fqn = generate_fqn(schema_name, op.name, op.operation_type)

        metadata = {
            "graphql_source": {
                "schema_name": schema_name,
                "schema_description": result.description,
                "operation_name": op.name,
                "operation_type": op.operation_type,
                "description": op.description,
                "arguments": op.args,
            }
        }

        assets.append(
            AssetFromGraphQL(
                fqn=fqn,
                resource_type=ResourceType.GRAPHQL_QUERY,
                metadata=metadata,
                schema_def=op.combined_schema,
            )
        )

    return assets
