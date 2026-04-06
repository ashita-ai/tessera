"""Tests: sync endpoints reject soft-deleted owner teams.

Covers issue #449 — verifies that the TeamDB.deleted_at.is_(None) filters
in the gRPC, OpenAPI, and GraphQL sync endpoints correctly return 404 when
the owner team has been soft-deleted.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db.models import TeamDB

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_team(session: AsyncSession, name: str) -> TeamDB:
    """Insert a team directly into the DB and return it."""
    team = TeamDB(name=name)
    session.add(team)
    await session.flush()
    return team


async def _soft_delete_team(session: AsyncSession, team: TeamDB) -> None:
    """Set deleted_at on a team to simulate soft deletion."""
    team.deleted_at = datetime.now(UTC)
    session.add(team)
    await session.flush()


# ---------------------------------------------------------------------------
# Minimal payloads
# ---------------------------------------------------------------------------

SIMPLE_PROTO = """\
syntax = "proto3";
package orders;

service OrderService {
  rpc GetOrder (GetOrderRequest) returns (Order);
}

message GetOrderRequest {
  string order_id = 1;
}

message Order {
  string order_id = 1;
  string status = 2;
}
"""

MINIMAL_OPENAPI_SPEC: dict = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List items",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

MINIMAL_GRAPHQL_INTROSPECTION: dict = {
    "__schema": {
        "queryType": {"name": "Query"},
        "types": [
            {
                "kind": "OBJECT",
                "name": "Query",
                "fields": [
                    {
                        "name": "users",
                        "args": [],
                        "type": {
                            "kind": "LIST",
                            "name": None,
                            "ofType": {"kind": "OBJECT", "name": "User"},
                        },
                    }
                ],
            },
            {
                "kind": "OBJECT",
                "name": "User",
                "fields": [
                    {
                        "name": "id",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "ID", "ofType": None},
                    },
                    {
                        "name": "name",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
            },
        ],
    }
}


# ---------------------------------------------------------------------------
# gRPC
# ---------------------------------------------------------------------------


class TestGRPCSyncRejectsSoftDeletedTeam:
    """gRPC import should return 404 when owner_team_id is soft-deleted."""

    async def test_grpc_sync_rejects_soft_deleted_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        team = await _create_team(session, "grpc-deleted-team")
        await _soft_delete_team(session, team)
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 404

    async def test_grpc_sync_accepts_active_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        """Sanity check: an active team should succeed."""
        team = await _create_team(session, "grpc-active-team")
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/grpc",
            json={
                "proto_content": SIMPLE_PROTO,
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


class TestOpenAPISyncRejectsSoftDeletedTeam:
    """OpenAPI import should return 404 when owner_team_id is soft-deleted."""

    async def test_openapi_sync_rejects_soft_deleted_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        team = await _create_team(session, "openapi-deleted-team")
        await _soft_delete_team(session, team)
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": MINIMAL_OPENAPI_SPEC,
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 404

    async def test_openapi_sync_accepts_active_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        """Sanity check: an active team should succeed."""
        team = await _create_team(session, "openapi-active-team")
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/openapi",
            json={
                "spec": MINIMAL_OPENAPI_SPEC,
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------


class TestGraphQLSyncRejectsSoftDeletedTeam:
    """GraphQL import should return 404 when owner_team_id is soft-deleted."""

    async def test_graphql_sync_rejects_soft_deleted_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        team = await _create_team(session, "graphql-deleted-team")
        await _soft_delete_team(session, team)
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": MINIMAL_GRAPHQL_INTROSPECTION,
                "schema_name": "test-graphql",
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 404

    async def test_graphql_sync_accepts_active_team(
        self, session: AsyncSession, client: AsyncClient
    ) -> None:
        """Sanity check: an active team should succeed."""
        team = await _create_team(session, "graphql-active-team")
        await session.commit()

        resp = await client.post(
            "/api/v1/sync/graphql",
            json={
                "introspection": MINIMAL_GRAPHQL_INTROSPECTION,
                "schema_name": "test-graphql",
                "owner_team_id": str(team.id),
            },
        )

        assert resp.status_code == 200
