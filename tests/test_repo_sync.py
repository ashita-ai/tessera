"""Tests for the git-based repo sync worker and spec discovery.

Tests cover: git operations (mocked), spec file discovery, service
assignment by path, FQN generation, contract publishing integration,
error handling, timeout behavior, and background worker logic.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.db import AssetDB, RepoDB, ServiceDB, SyncEventDB, TeamDB
from tessera.models.enums import ResourceType
from tessera.models.repo import Repo, SyncEvent
from tessera.services.repo_sync import (
    DiscoveredSpec,
    SyncResult,
    _classify_spec_file,
    _infer_service_name,
    _inject_token,
    _log_sync_failed,
    _parse_spec,
    _ssh_key_env,
    assign_spec_to_service,
    clone_or_pull,
    discover_specs,
    generate_fqn,
    save_sync_event,
    sync_repo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_team(session: AsyncSession, name: str = "test-team") -> TeamDB:
    team = TeamDB(name=name, metadata_={})
    session.add(team)
    await session.flush()
    await session.refresh(team)
    return team


async def _create_repo(
    session: AsyncSession,
    team: TeamDB,
    name: str = "test-repo",
    git_url: str = "https://github.com/acme/test-repo.git",
    spec_paths: list[str] | None = None,
    **kwargs: Any,
) -> RepoDB:
    repo = RepoDB(
        name=name,
        git_url=git_url,
        owner_team_id=team.id,
        spec_paths=spec_paths if spec_paths is not None else ["api/"],
        **kwargs,
    )
    session.add(repo)
    await session.flush()
    await session.refresh(repo)
    return repo


async def _create_service(
    session: AsyncSession,
    repo: RepoDB,
    name: str = "order-service",
    root_path: str = "services/orders",
) -> ServiceDB:
    svc = ServiceDB(
        name=name,
        repo_id=repo.id,
        root_path=root_path,
        owner_team_id=repo.owner_team_id,
    )
    session.add(svc)
    await session.flush()
    await session.refresh(svc)
    return svc


SAMPLE_OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Order API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "list_orders",
                "summary": "List all orders",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    },
                                }
                            }
                        }
                    }
                },
            },
            "post": {
                "operationId": "create_order",
                "summary": "Create an order",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "item": {"type": "string"},
                                    "quantity": {"type": "integer"},
                                },
                                "required": ["item", "quantity"],
                            }
                        }
                    }
                },
                "responses": {
                    "201": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        }
                    }
                },
            },
        }
    },
}

SAMPLE_PROTO = textwrap.dedent("""\
    syntax = "proto3";
    package orders;

    message CreateOrderRequest {
        string item = 1;
        int32 quantity = 2;
    }

    message CreateOrderResponse {
        string order_id = 1;
        string status = 2;
    }

    service OrderService {
        rpc CreateOrder(CreateOrderRequest) returns (CreateOrderResponse);
    }
""")


# ---------------------------------------------------------------------------
# Unit tests: token injection
# ---------------------------------------------------------------------------


class TestTokenInjection:
    def test_inject_https(self) -> None:
        url = "https://github.com/org/repo.git"
        result = _inject_token(url, "my-token")
        assert result == "https://x-access-token:my-token@github.com/org/repo.git"

    def test_inject_no_token(self) -> None:
        url = "https://github.com/org/repo.git"
        assert _inject_token(url, None) == url

    def test_inject_ssh_unchanged(self) -> None:
        url = "git@github.com:org/repo.git"
        assert _inject_token(url, "token") == url


# ---------------------------------------------------------------------------
# Unit tests: spec classification
# ---------------------------------------------------------------------------


class TestSpecClassification:
    def test_openapi_yaml(self) -> None:
        content = 'openapi: "3.0.0"\ninfo:\n  title: Test\n  version: "1.0"\npaths: {}'
        assert _classify_spec_file(Path("api/spec.yaml"), content) == "openapi"

    def test_openapi_json(self) -> None:
        spec = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": {}}
        content = json.dumps(spec)
        assert _classify_spec_file(Path("api/spec.json"), content) == "openapi"

    def test_proto_file(self) -> None:
        assert _classify_spec_file(Path("proto/orders.proto"), SAMPLE_PROTO) == "grpc"

    def test_graphql_file(self) -> None:
        result = _classify_spec_file(Path("schema.graphql"), "type Query { hello: String }")
        assert result == "graphql"

    def test_gql_extension(self) -> None:
        assert _classify_spec_file(Path("schema.gql"), "type Query {}") == "graphql"

    def test_yaml_without_openapi_key(self) -> None:
        assert _classify_spec_file(Path("config.yaml"), "name: test\nversion: 1") is None

    def test_unknown_extension(self) -> None:
        assert _classify_spec_file(Path("readme.md"), "# Readme") is None


# ---------------------------------------------------------------------------
# Unit tests: spec discovery (filesystem)
# ---------------------------------------------------------------------------


class TestDiscoverSpecs:
    def test_discover_openapi_in_directory(self, tmp_path: Path) -> None:
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        spec_file = api_dir / "openapi.yaml"
        spec_file.write_text(
            json.dumps({"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "paths": {}})
        )

        specs = discover_specs(str(tmp_path), ["api/"])
        assert len(specs) == 1
        assert specs[0].spec_type == "openapi"
        assert specs[0].file_path == "api/openapi.yaml"

    def test_discover_proto_file(self, tmp_path: Path) -> None:
        proto_dir = tmp_path / "proto"
        proto_dir.mkdir()
        (proto_dir / "orders.proto").write_text(SAMPLE_PROTO)

        specs = discover_specs(str(tmp_path), ["proto/"])
        assert len(specs) == 1
        assert specs[0].spec_type == "grpc"

    def test_discover_skips_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "refs"
        hidden.mkdir(parents=True)
        (hidden / "spec.yaml").write_text(
            json.dumps({"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "paths": {}})
        )

        specs = discover_specs(str(tmp_path), [".git/"])
        assert len(specs) == 0

    def test_discover_no_duplicates(self, tmp_path: Path) -> None:
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "spec.yaml").write_text(
            json.dumps({"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "paths": {}})
        )

        # Two patterns pointing to the same file
        specs = discover_specs(str(tmp_path), ["api/", "api/spec.yaml"])
        assert len(specs) == 1

    def test_discover_glob_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.proto").write_text(SAMPLE_PROTO)
        (tmp_path / "b.proto").write_text(SAMPLE_PROTO)

        specs = discover_specs(str(tmp_path), ["*.proto"])
        assert len(specs) == 2

    def test_discover_empty_spec_paths(self, tmp_path: Path) -> None:
        specs = discover_specs(str(tmp_path), [])
        assert len(specs) == 0

    def test_discover_skips_symlinks(self, tmp_path: Path) -> None:
        """Symlinks in a cloned repo must not be followed (path traversal risk)."""
        api_dir = tmp_path / "api"
        api_dir.mkdir()

        # Create a real spec file outside the repo directory
        external = tmp_path / "external"
        external.mkdir()
        secret = external / "secret.json"
        secret.write_text(
            json.dumps(
                {"openapi": "3.0.0", "info": {"title": "Leaked", "version": "1"}, "paths": {}}
            )
        )

        # Symlink inside repo pointing to external file
        link = api_dir / "evil.json"
        link.symlink_to(secret)

        # Also add a real file so we know discovery works
        real = api_dir / "real.yaml"
        real.write_text(
            json.dumps({"openapi": "3.0.0", "info": {"title": "Real", "version": "1"}, "paths": {}})
        )

        specs = discover_specs(str(tmp_path), ["api/"])
        assert len(specs) == 1
        assert specs[0].file_path == "api/real.yaml"


# ---------------------------------------------------------------------------
# Unit tests: service assignment
# ---------------------------------------------------------------------------


class TestServiceAssignment:
    def test_longest_prefix_match(self, test_session: AsyncSession) -> None:
        """The service with the longest matching root_path wins."""
        svc_root = MagicMock(spec=ServiceDB, root_path="/", name="root")
        svc_orders = MagicMock(spec=ServiceDB, root_path="services/orders", name="orders")
        svc_payments = MagicMock(spec=ServiceDB, root_path="services/payments", name="payments")

        result = assign_spec_to_service(
            "services/orders/api/openapi.yaml",
            [svc_root, svc_orders, svc_payments],
        )
        assert result is svc_orders

    def test_root_service_fallback(self) -> None:
        svc_root = MagicMock(spec=ServiceDB, root_path="/", name="root")
        result = assign_spec_to_service("somewhere/spec.yaml", [svc_root])
        assert result is svc_root

    def test_no_match_returns_none(self) -> None:
        svc = MagicMock(spec=ServiceDB, root_path="services/orders", name="orders")
        result = assign_spec_to_service("proto/spec.proto", [svc])
        assert result is None

    def test_dot_root_path_matches_as_fallback(self) -> None:
        """A service with root_path='.' (from Path('.').str()) matches as root fallback."""
        svc_dot = MagicMock(spec=ServiceDB, root_path=".", name="root")
        result = assign_spec_to_service("openapi.yaml", [svc_dot])
        assert result is svc_dot

    def test_dot_root_path_loses_to_longer_prefix(self) -> None:
        """A '.' root service is only a fallback — a longer prefix match wins."""
        svc_dot = MagicMock(spec=ServiceDB, root_path=".", name="root")
        svc_api = MagicMock(spec=ServiceDB, root_path="api", name="api")
        result = assign_spec_to_service("api/openapi.yaml", [svc_dot, svc_api])
        assert result is svc_api


# ---------------------------------------------------------------------------
# Unit tests: service name inference
# ---------------------------------------------------------------------------


class TestServiceNameInference:
    def test_standard_path(self) -> None:
        assert _infer_service_name("services/orders/api/openapi.yaml") == "orders"

    def test_generic_dirs_filtered(self) -> None:
        assert _infer_service_name("api/openapi.yaml") != "api"

    def test_root_spec(self) -> None:
        # When path is just the file, fall back to stem
        name = _infer_service_name("openapi.yaml")
        assert name == "openapi"

    def test_hyphenated_name(self) -> None:
        assert _infer_service_name("services/payment-service/api/spec.yaml") == "payment_service"


# ---------------------------------------------------------------------------
# Unit tests: FQN generation
# ---------------------------------------------------------------------------


class TestFQNGeneration:
    def test_basic_fqn(self) -> None:
        result = generate_fqn("order_service", "rest", "create_order")
        assert result == "order_service.rest.create_order"

    def test_hyphen_normalization(self) -> None:
        assert generate_fqn("payment-service", "grpc", "Pay") == "payment_service.grpc.Pay"

    def test_empty_service_name(self) -> None:
        fqn = generate_fqn("", "rest", "op")
        assert fqn == "default.rest.op"


# ---------------------------------------------------------------------------
# Unit tests: spec parsing
# ---------------------------------------------------------------------------


class TestParseSpec:
    def test_parse_openapi_spec(self) -> None:
        spec = DiscoveredSpec(
            file_path="api/openapi.yaml",
            spec_type="openapi",
            content=json.dumps(SAMPLE_OPENAPI),
        )
        items = _parse_spec(spec)
        assert len(items) == 2
        op_ids = {item["fqn_suffix"] for item in items}
        assert "rest.list_orders" in op_ids
        assert "rest.create_order" in op_ids

    def test_parse_proto_spec(self) -> None:
        spec = DiscoveredSpec(
            file_path="proto/orders.proto",
            spec_type="grpc",
            content=SAMPLE_PROTO,
        )
        items = _parse_spec(spec)
        assert len(items) == 1
        assert items[0]["fqn_suffix"] == "grpc.OrderService_CreateOrder"
        assert items[0]["resource_type"] == ResourceType.GRPC_SERVICE

    def test_parse_graphql_spec(self) -> None:
        spec = DiscoveredSpec(
            file_path="schema.graphql",
            spec_type="graphql",
            content="type Query { hello: String }",
        )
        items = _parse_spec(spec)
        assert len(items) >= 1
        assert items[0]["resource_type"] == ResourceType.GRAPHQL_QUERY
        assert "graphql." in items[0]["fqn_suffix"]

    def test_parse_invalid_openapi_returns_empty(self) -> None:
        spec = DiscoveredSpec(
            file_path="bad.yaml",
            spec_type="openapi",
            content="not: valid: yaml: {{{{",
        )
        items = _parse_spec(spec)
        assert len(items) == 0


# ---------------------------------------------------------------------------
# Integration tests: sync_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncRepo:
    """Integration tests for the full sync_repo flow with mocked git."""

    async def _setup_repo_with_specs(
        self,
        session: AsyncSession,
        tmp_path: Path,
        specs: dict[str, str],
    ) -> tuple[RepoDB, TeamDB]:
        """Create a team, repo, and mock spec files on disk."""
        team = await _create_team(session)
        repo = await _create_repo(
            session,
            team,
            spec_paths=list({str(Path(p).parent) + "/" for p in specs}),
        )

        # Create fake repo directory with specs
        repo_dir = tmp_path / str(repo.id)
        repo_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()  # Mark as git repo

        for rel_path, content in specs.items():
            full_path = repo_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        return repo, team

    async def test_sync_single_openapi(self, test_session: AsyncSession, tmp_path: Path) -> None:
        """Sync a repo with a single OpenAPI spec → creates service and assets."""
        repo, team = await self._setup_repo_with_specs(
            test_session,
            tmp_path,
            {"api/openapi.yaml": json.dumps(SAMPLE_OPENAPI)},
        )

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=(str(tmp_path / str(repo.id)), "abc123"),
        ):
            result = await sync_repo(test_session, repo)

        assert result.success
        assert result.commit_sha == "abc123"
        assert result.specs_found == 1
        assert result.services_created >= 1

        # Verify service was created
        svc_result = await test_session.execute(
            select(ServiceDB).where(ServiceDB.repo_id == repo.id)
        )
        services = list(svc_result.scalars().all())
        assert len(services) >= 1

        # Verify assets were created
        asset_result = await test_session.execute(
            select(AssetDB).where(AssetDB.service_id == services[0].id)
        )
        assets = list(asset_result.scalars().all())
        assert len(assets) >= 1

    async def test_sync_monorepo_two_services(
        self, test_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Monorepo with two service dirs → each gets its own service and assets."""
        team = await _create_team(test_session)
        repo = await _create_repo(
            test_session,
            team,
            spec_paths=["services/"],
        )

        repo_dir = tmp_path / str(repo.id)
        (repo_dir / ".git").mkdir(parents=True)

        # Service 1: orders
        orders_dir = repo_dir / "services" / "orders" / "api"
        orders_dir.mkdir(parents=True)
        orders_spec = dict(SAMPLE_OPENAPI)
        orders_spec["info"] = {"title": "Orders API", "version": "1.0.0"}
        (orders_dir / "openapi.yaml").write_text(json.dumps(orders_spec))

        # Service 2: payments (proto)
        payments_dir = repo_dir / "services" / "payments" / "proto"
        payments_dir.mkdir(parents=True)
        (payments_dir / "payment.proto").write_text(SAMPLE_PROTO)

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=(str(repo_dir), "def456"),
        ):
            result = await sync_repo(test_session, repo)

        assert result.success
        assert result.specs_found == 2
        assert result.services_created >= 2

        svc_result = await test_session.execute(
            select(ServiceDB)
            .where(ServiceDB.repo_id == repo.id)
            .where(ServiceDB.deleted_at.is_(None))
        )
        services = list(svc_result.scalars().all())
        service_names = {s.name for s in services}
        assert len(services) >= 2
        assert "orders" in service_names or any("order" in s.lower() for s in service_names)

    async def test_sync_with_existing_service(
        self, test_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Specs matching an existing service's root_path use that service."""
        repo, team = await self._setup_repo_with_specs(
            test_session,
            tmp_path,
            {"services/orders/api/openapi.yaml": json.dumps(SAMPLE_OPENAPI)},
        )
        # Pre-create service
        svc = await _create_service(test_session, repo)

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=(str(tmp_path / str(repo.id)), "abc123"),
        ):
            # Reconfigure spec_paths to match our directory structure
            repo.spec_paths = ["services/"]
            await test_session.flush()
            result = await sync_repo(test_session, repo)

        assert result.success
        assert result.services_created == 0  # Reused existing service

        # Verify assets linked to existing service
        asset_result = await test_session.execute(
            select(AssetDB).where(AssetDB.service_id == svc.id)
        )
        assets = list(asset_result.scalars().all())
        assert len(assets) >= 1

    async def test_sync_no_change_skips(self, test_session: AsyncSession, tmp_path: Path) -> None:
        """If the commit SHA hasn't changed, sync short-circuits."""
        repo, _ = await self._setup_repo_with_specs(
            test_session,
            tmp_path,
            {"api/openapi.yaml": json.dumps(SAMPLE_OPENAPI)},
        )
        repo.last_synced_commit = "same_sha"
        await test_session.flush()

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=(str(tmp_path / str(repo.id)), "same_sha"),
        ):
            result = await sync_repo(test_session, repo)

        assert result.success
        assert result.specs_found == 0
        assert "No new commits" in result.warnings[0]

    async def test_sync_no_spec_paths(self, test_session: AsyncSession) -> None:
        """Repo with empty spec_paths returns success with a warning."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team, spec_paths=[])

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=("/tmp/fake", "abc123"),
        ):
            result = await sync_repo(test_session, repo)

        assert result.success
        assert "No spec_paths" in result.warnings[0]

    async def test_sync_git_failure(self, test_session: AsyncSession) -> None:
        """Git clone/pull failure → sync fails with error."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team)

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            side_effect=RuntimeError("Authentication failed"),
        ):
            result = await sync_repo(test_session, repo)

        assert not result.success
        assert "Authentication failed" in result.errors[0]

    async def test_sync_updates_last_synced_fields(
        self, test_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Successful sync updates last_synced_at and last_synced_commit."""
        repo, _ = await self._setup_repo_with_specs(
            test_session,
            tmp_path,
            {"api/openapi.yaml": json.dumps(SAMPLE_OPENAPI)},
        )

        assert repo.last_synced_at is None
        assert repo.last_synced_commit is None

        with patch(
            "tessera.services.repo_sync.clone_or_pull",
            return_value=(str(tmp_path / str(repo.id)), "commit_xyz"),
        ):
            result = await sync_repo(test_session, repo)

        assert result.success
        await test_session.refresh(repo)
        assert repo.last_synced_commit == "commit_xyz"
        assert repo.last_synced_at is not None


# ---------------------------------------------------------------------------
# Git operations (mocked subprocess)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCloneOrPull:
    async def test_clone_new_repo(self, tmp_path: Path) -> None:
        """First sync: shallow clone."""
        repo = MagicMock(spec=RepoDB)
        repo.id = uuid4()
        repo.git_url = "https://github.com/acme/test.git"
        repo.default_branch = "main"

        with (
            patch("tessera.services.repo_sync.settings") as mock_settings,
            patch("tessera.services.repo_sync._run_git") as mock_git,
            patch("tessera.services.repo_sync._dir_size", return_value=1000),
        ):
            mock_settings.repo_dir = str(tmp_path)
            mock_settings.git_timeout = 120
            mock_settings.repo_max_size_mb = 500

            mock_git.side_effect = [
                (0, "", ""),  # clone
                (0, "abc123", ""),  # rev-parse HEAD
            ]

            repo_dir, sha = await clone_or_pull(repo, None)

        assert sha == "abc123"
        # Verify clone was called with correct args including -- separator
        clone_call = mock_git.call_args_list[0]
        clone_args = clone_call[0][0]
        assert "clone" in clone_args
        assert "--depth" in clone_args
        assert "--" in clone_args

    async def test_pull_existing_repo(self, tmp_path: Path) -> None:
        """Subsequent sync: fetch + reset."""
        repo = MagicMock(spec=RepoDB)
        repo.id = uuid4()
        repo.git_url = "https://github.com/acme/test.git"
        repo.default_branch = "main"

        # Create fake .git directory to trigger pull path
        repo_dir = tmp_path / str(repo.id)
        (repo_dir / ".git").mkdir(parents=True)

        with (
            patch("tessera.services.repo_sync.settings") as mock_settings,
            patch("tessera.services.repo_sync._run_git") as mock_git,
            patch("tessera.services.repo_sync._dir_size", return_value=1000),
        ):
            mock_settings.repo_dir = str(tmp_path)
            mock_settings.git_timeout = 120
            mock_settings.repo_max_size_mb = 500

            mock_git.side_effect = [
                (0, "", ""),  # fetch
                (0, "", ""),  # reset
                (0, "def456", ""),  # rev-parse HEAD
            ]

            _, sha = await clone_or_pull(repo, None)

        assert sha == "def456"
        # Verify fetch was called (not clone) with -- separator
        fetch_call = mock_git.call_args_list[0]
        fetch_args = fetch_call[0][0]
        assert "fetch" in fetch_args
        assert "--" in fetch_args

    async def test_clone_failure_raises(self, tmp_path: Path) -> None:
        """Git clone failure raises RuntimeError."""
        repo = MagicMock(spec=RepoDB)
        repo.id = uuid4()
        repo.git_url = "https://github.com/acme/test.git"
        repo.default_branch = "main"

        with (
            patch("tessera.services.repo_sync.settings") as mock_settings,
            patch("tessera.services.repo_sync._run_git") as mock_git,
        ):
            mock_settings.repo_dir = str(tmp_path)
            mock_settings.git_timeout = 120
            mock_settings.repo_max_size_mb = 500

            mock_git.return_value = (128, "", "fatal: repository not found")

            with pytest.raises(RuntimeError, match="git clone failed"):
                await clone_or_pull(repo, None)

    async def test_repo_size_limit_enforced(self, tmp_path: Path) -> None:
        """Repos exceeding size limit are rejected."""
        repo = MagicMock(spec=RepoDB)
        repo.id = uuid4()
        repo.git_url = "https://github.com/acme/test.git"
        repo.default_branch = "main"

        with (
            patch("tessera.services.repo_sync.settings") as mock_settings,
            patch("tessera.services.repo_sync._run_git") as mock_git,
            patch(
                "tessera.services.repo_sync._dir_size",
                return_value=600 * 1024 * 1024,  # 600MB
            ),
        ):
            mock_settings.repo_dir = str(tmp_path)
            mock_settings.git_timeout = 120
            mock_settings.repo_max_size_mb = 500

            mock_git.side_effect = [
                (0, "", ""),  # clone succeeds
            ]

            with pytest.raises(RuntimeError, match="exceeds size limit"):
                await clone_or_pull(repo, None)

    async def test_token_injected_for_private_repo(self, tmp_path: Path) -> None:
        """Auth token is injected into the clone URL."""
        repo = MagicMock(spec=RepoDB)
        repo.id = uuid4()
        repo.git_url = "https://github.com/acme/private-repo.git"
        repo.default_branch = "main"

        with (
            patch("tessera.services.repo_sync.settings") as mock_settings,
            patch("tessera.services.repo_sync._run_git") as mock_git,
            patch("tessera.services.repo_sync._dir_size", return_value=1000),
        ):
            mock_settings.repo_dir = str(tmp_path)
            mock_settings.git_timeout = 120
            mock_settings.repo_max_size_mb = 500

            mock_git.side_effect = [
                (0, "", ""),  # clone
                (0, "abc", ""),  # rev-parse
            ]

            await clone_or_pull(repo, "ghp_secret_token")

        # The clone command should have the token in the URL
        clone_args = mock_git.call_args_list[0][0][0]
        assert any("x-access-token:ghp_secret_token@" in arg for arg in clone_args)


# ---------------------------------------------------------------------------
# Background worker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncRepoPublishFailure:
    """Tests for publish failure recording commit SHA to prevent infinite retry."""

    async def _setup_repo_with_specs(
        self,
        session: AsyncSession,
        tmp_path: Path,
        specs: dict[str, str],
    ) -> tuple[RepoDB, TeamDB]:
        team = await _create_team(session)
        repo = await _create_repo(
            session,
            team,
            spec_paths=list({str(Path(p).parent) + "/" for p in specs}),
        )
        repo_dir = tmp_path / str(repo.id)
        repo_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()
        for rel_path, content in specs.items():
            full_path = repo_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
        return repo, team

    async def test_publish_failure_still_records_commit(
        self, test_session: AsyncSession, tmp_path: Path
    ) -> None:
        """When bulk_publish raises, last_synced_commit is still recorded."""
        repo, _ = await self._setup_repo_with_specs(
            test_session,
            tmp_path,
            {"api/openapi.yaml": json.dumps(SAMPLE_OPENAPI)},
        )

        assert repo.last_synced_commit is None

        with (
            patch(
                "tessera.services.repo_sync.clone_or_pull",
                return_value=(str(tmp_path / str(repo.id)), "fail_sha"),
            ),
            patch(
                "tessera.services.repo_sync.bulk_publish_contracts",
                side_effect=RuntimeError("publish exploded"),
            ),
        ):
            result = await sync_repo(test_session, repo)

        assert not result.success
        assert "Bulk publish failed" in result.errors[0]
        # The commit SHA must be recorded to prevent infinite retry
        await test_session.refresh(repo)
        assert repo.last_synced_commit == "fail_sha"
        assert repo.last_synced_at is not None


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestRepoModelValidation:
    """Tests for Pydantic model validation on RepoCreate/RepoUpdate."""

    def test_git_url_rejects_flag_injection(self) -> None:
        from tessera.models.repo import RepoCreate

        with pytest.raises(ValueError, match="must start with"):
            RepoCreate(
                name="test",
                git_url="--upload-pack=evil",
                owner_team_id=uuid4(),
            )

    def test_git_url_accepts_https(self) -> None:
        from tessera.models.repo import RepoCreate

        repo = RepoCreate(
            name="test",
            git_url="https://github.com/acme/test.git",
            owner_team_id=uuid4(),
        )
        assert repo.git_url == "https://github.com/acme/test.git"

    def test_git_url_accepts_ssh(self) -> None:
        from tessera.models.repo import RepoCreate

        repo = RepoCreate(
            name="test",
            git_url="git@github.com:acme/test.git",
            owner_team_id=uuid4(),
        )
        assert repo.git_url == "git@github.com:acme/test.git"

    def test_branch_rejects_flag_injection(self) -> None:
        from tessera.models.repo import RepoCreate

        with pytest.raises(ValueError, match="alphanumeric"):
            RepoCreate(
                name="test",
                git_url="https://github.com/acme/test.git",
                owner_team_id=uuid4(),
                default_branch="--upload-pack=evil",
            )

    def test_branch_rejects_dotdot(self) -> None:
        from tessera.models.repo import RepoCreate

        with pytest.raises(ValueError, match="must not contain"):
            RepoCreate(
                name="test",
                git_url="https://github.com/acme/test.git",
                owner_team_id=uuid4(),
                default_branch="main..dev",
            )

    def test_branch_accepts_slashes(self) -> None:
        from tessera.models.repo import RepoCreate

        repo = RepoCreate(
            name="test",
            git_url="https://github.com/acme/test.git",
            owner_team_id=uuid4(),
            default_branch="feature/my-branch",
        )
        assert repo.default_branch == "feature/my-branch"

    def test_spec_paths_rejects_traversal(self) -> None:
        from tessera.models.repo import RepoCreate

        with pytest.raises(ValueError, match="must not contain"):
            RepoCreate(
                name="test",
                git_url="https://github.com/acme/test.git",
                owner_team_id=uuid4(),
                spec_paths=["../../etc/passwd"],
            )

    def test_spec_paths_accepts_normal_paths(self) -> None:
        from tessera.models.repo import RepoCreate

        repo = RepoCreate(
            name="test",
            git_url="https://github.com/acme/test.git",
            owner_team_id=uuid4(),
            spec_paths=["api/", "proto/orders.proto"],
        )
        assert repo.spec_paths == ["api/", "proto/orders.proto"]

    def test_update_branch_rejects_flag_injection(self) -> None:
        from tessera.models.repo import RepoUpdate

        with pytest.raises(ValueError, match="alphanumeric"):
            RepoUpdate(default_branch="--evil")

    def test_update_spec_paths_rejects_traversal(self) -> None:
        from tessera.models.repo import RepoUpdate

        with pytest.raises(ValueError, match="must not contain"):
            RepoUpdate(spec_paths=["../../../etc/shadow"])


# ---------------------------------------------------------------------------
# Background worker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBackgroundWorker:
    async def test_poll_skips_disabled_repos(self, test_session: AsyncSession) -> None:
        """Repos with sync_enabled=False are not synced."""
        team = await _create_team(test_session)
        repo = await _create_repo(
            test_session,
            team,
            sync_enabled=False,
        )

        # The background worker queries for sync_enabled=True,
        # so this repo should not appear
        result = await test_session.execute(
            select(RepoDB).where(RepoDB.sync_enabled.is_(True)).where(RepoDB.deleted_at.is_(None))
        )
        repos = list(result.scalars().all())
        repo_ids = {r.id for r in repos}
        assert repo.id not in repo_ids


# ---------------------------------------------------------------------------
# Per-repo auth tests
# ---------------------------------------------------------------------------


class TestPerRepoAuth:
    """Tests for per-repo git_token / ssh_key support."""

    def test_repo_response_masks_credentials(self) -> None:
        """Repo response model exposes has_git_token/has_ssh_key, not plaintext."""
        repo_db = MagicMock()
        repo_db.id = uuid4()
        repo_db.name = "test"
        repo_db.git_url = "https://github.com/org/repo.git"
        repo_db.default_branch = "main"
        repo_db.spec_paths = []
        repo_db.owner_team_id = uuid4()
        repo_db.sync_enabled = True
        repo_db.codeowners_path = None
        repo_db.last_synced_at = None
        repo_db.last_synced_commit = None
        repo_db.created_at = "2026-01-01T00:00:00Z"
        repo_db.updated_at = None
        repo_db.git_token = "ghp_secret123"
        # Use a non-real key format to avoid tripping detect-private-key hook
        repo_db.ssh_key = "ssh-ed25519-fake-test-key-data-not-real"

        model = Repo.model_validate(repo_db)
        dumped = model.model_dump()

        assert dumped["has_git_token"] is True
        assert dumped["has_ssh_key"] is True
        assert "git_token" not in dumped
        assert "ssh_key" not in dumped

    def test_repo_response_no_credentials(self) -> None:
        """When no credentials are set, has_* fields are False."""
        repo_db = MagicMock()
        repo_db.id = uuid4()
        repo_db.name = "test"
        repo_db.git_url = "https://github.com/org/repo.git"
        repo_db.default_branch = "main"
        repo_db.spec_paths = []
        repo_db.owner_team_id = uuid4()
        repo_db.sync_enabled = True
        repo_db.codeowners_path = None
        repo_db.last_synced_at = None
        repo_db.last_synced_commit = None
        repo_db.created_at = "2026-01-01T00:00:00Z"
        repo_db.updated_at = None
        repo_db.git_token = None
        repo_db.ssh_key = None

        model = Repo.model_validate(repo_db)
        dumped = model.model_dump()

        assert dumped["has_git_token"] is False
        assert dumped["has_ssh_key"] is False

    @pytest.mark.asyncio
    async def test_ssh_key_env_creates_temp_file(self) -> None:
        """_ssh_key_env writes key to a 0600 temp file and cleans up on exit."""
        import os
        import stat

        # Use a non-real key to avoid tripping detect-private-key hook
        fake_key = "ssh-ed25519-fake-test-key-data-not-real"
        key_path: str | None = None

        async with _ssh_key_env(fake_key) as env:
            assert "GIT_SSH_COMMAND" in env
            ssh_cmd = env["GIT_SSH_COMMAND"]
            assert "-i " in ssh_cmd
            assert "StrictHostKeyChecking=accept-new" in ssh_cmd
            assert "IdentitiesOnly=yes" in ssh_cmd

            # Extract key path from the command
            key_path = ssh_cmd.split("-i ")[1].split(" ")[0]
            assert os.path.exists(key_path)

            # Verify permissions are 0600
            file_stat = os.stat(key_path)
            mode = stat.S_IMODE(file_stat.st_mode)
            assert mode == 0o600

            # Verify content
            with open(key_path) as f:
                content = f.read()
            assert "fake-test-key" in content

        # Verify cleanup
        assert key_path is not None
        assert not os.path.exists(key_path)

    @pytest.mark.asyncio
    async def test_token_priority_chain(self, test_session: AsyncSession) -> None:
        """sync_repo uses: explicit token > repo.git_token > settings.git_token."""
        team = await _create_team(test_session)
        repo = await _create_repo(
            test_session,
            team,
            git_token="repo-level-token",
        )

        captured_urls: list[str] = []

        async def mock_run_git(args, **kwargs):
            # Capture the URL used in clone/fetch
            for arg in args:
                if "github.com" in arg:
                    captured_urls.append(arg)
            if "rev-parse" in args:
                return 0, "abc123", ""
            return 0, "", ""

        with (
            patch("tessera.services.repo_sync._run_git", side_effect=mock_run_git),
            patch("tessera.services.repo_sync._dir_size", return_value=100),
        ):
            await sync_repo(test_session, repo)
            # The repo-level token should be used (injected into URL)
            assert any("repo-level-token" in url for url in captured_urls)


# ---------------------------------------------------------------------------
# Sync event persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncEventPersistence:
    """Tests for save_sync_event and SyncEvent model."""

    async def test_save_sync_event_success(self, test_session: AsyncSession) -> None:
        """save_sync_event persists a successful sync result."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team)

        result = SyncResult(
            repo_id=repo.id,
            success=True,
            commit_sha="abc123def456",
            specs_found=3,
            contracts_published=2,
            proposals_created=1,
            services_created=1,
            assets_created=2,
            assets_updated=1,
        )

        event = await save_sync_event(
            test_session,
            result,
            duration_seconds=5.2,
            triggered_by="manual",
        )

        assert event.repo_id == repo.id
        assert event.success is True
        assert event.commit_sha == "abc123def456"
        assert event.specs_found == 3
        assert event.contracts_published == 2
        assert event.proposals_created == 1
        assert event.services_created == 1
        assert event.assets_created == 2
        assert event.assets_updated == 1
        assert event.duration_seconds == pytest.approx(5.2)
        assert event.triggered_by == "manual"
        assert event.created_at is not None

    async def test_save_sync_event_failure(self, test_session: AsyncSession) -> None:
        """save_sync_event persists a failed sync result with errors."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team)

        result = SyncResult(
            repo_id=repo.id,
            success=False,
            errors=["git clone failed: timeout"],
        )

        event = await save_sync_event(
            test_session,
            result,
            duration_seconds=120.0,
            triggered_by="worker",
        )

        assert event.success is False
        assert event.errors == ["git clone failed: timeout"]
        assert event.triggered_by == "worker"

    async def test_sync_event_model_validates(self, test_session: AsyncSession) -> None:
        """SyncEvent pydantic model validates from SyncEventDB."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team)

        result = SyncResult(repo_id=repo.id, success=True, specs_found=1)
        event = await save_sync_event(test_session, result, duration_seconds=0.5)
        await test_session.refresh(event)

        model = SyncEvent.model_validate(event)
        assert model.repo_id == repo.id
        assert model.success is True
        assert model.specs_found == 1

    async def test_multiple_events_per_repo(self, test_session: AsyncSession) -> None:
        """Multiple sync events can be recorded for the same repo."""
        team = await _create_team(test_session)
        repo = await _create_repo(test_session, team)

        for i in range(3):
            result = SyncResult(
                repo_id=repo.id,
                success=i % 2 == 0,
                specs_found=i,
            )
            await save_sync_event(test_session, result, duration_seconds=float(i))

        events = (
            (
                await test_session.execute(
                    select(SyncEventDB)
                    .where(SyncEventDB.repo_id == repo.id)
                    .order_by(SyncEventDB.created_at)
                )
            )
            .scalars()
            .all()
        )

        assert len(events) == 3


@pytest.mark.asyncio
class TestLogSyncFailedSlackNotification:
    """Tests for Slack dispatch in _log_sync_failed."""

    @patch("tessera.services.repo_sync.audit")
    @patch(
        "tessera.services.slack_dispatcher.dispatch_slack_notifications",
        new_callable=AsyncMock,
    )
    async def test_dispatches_slack_when_repo_name_provided(
        self, mock_dispatch: AsyncMock, mock_audit: MagicMock, test_session: AsyncSession
    ) -> None:
        """Slack notification fires when repo_name is provided."""
        mock_audit.log_event = AsyncMock()
        repo_id = uuid4()
        team_id = uuid4()
        last_synced = datetime(2026, 4, 1, 12, 0, 0)

        await _log_sync_failed(
            test_session,
            repo_id,
            team_id,
            ["Clone timed out"],
            repo_name="my-repo",
            last_synced_at=last_synced,
        )

        mock_dispatch.assert_awaited_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs["event_type"] == "repo.sync_failed"
        assert call_kwargs["team_ids"] == [team_id]
        assert call_kwargs["payload"]["repo_name"] == "my-repo"
        assert call_kwargs["payload"]["error_message"] == "Clone timed out"
        assert call_kwargs["payload"]["last_synced_at"] == last_synced.isoformat()
        assert call_kwargs["payload"]["repo_id"] == str(repo_id)

    @patch("tessera.services.repo_sync.audit")
    @patch(
        "tessera.services.slack_dispatcher.dispatch_slack_notifications",
        new_callable=AsyncMock,
    )
    async def test_skips_slack_when_repo_name_is_none(
        self, mock_dispatch: AsyncMock, mock_audit: MagicMock, test_session: AsyncSession
    ) -> None:
        """Slack notification is skipped when repo_name is None (backward compat)."""
        mock_audit.log_event = AsyncMock()

        await _log_sync_failed(
            test_session,
            uuid4(),
            uuid4(),
            ["Some error"],
        )

        mock_dispatch.assert_not_awaited()

    @patch("tessera.services.repo_sync.audit")
    @patch(
        "tessera.services.slack_dispatcher.dispatch_slack_notifications",
        new_callable=AsyncMock,
    )
    async def test_handles_multiple_errors(
        self, mock_dispatch: AsyncMock, mock_audit: MagicMock, test_session: AsyncSession
    ) -> None:
        """Multiple errors are joined with semicolons in the payload."""
        mock_audit.log_event = AsyncMock()

        await _log_sync_failed(
            test_session,
            uuid4(),
            uuid4(),
            ["Error one", "Error two"],
            repo_name="multi-error-repo",
        )

        payload = mock_dispatch.call_args.kwargs["payload"]
        assert payload["error_message"] == "Error one; Error two"

    @patch("tessera.services.repo_sync.audit")
    @patch(
        "tessera.services.slack_dispatcher.dispatch_slack_notifications",
        new_callable=AsyncMock,
    )
    async def test_handles_none_last_synced_at(
        self, mock_dispatch: AsyncMock, mock_audit: MagicMock, test_session: AsyncSession
    ) -> None:
        """last_synced_at=None produces null in the payload."""
        mock_audit.log_event = AsyncMock()

        await _log_sync_failed(
            test_session,
            uuid4(),
            uuid4(),
            ["Error"],
            repo_name="new-repo",
            last_synced_at=None,
        )

        payload = mock_dispatch.call_args.kwargs["payload"]
        assert payload["last_synced_at"] is None
