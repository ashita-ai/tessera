"""Protocol Buffer (.proto) parser and converter.

Parses proto3 file content and converts gRPC service definitions to Tessera
assets with JSON Schema contracts. Uses a pure-Python parser (no external
protobuf tooling required).
"""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from tessera.models.enums import ResourceType

# Protobuf scalar type -> JSON Schema mapping per the issue spec.
_SCALAR_TYPE_MAP: dict[str, dict[str, Any]] = {
    "double": {"type": "number"},
    "float": {"type": "number"},
    "int32": {"type": "integer"},
    "int64": {"type": "integer"},
    "uint32": {"type": "integer"},
    "uint64": {"type": "integer"},
    "sint32": {"type": "integer"},
    "sint64": {"type": "integer"},
    "fixed32": {"type": "integer"},
    "fixed64": {"type": "integer"},
    "sfixed32": {"type": "integer"},
    "sfixed64": {"type": "integer"},
    "bool": {"type": "boolean"},
    "string": {"type": "string"},
    "bytes": {"type": "string", "contentEncoding": "base64"},
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ProtoField(BaseModel):
    """A single field inside a protobuf message."""

    name: str
    type_name: str
    field_number: int
    repeated: bool = False
    map_key_type: str | None = None
    map_value_type: str | None = None
    optional: bool = False


class ProtoEnumValue(BaseModel):
    """A single value inside a protobuf enum."""

    name: str
    number: int


class ProtoEnum(BaseModel):
    """A protobuf enum definition."""

    name: str
    values: list[ProtoEnumValue]


class ProtoMessage(BaseModel):
    """A protobuf message definition."""

    name: str
    fields: list[ProtoField]
    nested_messages: list["ProtoMessage"] = []
    nested_enums: list[ProtoEnum] = []


class ProtoRpcMethod(BaseModel):
    """An RPC method inside a gRPC service."""

    name: str
    input_type: str
    output_type: str
    client_streaming: bool = False
    server_streaming: bool = False


class ProtoService(BaseModel):
    """A gRPC service definition."""

    name: str
    methods: list[ProtoRpcMethod]


class GRPCRpcMethod(BaseModel):
    """Fully resolved RPC method with JSON Schema representations."""

    service_name: str
    method_name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    combined_schema: dict[str, Any]
    client_streaming: bool = False
    server_streaming: bool = False


class GRPCParseResult(BaseModel):
    """Result of parsing a .proto file."""

    package: str
    syntax: str
    services: list[ProtoService]
    messages: list[ProtoMessage]
    enums: list[ProtoEnum]
    rpc_methods: list[GRPCRpcMethod]
    errors: list[str]


class AssetFromGRPC(BaseModel):
    """Asset to be created from a gRPC RPC method."""

    fqn: str
    resource_type: ResourceType
    metadata: dict[str, Any]
    schema_def: dict[str, Any]


# ---------------------------------------------------------------------------
# Parser helpers — strip comments and extract blocks
# ---------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_OPTION_RE = re.compile(r"\boption\b[^;]*;")


def _strip_comments(text: str) -> str:
    """Remove C-style and C++-style comments."""
    return _COMMENT_RE.sub("", text)


def _strip_options(text: str) -> str:
    """Remove top-level option statements which we don't need."""
    return _OPTION_RE.sub("", text)


def _find_block(text: str, start: int) -> tuple[str, int]:
    """Find the matching closing brace for an opening brace at *start*.

    Returns the content between braces and the index past the closing brace.
    """
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], len(text)


# ---------------------------------------------------------------------------
# Enum parsing
# ---------------------------------------------------------------------------

_ENUM_VALUE_RE = re.compile(r"(\w+)\s*=\s*(-?\d+)\s*;")


def _parse_enum(name: str, body: str) -> ProtoEnum:
    values: list[ProtoEnumValue] = []
    for m in _ENUM_VALUE_RE.finditer(body):
        values.append(ProtoEnumValue(name=m.group(1), number=int(m.group(2))))
    return ProtoEnum(name=name, values=values)


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

_MAP_FIELD_RE = re.compile(r"map\s*<\s*(\w+)\s*,\s*(\w+)\s*>\s+(\w+)\s*=\s*(\d+)\s*;")
_FIELD_RE = re.compile(r"(repeated|optional)?\s*(\w+(?:\.\w+)*)\s+(\w+)\s*=\s*(\d+)\s*;")
_NESTED_ENUM_RE = re.compile(r"enum\s+(\w+)\s*\{")
_NESTED_MSG_RE = re.compile(r"message\s+(\w+)\s*\{")
_ONEOF_RE = re.compile(r"oneof\s+\w+\s*\{")
_RESERVED_RE = re.compile(r"reserved\s+[^;]+;")


def _parse_message(name: str, body: str) -> ProtoMessage:
    fields: list[ProtoField] = []
    nested_messages: list[ProtoMessage] = []
    nested_enums: list[ProtoEnum] = []

    # Remove reserved statements
    body = _RESERVED_RE.sub("", body)

    # Extract nested enums first (so their body doesn't confuse field parsing)
    remaining = body
    for m in _NESTED_ENUM_RE.finditer(body):
        enum_name = m.group(1)
        brace_pos = body.index("{", m.start())
        enum_body, _ = _find_block(body, brace_pos)
        nested_enums.append(_parse_enum(enum_name, enum_body))
        # blank out the enum in remaining so we don't re-parse its contents
        end_idx = body.index("}", brace_pos) + 1
        remaining = remaining[: m.start()] + " " * (end_idx - m.start()) + remaining[end_idx:]

    # Extract nested messages
    body_for_msgs = remaining
    for m in _NESTED_MSG_RE.finditer(body_for_msgs):
        msg_name = m.group(1)
        brace_pos = body_for_msgs.index("{", m.start())
        msg_body, end_idx = _find_block(body_for_msgs, brace_pos)
        nested_messages.append(_parse_message(msg_name, msg_body))
        remaining = remaining[: m.start()] + " " * (end_idx - m.start()) + remaining[end_idx:]

    # Flatten oneof blocks — treat their fields as regular optional fields.
    # Pad with spaces (length-preserving) so positions from finditer stay valid
    # when there are multiple oneof blocks in the same message.
    oneof_flattened = remaining
    for m in _ONEOF_RE.finditer(remaining):
        brace_pos = remaining.index("{", m.start())
        oneof_body, end = _find_block(remaining, brace_pos)
        padding = (end - m.start()) - len(oneof_body)
        oneof_flattened = (
            oneof_flattened[: m.start()] + oneof_body + " " * padding + oneof_flattened[end:]
        )

    # Parse map fields
    for m in _MAP_FIELD_RE.finditer(oneof_flattened):
        fields.append(
            ProtoField(
                name=m.group(3),
                type_name="map",
                field_number=int(m.group(4)),
                map_key_type=m.group(1),
                map_value_type=m.group(2),
            )
        )

    # Parse regular / repeated / optional fields (skip map lines already handled)
    map_field_names = {f.name for f in fields}
    for m in _FIELD_RE.finditer(oneof_flattened):
        field_name = m.group(3)
        if field_name in map_field_names:
            continue
        modifier = m.group(1) or ""
        fields.append(
            ProtoField(
                name=field_name,
                type_name=m.group(2),
                field_number=int(m.group(4)),
                repeated=modifier == "repeated",
                optional=modifier == "optional",
            )
        )

    return ProtoMessage(
        name=name,
        fields=fields,
        nested_messages=nested_messages,
        nested_enums=nested_enums,
    )


# ---------------------------------------------------------------------------
# Service / RPC parsing
# ---------------------------------------------------------------------------

_RPC_RE = re.compile(
    r"rpc\s+(\w+)\s*\(\s*(stream\s+)?(\w+(?:\.\w+)*)\s*\)"
    r"\s+returns\s*\(\s*(stream\s+)?(\w+(?:\.\w+)*)\s*\)\s*[;{]"
)


def _parse_service(name: str, body: str) -> ProtoService:
    methods: list[ProtoRpcMethod] = []
    for m in _RPC_RE.finditer(body):
        methods.append(
            ProtoRpcMethod(
                name=m.group(1),
                input_type=m.group(3),
                output_type=m.group(5),
                client_streaming=m.group(2) is not None,
                server_streaming=m.group(4) is not None,
            )
        )
    return ProtoService(name=name, methods=methods)


# ---------------------------------------------------------------------------
# Type resolution: protobuf message/enum -> JSON Schema
# ---------------------------------------------------------------------------


def _build_type_index(
    messages: list[ProtoMessage],
    enums: list[ProtoEnum],
    prefix: str = "",
) -> tuple[dict[str, ProtoMessage], dict[str, ProtoEnum]]:
    """Build flat lookup dicts for all messages and enums (including nested)."""
    msg_idx: dict[str, ProtoMessage] = {}
    enum_idx: dict[str, ProtoEnum] = {}

    for msg in messages:
        fq = f"{prefix}.{msg.name}" if prefix else msg.name
        msg_idx[msg.name] = msg
        msg_idx[fq] = msg
        nested_msgs, nested_enums = _build_type_index(msg.nested_messages, msg.nested_enums, fq)
        msg_idx.update(nested_msgs)
        enum_idx.update(nested_enums)

    for enum in enums:
        fq = f"{prefix}.{enum.name}" if prefix else enum.name
        enum_idx[enum.name] = enum
        enum_idx[fq] = enum

    return msg_idx, enum_idx


def _resolve_type(
    type_name: str,
    msg_idx: dict[str, ProtoMessage],
    enum_idx: dict[str, ProtoEnum],
    depth: int = 0,
) -> dict[str, Any]:
    """Convert a protobuf type reference to JSON Schema."""
    if depth > 15:
        return {"type": "object", "description": f"(circular: {type_name})"}

    # Scalar?
    if type_name in _SCALAR_TYPE_MAP:
        return dict(_SCALAR_TYPE_MAP[type_name])

    # Enum?
    if type_name in enum_idx:
        enum = enum_idx[type_name]
        return {
            "type": "string",
            "enum": [v.name for v in enum.values],
        }

    # Message?
    if type_name in msg_idx:
        return _message_to_schema(msg_idx[type_name], msg_idx, enum_idx, depth + 1)

    # Unknown — return a generic object with a note
    return {"type": "object", "description": f"unresolved type: {type_name}"}


def _message_to_schema(
    msg: ProtoMessage,
    msg_idx: dict[str, ProtoMessage],
    enum_idx: dict[str, ProtoEnum],
    depth: int = 0,
) -> dict[str, Any]:
    """Convert a ProtoMessage to a JSON Schema object."""
    properties: dict[str, Any] = {}
    for field in msg.fields:
        if field.map_key_type and field.map_value_type:
            value_schema = _resolve_type(field.map_value_type, msg_idx, enum_idx, depth + 1)
            properties[field.name] = {
                "type": "object",
                "additionalProperties": value_schema,
            }
        elif field.repeated:
            item_schema = _resolve_type(field.type_name, msg_idx, enum_idx, depth + 1)
            properties[field.name] = {"type": "array", "items": item_schema}
        else:
            properties[field.name] = _resolve_type(field.type_name, msg_idx, enum_idx, depth + 1)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    # In proto3 all non-optional fields are implicitly present, so we mark
    # non-optional fields as required.
    required = [f.name for f in msg.fields if not f.optional]
    if required:
        schema["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SYNTAX_RE = re.compile(r'syntax\s*=\s*"(proto[23])"\s*;')
_PACKAGE_RE = re.compile(r"package\s+([\w.]+)\s*;")
_SERVICE_RE = re.compile(r"service\s+(\w+)\s*\{")
_TOP_MSG_RE = re.compile(r"(?<!\w)message\s+(\w+)\s*\{")
_TOP_ENUM_RE = re.compile(r"(?<!\w)enum\s+(\w+)\s*\{")


def parse_proto(proto_content: str) -> GRPCParseResult:
    """Parse a .proto file and extract services, messages, and enums.

    Args:
        proto_content: Raw text content of a .proto file.

    Returns:
        GRPCParseResult with parsed services, messages, resolved RPC methods,
        and any parse errors encountered.
    """
    errors: list[str] = []

    cleaned = _strip_comments(proto_content)
    cleaned = _strip_options(cleaned)

    # Syntax
    syntax_match = _SYNTAX_RE.search(cleaned)
    syntax = syntax_match.group(1) if syntax_match else "proto3"

    # Package
    pkg_match = _PACKAGE_RE.search(cleaned)
    package = pkg_match.group(1) if pkg_match else ""

    # --- Top-level enums ---
    top_enums: list[ProtoEnum] = []
    for m in _TOP_ENUM_RE.finditer(cleaned):
        try:
            brace_pos = cleaned.index("{", m.start())
            body, _ = _find_block(cleaned, brace_pos)
            top_enums.append(_parse_enum(m.group(1), body))
        except Exception as exc:
            errors.append(f"Error parsing enum {m.group(1)}: {exc!s}")

    # --- Top-level messages ---
    # We need to skip enum blocks that might look like message blocks
    enum_ranges: set[int] = set()
    for m in _TOP_ENUM_RE.finditer(cleaned):
        brace_pos = cleaned.index("{", m.start())
        _, end = _find_block(cleaned, brace_pos)
        for i in range(m.start(), end):
            enum_ranges.add(i)

    top_messages: list[ProtoMessage] = []
    for m in _TOP_MSG_RE.finditer(cleaned):
        if m.start() in enum_ranges:
            continue
        try:
            brace_pos = cleaned.index("{", m.start())
            body, _ = _find_block(cleaned, brace_pos)
            top_messages.append(_parse_message(m.group(1), body))
        except Exception as exc:
            errors.append(f"Error parsing message {m.group(1)}: {exc!s}")

    # --- Services ---
    services: list[ProtoService] = []
    for m in _SERVICE_RE.finditer(cleaned):
        try:
            brace_pos = cleaned.index("{", m.start())
            body, _ = _find_block(cleaned, brace_pos)
            services.append(_parse_service(m.group(1), body))
        except Exception as exc:
            errors.append(f"Error parsing service {m.group(1)}: {exc!s}")

    # --- Resolve RPC methods to JSON Schemas ---
    msg_idx, enum_idx = _build_type_index(top_messages, top_enums)

    rpc_methods: list[GRPCRpcMethod] = []
    for svc in services:
        for rpc in svc.methods:
            try:
                input_schema = _resolve_type(rpc.input_type, msg_idx, enum_idx)
                output_schema = _resolve_type(rpc.output_type, msg_idx, enum_idx)
                combined = _combine_schemas(input_schema, output_schema)

                rpc_methods.append(
                    GRPCRpcMethod(
                        service_name=svc.name,
                        method_name=rpc.name,
                        input_schema=input_schema,
                        output_schema=output_schema,
                        combined_schema=combined,
                        client_streaming=rpc.client_streaming,
                        server_streaming=rpc.server_streaming,
                    )
                )
            except Exception as exc:
                errors.append(f"Error resolving {svc.name}.{rpc.name}: {exc!s}")

    return GRPCParseResult(
        package=package,
        syntax=syntax,
        services=services,
        messages=top_messages,
        enums=top_enums,
        rpc_methods=rpc_methods,
        errors=errors,
    )


def _combine_schemas(
    request_schema: dict[str, Any],
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    """Combine request and response schemas into a single contract schema."""
    combined: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    if request_schema:
        combined["properties"]["request"] = request_schema
        combined["required"].append("request")

    if response_schema:
        combined["properties"]["response"] = response_schema
        combined["required"].append("response")

    if not combined["required"]:
        del combined["required"]

    return combined


def generate_fqn(package: str, service_name: str, method_name: str) -> str:
    """Generate a fully qualified name for a gRPC RPC method.

    Format: grpc.<sanitized_package>.<service>.<method>
    Example: grpc.users.UserService.GetUser

    Package dots are replaced with underscores to prevent FQN injection
    (e.g., ``com.example.api`` becomes ``com_example_api``).
    Service and method names are validated to contain only safe characters.

    Args:
        package: The protobuf package name (dots allowed, will be sanitized).
        service_name: The gRPC service name (no dots/slashes).
        method_name: The RPC method name (no dots/slashes).

    Returns:
        A valid FQN string.

    Raises:
        FQNComponentError: If any component contains unsafe characters.
    """
    from tessera.services.fqn import sanitize_proto_package, validate_fqn_component

    validate_fqn_component(service_name, "gRPC service name")
    validate_fqn_component(method_name, "gRPC method name")

    parts = ["grpc"]
    sanitized_package = sanitize_proto_package(package)
    if sanitized_package:
        parts.append(sanitized_package)
    parts.append(service_name)
    parts.append(method_name)
    return ".".join(parts)


def rpc_methods_to_assets(
    result: GRPCParseResult,
    owner_team_id: UUID,
    environment: str = "production",
) -> list[AssetFromGRPC]:
    """Convert parsed gRPC RPC methods to Tessera asset definitions.

    Args:
        result: The parsed proto result.
        owner_team_id: The team that will own these assets.
        environment: The environment for the assets.

    Returns:
        List of AssetFromGRPC ready to be created.
    """
    assets: list[AssetFromGRPC] = []

    for rpc in result.rpc_methods:
        fqn = generate_fqn(result.package, rpc.service_name, rpc.method_name)

        metadata: dict[str, Any] = {
            "grpc_source": {
                "package": result.package,
                "syntax": result.syntax,
                "service": rpc.service_name,
                "method": rpc.method_name,
                "client_streaming": rpc.client_streaming,
                "server_streaming": rpc.server_streaming,
            }
        }

        assets.append(
            AssetFromGRPC(
                fqn=fqn,
                resource_type=ResourceType.GRPC_SERVICE,
                metadata=metadata,
                schema_def=rpc.combined_schema,
            )
        )

    return assets
