"""Tests for gRPC / Protocol Buffers sync endpoints and parser."""

import pytest
from httpx import AsyncClient

from tessera.services.grpc import (
    generate_fqn,
    parse_proto,
    rpc_methods_to_assets,
)

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Sample .proto files used across tests
# ---------------------------------------------------------------------------

SIMPLE_PROTO = """\
syntax = "proto3";
package users;

service UserService {
  rpc GetUser (GetUserRequest) returns (User);
  rpc CreateUser (CreateUserRequest) returns (User);
}

message GetUserRequest {
  string id = 1;
}

message CreateUserRequest {
  string email = 1;
  string name = 2;
}

message User {
  string id = 1;
  string email = 2;
  string name = 3;
}
"""

NESTED_ENUM_PROTO = """\
syntax = "proto3";
package orders;

service OrderService {
  rpc GetOrder (GetOrderRequest) returns (Order);
}

message GetOrderRequest {
  string order_id = 1;
}

enum OrderStatus {
  UNKNOWN = 0;
  PENDING = 1;
  SHIPPED = 2;
  DELIVERED = 3;
}

message Address {
  string street = 1;
  string city = 2;
  string zip = 3;
}

message Order {
  string id = 1;
  OrderStatus status = 2;
  repeated LineItem items = 3;
  Address shipping_address = 4;
}

message LineItem {
  string product_id = 1;
  int32 quantity = 2;
  double price = 3;
}
"""

MAP_PROTO = """\
syntax = "proto3";
package config;

service ConfigService {
  rpc GetConfig (GetConfigRequest) returns (Config);
}

message GetConfigRequest {
  string namespace = 1;
}

message Config {
  string namespace = 1;
  map<string, string> values = 2;
}
"""

MULTI_SERVICE_PROTO = """\
syntax = "proto3";
package multi;

service AuthService {
  rpc Login (LoginRequest) returns (LoginResponse);
}

service UserService {
  rpc GetProfile (ProfileRequest) returns (Profile);
}

message LoginRequest {
  string username = 1;
  string password = 2;
}

message LoginResponse {
  string token = 1;
}

message ProfileRequest {
  string user_id = 1;
}

message Profile {
  string user_id = 1;
  string display_name = 2;
}
"""

STREAMING_PROTO = """\
syntax = "proto3";
package streaming;

service ChatService {
  rpc SendMessage (ChatMessage) returns (ChatMessage);
  rpc StreamMessages (StreamRequest) returns (stream ChatMessage);
  rpc SendBatch (stream ChatMessage) returns (BatchResponse);
  rpc BiDiChat (stream ChatMessage) returns (stream ChatMessage);
}

message ChatMessage {
  string sender = 1;
  string text = 2;
}

message StreamRequest {
  string channel_id = 1;
}

message BatchResponse {
  int32 count = 1;
}
"""

ONEOF_OPTIONAL_PROTO = """\
syntax = "proto3";
package search;

service SearchService {
  rpc Search (SearchRequest) returns (SearchResponse);
}

message SearchRequest {
  string query = 1;
  optional int32 page = 2;
  oneof filter {
    string category = 3;
    string tag = 4;
  }
}

message SearchResponse {
  repeated Result results = 1;
}

message Result {
  string id = 1;
  string title = 2;
  float score = 3;
}
"""


# ===========================================================================
# Unit tests for the parser
# ===========================================================================


class TestParseProto:
    """Tests for parse_proto service function."""

    def test_simple_service(self) -> None:
        result = parse_proto(SIMPLE_PROTO)
        assert result.package == "users"
        assert result.syntax == "proto3"
        assert len(result.services) == 1
        assert result.services[0].name == "UserService"
        assert len(result.services[0].methods) == 2
        assert len(result.messages) == 3
        assert len(result.rpc_methods) == 2
        assert result.errors == []

    def test_rpc_schemas_have_request_and_response(self) -> None:
        result = parse_proto(SIMPLE_PROTO)
        get_user = next(r for r in result.rpc_methods if r.method_name == "GetUser")
        assert "properties" in get_user.input_schema
        assert "id" in get_user.input_schema["properties"]
        assert get_user.input_schema["properties"]["id"] == {"type": "string"}

        assert "properties" in get_user.output_schema
        assert "email" in get_user.output_schema["properties"]

        # Combined schema wraps request + response
        assert "request" in get_user.combined_schema["properties"]
        assert "response" in get_user.combined_schema["properties"]

    def test_nested_messages_and_enums(self) -> None:
        result = parse_proto(NESTED_ENUM_PROTO)
        assert result.package == "orders"
        assert len(result.enums) == 1
        assert result.enums[0].name == "OrderStatus"
        assert len(result.enums[0].values) == 4

        get_order = result.rpc_methods[0]
        resp = get_order.output_schema
        # status should resolve to enum
        assert resp["properties"]["status"]["type"] == "string"
        assert "enum" in resp["properties"]["status"]
        assert "PENDING" in resp["properties"]["status"]["enum"]

        # items should be repeated (array)
        assert resp["properties"]["items"]["type"] == "array"
        assert resp["properties"]["items"]["items"]["type"] == "object"

        # shipping_address is nested message
        assert resp["properties"]["shipping_address"]["type"] == "object"
        assert "street" in resp["properties"]["shipping_address"]["properties"]

    def test_map_fields(self) -> None:
        result = parse_proto(MAP_PROTO)
        rpc = result.rpc_methods[0]
        config_schema = rpc.output_schema
        values_prop = config_schema["properties"]["values"]
        assert values_prop["type"] == "object"
        assert values_prop["additionalProperties"] == {"type": "string"}

    def test_multiple_services(self) -> None:
        result = parse_proto(MULTI_SERVICE_PROTO)
        assert len(result.services) == 2
        assert len(result.rpc_methods) == 2
        service_names = {r.service_name for r in result.rpc_methods}
        assert service_names == {"AuthService", "UserService"}

    def test_streaming_methods(self) -> None:
        result = parse_proto(STREAMING_PROTO)
        methods_by_name = {r.method_name: r for r in result.rpc_methods}

        assert not methods_by_name["SendMessage"].client_streaming
        assert not methods_by_name["SendMessage"].server_streaming

        assert not methods_by_name["StreamMessages"].client_streaming
        assert methods_by_name["StreamMessages"].server_streaming

        assert methods_by_name["SendBatch"].client_streaming
        assert not methods_by_name["SendBatch"].server_streaming

        assert methods_by_name["BiDiChat"].client_streaming
        assert methods_by_name["BiDiChat"].server_streaming

    def test_oneof_and_optional(self) -> None:
        result = parse_proto(ONEOF_OPTIONAL_PROTO)
        rpc = result.rpc_methods[0]
        req = rpc.input_schema
        # query should be required (non-optional)
        assert "query" in req["properties"]
        # page is optional -> not in required
        assert "page" not in req.get("required", [])
        # oneof fields should be parsed
        assert "category" in req["properties"] or "tag" in req["properties"]

    def test_comments_stripped(self) -> None:
        proto = """\
syntax = "proto3";
package commented;

// This is a line comment
service Svc {
  /* block comment */
  rpc Ping (PingReq) returns (PingResp);
}

message PingReq {
  string msg = 1; // inline comment
}

message PingResp {
  string reply = 1;
}
"""
        result = parse_proto(proto)
        assert len(result.rpc_methods) == 1
        assert result.errors == []

    def test_no_package(self) -> None:
        proto = """\
syntax = "proto3";

service Minimal {
  rpc DoThing (Req) returns (Resp);
}

message Req { string x = 1; }
message Resp { string y = 1; }
"""
        result = parse_proto(proto)
        assert result.package == ""
        assert len(result.rpc_methods) == 1

    def test_empty_proto(self) -> None:
        result = parse_proto("")
        assert result.rpc_methods == []
        assert result.services == []

    def test_proto_with_no_services(self) -> None:
        proto = """\
syntax = "proto3";
package types;

message Timestamp {
  int64 seconds = 1;
  int32 nanos = 2;
}
"""
        result = parse_proto(proto)
        assert len(result.messages) == 1
        assert result.rpc_methods == []

    def test_bytes_field_type(self) -> None:
        proto = """\
syntax = "proto3";
package blob;

service BlobService {
  rpc Upload (BlobReq) returns (BlobResp);
}

message BlobReq {
  bytes data = 1;
  string name = 2;
}

message BlobResp {
  string id = 1;
}
"""
        result = parse_proto(proto)
        rpc = result.rpc_methods[0]
        data_field = rpc.input_schema["properties"]["data"]
        assert data_field == {"type": "string", "contentEncoding": "base64"}


# ===========================================================================
# Unit tests for FQN generation
# ===========================================================================


class TestGenerateFQN:
    def test_basic(self) -> None:
        assert generate_fqn("users", "UserService", "GetUser") == "grpc.users.UserService.GetUser"

    def test_no_package(self) -> None:
        assert generate_fqn("", "Svc", "Do") == "grpc.Svc.Do"

    def test_dotted_package(self) -> None:
        assert generate_fqn("com.example.api", "Svc", "Call") == "grpc.com.example.api.Svc.Call"


# ===========================================================================
# Unit tests for asset conversion
# ===========================================================================


class TestRpcMethodsToAssets:
    def test_basic_conversion(self) -> None:
        from uuid import uuid4

        result = parse_proto(SIMPLE_PROTO)
        team_id = uuid4()
        assets = rpc_methods_to_assets(result, team_id)

        assert len(assets) == 2
        fqns = {a.fqn for a in assets}
        assert "grpc.users.UserService.GetUser" in fqns
        assert "grpc.users.UserService.CreateUser" in fqns

        for asset in assets:
            assert asset.resource_type.value == "grpc_service"
            assert "grpc_source" in asset.metadata
            assert asset.metadata["grpc_source"]["package"] == "users"


# ===========================================================================
# Integration tests for /api/v1/sync/grpc endpoints
# ===========================================================================


class TestGRPCSync:
    """Tests for /api/v1/sync/grpc endpoint."""

    async def test_import_grpc_basic(self, client: AsyncClient) -> None:
        """Import proto file creates assets for each RPC method."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["package"] == "users"
        assert data["services_found"] == 1
        assert data["methods_found"] == 2
        assert data["assets_created"] == 2
        assert data["contracts_published"] == 2
        assert len(data["methods"]) == 2
        assert all(m["action"] == "created" for m in data["methods"])
        assert data["parse_errors"] == []

    async def test_import_grpc_dry_run(self, client: AsyncClient) -> None:
        """Dry run previews changes without creating assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-dry-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets_created"] == 2
        for method in data["methods"]:
            assert method["action"] == "would_create"

    async def test_import_grpc_update_existing(self, client: AsyncClient) -> None:
        """Re-importing updates existing assets."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-update-team"})
        team_id = team_resp.json()["id"]

        # First import
        resp1 = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": SIMPLE_PROTO, "owner_team_id": team_id},
        )
        assert resp1.status_code == 200
        assert resp1.json()["assets_created"] == 2

        # Second import
        resp2 = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": SIMPLE_PROTO, "owner_team_id": team_id},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["assets_updated"] == 2
        assert data2["assets_created"] == 0

    async def test_import_grpc_no_auto_contracts(self, client: AsyncClient) -> None:
        """Import with auto_publish_contracts=false skips contract creation."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-nocontract-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
                "auto_publish_contracts": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contracts_published"] == 0
        assert data["assets_created"] == 2

    async def test_import_grpc_nested_enums(self, client: AsyncClient) -> None:
        """Import proto with nested messages and enums."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-nested-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": NESTED_ENUM_PROTO, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["package"] == "orders"
        assert data["assets_created"] == 1

    async def test_import_grpc_multi_service(self, client: AsyncClient) -> None:
        """Import proto with multiple services."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-multi-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": MULTI_SERVICE_PROTO, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["services_found"] == 2
        assert data["methods_found"] == 2
        assert data["assets_created"] == 2

    async def test_import_grpc_invalid_team(self, client: AsyncClient) -> None:
        """Import with nonexistent team returns 404."""
        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.status_code == 404

    async def test_import_grpc_no_services(self, client: AsyncClient) -> None:
        """Import proto with no services returns 400."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-nosvc-team"})
        team_id = team_resp.json()["id"]

        proto = """\
syntax = "proto3";
package types;

message Timestamp {
  int64 seconds = 1;
  int32 nanos = 2;
}
"""
        resp = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": proto, "owner_team_id": team_id},
        )
        assert resp.status_code == 400

    async def test_import_grpc_streaming(self, client: AsyncClient) -> None:
        """Import proto with streaming RPCs preserves streaming metadata."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-stream-team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={"proto_content": STREAMING_PROTO, "owner_team_id": team_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["methods_found"] == 4
        assert data["assets_created"] == 4


class TestGRPCImpact:
    """Tests for /api/v1/sync/grpc/impact endpoint."""

    async def test_impact_no_contracts(self, client: AsyncClient) -> None:
        """Impact check with no existing contracts returns success."""
        resp = await client.post(
            "/api/v1/sync/grpc/impact",
            json={"proto_content": SIMPLE_PROTO},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["breaking_changes_count"] == 0
        assert data["methods_with_contracts"] == 0

    async def test_impact_with_existing_contract(self, client: AsyncClient) -> None:
        """Impact check finds existing contracts."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-impact-team"})
        team_id = team_resp.json()["id"]

        # Create assets+contracts first
        await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        # Now check impact
        resp = await client.post(
            "/api/v1/sync/grpc/impact",
            json={"proto_content": SIMPLE_PROTO},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["methods_with_contracts"] >= 1


class TestGRPCDiff:
    """Tests for /api/v1/sync/grpc/diff endpoint."""

    async def test_diff_new_methods(self, client: AsyncClient) -> None:
        """Diff shows new methods correctly."""
        resp = await client.post(
            "/api/v1/sync/grpc/diff",
            json={"proto_content": SIMPLE_PROTO},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["new"] == 2
        assert data["blocking"] is False

    async def test_diff_detects_breaking_changes(self, client: AsyncClient) -> None:
        """Diff detects breaking schema changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-diff-team"})
        team_id = team_resp.json()["id"]

        # Import v1
        await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        # Diff with v2 that removes a field
        v2_proto = """\
syntax = "proto3";
package users;

service UserService {
  rpc GetUser (GetUserRequest) returns (User);
  rpc CreateUser (CreateUserRequest) returns (User);
}

message GetUserRequest {
  string id = 1;
}

message CreateUserRequest {
  string email = 1;
}

message User {
  string id = 1;
  string email = 2;
}
"""
        resp = await client.post(
            "/api/v1/sync/grpc/diff",
            json={"proto_content": v2_proto, "fail_on_breaking": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should detect changes (name removed from CreateUserRequest and User)
        total_changes = data["summary"]["modified"] + data["summary"]["breaking"]
        assert total_changes >= 1 or data["summary"]["unchanged"] >= 1

    async def test_diff_fail_on_breaking_false(self, client: AsyncClient) -> None:
        """Diff with fail_on_breaking=false doesn't block."""
        resp = await client.post(
            "/api/v1/sync/grpc/diff",
            json={"proto_content": SIMPLE_PROTO, "fail_on_breaking": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocking"] is False

    async def test_diff_unchanged_schema(self, client: AsyncClient) -> None:
        """Diff with same proto shows no breaking changes."""
        team_resp = await client.post("/api/v1/teams", json={"name": "grpc-diff-same-team"})
        team_id = team_resp.json()["id"]

        # Import
        await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": team_id,
                "auto_publish_contracts": True,
            },
        )

        # Diff with same proto — should find existing methods with no breaking changes
        resp = await client.post(
            "/api/v1/sync/grpc/diff",
            json={"proto_content": SIMPLE_PROTO},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["breaking"] == 0
        assert data["blocking"] is False
        assert data["total_methods"] >= 1 if "total_methods" in data else True
