"""OpenAPI specification parser and converter.

Parses OpenAPI 3.x specs and converts them to Tessera assets with JSON Schema contracts.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from tessera.models.enums import ResourceType


class OpenAPIEndpoint(BaseModel):
    """Parsed API endpoint from OpenAPI spec."""

    path: str
    method: str
    operation_id: str | None
    summary: str | None
    description: str | None
    tags: list[str]
    request_schema: dict[str, Any] | None
    response_schema: dict[str, Any] | None
    combined_schema: dict[str, Any]  # Combined request + response for contract
    guarantees: dict[str, Any] | None = None  # Guarantees from x-tessera or inferred


class OpenAPIParseResult(BaseModel):
    """Result of parsing an OpenAPI specification."""

    title: str
    version: str
    description: str | None
    endpoints: list[OpenAPIEndpoint]
    errors: list[str]


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a $ref pointer in the OpenAPI spec."""
    if not ref.startswith("#/"):
        return {}

    parts = ref[2:].split("/")
    current = spec
    for part in parts:
        # Handle URL-encoded characters
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {}
    return current if isinstance(current, dict) else {}


def _expand_refs(spec: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively expand $ref pointers in a schema.

    Stops at depth 10 to prevent infinite recursion.
    """
    if depth > 10:
        return schema

    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return _expand_refs(spec, resolved, depth + 1)

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = _expand_refs(spec, value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                _expand_refs(spec, item, depth + 1) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def _extract_request_schema(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract the request body schema from an operation."""
    request_body = operation.get("requestBody", {})
    if not request_body:
        return None

    content = request_body.get("content", {})

    # Prefer JSON content type
    for content_type in ["application/json", "application/xml", "text/plain"]:
        if content_type in content:
            schema = content[content_type].get("schema", {})
            return _expand_refs(spec, schema)

    # Fall back to first content type
    if content:
        first_content = next(iter(content.values()))
        schema = first_content.get("schema", {})
        return _expand_refs(spec, schema)

    return None


def _extract_response_schema(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any] | None:
    """Extract the primary response schema from an operation.

    Looks for 200, 201, or default response in order of preference.
    """
    responses = operation.get("responses", {})
    if not responses:
        return None

    # Check common success codes in order
    for code in ["200", "201", "default"]:
        if code in responses:
            response = responses[code]
            content = response.get("content", {})

            # Prefer JSON content type
            for content_type in ["application/json", "application/xml", "text/plain"]:
                if content_type in content:
                    schema = content[content_type].get("schema", {})
                    return _expand_refs(spec, schema)

            # Fall back to first content type
            if content:
                first_content = next(iter(content.values()))
                schema = first_content.get("schema", {})
                return _expand_refs(spec, schema)

    return None


def _extract_tessera_guarantees(operation: dict[str, Any]) -> dict[str, Any] | None:
    """Extract x-tessera guarantees from an OpenAPI operation.

    Parses the x-tessera extension from an operation to extract SLA guarantees.

    Example OpenAPI:
        paths:
          /users:
            get:
              x-tessera:
                freshness:
                  max_staleness_minutes: 60
                volume:
                  max_requests_per_minute: 1000
                custom:
                  - type: latency_p99_ms
                    value: 200

    Returns:
        Guarantees dict or None if no x-tessera extension found.
    """
    tessera = operation.get("x-tessera", {})
    if not tessera:
        return None

    guarantees: dict[str, Any] = {}

    if "freshness" in tessera:
        guarantees["freshness"] = tessera["freshness"]
    if "volume" in tessera:
        guarantees["volume"] = tessera["volume"]
    if "custom" in tessera:
        guarantees["custom"] = tessera["custom"]
    if "nullability" in tessera:
        guarantees["nullability"] = tessera["nullability"]
    if "accepted_values" in tessera:
        guarantees["accepted_values"] = tessera["accepted_values"]

    return guarantees if guarantees else None


def _infer_nullability_from_schema(schema: dict[str, Any]) -> dict[str, str]:
    """Infer nullability guarantees from JSON Schema.

    Parses the schema to identify required fields and nullable properties.

    Args:
        schema: A JSON Schema object

    Returns:
        Dict of field_name -> "never" for non-nullable fields
    """
    nullability: dict[str, str] = {}

    if not schema or not isinstance(schema, dict):
        return nullability

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        # Field is required (explicitly in required array)
        if prop_name in required:
            # Also check it's not explicitly nullable
            if prop_schema.get("nullable") is not True:
                nullability[prop_name] = "never"
        # Field has nullable: false explicitly set
        elif prop_schema.get("nullable") is False:
            nullability[prop_name] = "never"

    return nullability


def _merge_guarantees(*guarantee_dicts: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge multiple guarantee dicts, later ones taking precedence.

    Args:
        *guarantee_dicts: Variable number of guarantee dicts (can be None)

    Returns:
        Merged guarantees or None if all inputs are None/empty
    """
    merged: dict[str, Any] = {}

    for g in guarantee_dicts:
        if g:
            for key, value in g.items():
                if key == "nullability" and key in merged:
                    # Merge nullability dicts
                    merged[key] = {**merged[key], **value}
                elif key == "accepted_values" and key in merged:
                    # Merge accepted_values dicts
                    merged[key] = {**merged[key], **value}
                elif key == "custom" and key in merged:
                    # Append custom guarantees
                    merged[key] = merged[key] + value
                else:
                    # Overwrite for other keys
                    merged[key] = value

    return merged if merged else None


def _combine_schemas(
    request_schema: dict[str, Any] | None, response_schema: dict[str, Any] | None
) -> dict[str, Any]:
    """Combine request and response schemas into a single contract schema.

    Creates a JSON Schema with request and response as properties.
    """
    combined: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    if request_schema:
        combined["properties"]["request"] = request_schema

    if response_schema:
        combined["properties"]["response"] = response_schema

    # If we have at least one schema, return the combined schema
    if combined["properties"]:
        return combined

    # If no schemas, return a minimal valid schema
    return {"type": "object"}


def parse_openapi(spec: dict[str, Any]) -> OpenAPIParseResult:
    """Parse an OpenAPI 3.x specification and extract endpoints.

    Args:
        spec: The OpenAPI specification as a dictionary

    Returns:
        OpenAPIParseResult with parsed endpoints and any errors
    """
    errors: list[str] = []
    endpoints: list[OpenAPIEndpoint] = []

    # Extract basic info
    info = spec.get("info", {})
    title = info.get("title", "Untitled API")
    version = info.get("version", "1.0.0")
    description = info.get("description")

    # Validate OpenAPI version
    openapi_version = spec.get("openapi", "")
    if not openapi_version.startswith("3."):
        errors.append(f"Only OpenAPI 3.x is supported, found: {openapi_version or 'unknown'}")
        return OpenAPIParseResult(
            title=title,
            version=version,
            description=description,
            endpoints=[],
            errors=errors,
        )

    # Parse paths
    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        # Handle path-level parameters (shared across all methods)
        for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
            if method not in path_item:
                continue

            operation = path_item[method]
            if not isinstance(operation, dict):
                continue

            try:
                operation_id = operation.get("operationId")
                summary = operation.get("summary")
                op_description = operation.get("description")
                tags = operation.get("tags", [])

                request_schema = _extract_request_schema(spec, operation)
                response_schema = _extract_response_schema(spec, operation)
                combined_schema = _combine_schemas(request_schema, response_schema)

                # Extract guarantees from x-tessera extension
                explicit_guarantees = _extract_tessera_guarantees(operation)

                # Infer nullability from schemas
                inferred_nullability: dict[str, str] = {}
                if request_schema:
                    inferred_nullability.update(_infer_nullability_from_schema(request_schema))
                if response_schema:
                    inferred_nullability.update(_infer_nullability_from_schema(response_schema))

                # Build inferred guarantees
                inferred_guarantees: dict[str, Any] | None = None
                if inferred_nullability:
                    inferred_guarantees = {"nullability": inferred_nullability}

                # Merge: inferred first, then explicit (explicit wins)
                guarantees = _merge_guarantees(inferred_guarantees, explicit_guarantees)

                endpoints.append(
                    OpenAPIEndpoint(
                        path=path,
                        method=method.upper(),
                        operation_id=operation_id,
                        summary=summary,
                        description=op_description,
                        tags=tags if isinstance(tags, list) else [],
                        request_schema=request_schema,
                        response_schema=response_schema,
                        combined_schema=combined_schema,
                        guarantees=guarantees,
                    )
                )
            except Exception as e:
                errors.append(f"Error parsing {method.upper()} {path}: {e!s}")

    return OpenAPIParseResult(
        title=title,
        version=version,
        description=description,
        endpoints=endpoints,
        errors=errors,
    )


def generate_fqn(api_title: str, path: str, method: str) -> str:
    """Generate a fully qualified name for an API endpoint.

    Format: api.<title>.<method>_<path>
    Example: api.users_api.get_users_by_id

    Args:
        api_title: The API title from the spec
        path: The endpoint path (e.g., /users/{id})
        method: The HTTP method (e.g., GET)

    Returns:
        A valid FQN string
    """
    # Normalize title: lowercase, replace spaces with underscores
    normalized_title = api_title.lower().replace(" ", "_").replace("-", "_")
    # Remove any characters that aren't alphanumeric or underscore
    normalized_title = "".join(c if c.isalnum() or c == "_" else "" for c in normalized_title)
    if not normalized_title:
        normalized_title = "unknown"

    # Normalize path: replace slashes and braces
    normalized_path = path.lower().strip("/")
    normalized_path = normalized_path.replace("/", "_").replace("{", "").replace("}", "")
    normalized_path = "".join(c if c.isalnum() or c == "_" else "_" for c in normalized_path)
    # Remove consecutive underscores
    while "__" in normalized_path:
        normalized_path = normalized_path.replace("__", "_")
    normalized_path = normalized_path.strip("_")
    if not normalized_path:
        normalized_path = "root"

    # Combine with method
    method_lower = method.lower()
    return f"api.{normalized_title}.{method_lower}_{normalized_path}"


class AssetFromOpenAPI(BaseModel):
    """Asset to be created from an OpenAPI endpoint."""

    fqn: str
    resource_type: ResourceType
    metadata: dict[str, Any]
    schema_def: dict[str, Any]
    guarantees: dict[str, Any] | None = None


def endpoints_to_assets(
    result: OpenAPIParseResult, owner_team_id: UUID, environment: str = "production"
) -> list[AssetFromOpenAPI]:
    """Convert parsed OpenAPI endpoints to Tessera asset definitions.

    Args:
        result: The parsed OpenAPI result
        owner_team_id: The team that will own these assets
        environment: The environment for the assets

    Returns:
        List of AssetFromOpenAPI ready to be created
    """
    assets: list[AssetFromOpenAPI] = []

    for endpoint in result.endpoints:
        fqn = generate_fqn(result.title, endpoint.path, endpoint.method)

        metadata = {
            "openapi_source": {
                "api_title": result.title,
                "api_version": result.version,
                "path": endpoint.path,
                "method": endpoint.method,
                "operation_id": endpoint.operation_id,
                "summary": endpoint.summary,
                "description": endpoint.description,
                "tags": endpoint.tags,
            }
        }

        assets.append(
            AssetFromOpenAPI(
                fqn=fqn,
                resource_type=ResourceType.API_ENDPOINT,
                metadata=metadata,
                schema_def=endpoint.combined_schema,
                guarantees=endpoint.guarantees,
            )
        )

    return assets
