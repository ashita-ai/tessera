"""Git-based repository sync worker and spec discovery.

Clones/pulls registered repos, discovers spec files, parses them using
existing sync logic (OpenAPI, GraphQL, gRPC), and creates/updates assets
and contracts through the contract publisher.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db import AssetDB, RepoDB, ServiceDB, SyncEventDB
from tessera.models.enums import CompatibilityMode, ResourceType
from tessera.services import audit
from tessera.services.audit import AuditAction
from tessera.services.contract_publisher import (
    BulkPublishResult,
    ContractToPublish,
    bulk_publish_contracts,
)
from tessera.services.grpc import parse_proto
from tessera.services.openapi import parse_openapi

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredSpec:
    """A spec file discovered in a repository."""

    file_path: str  # Relative to repo root
    spec_type: str  # "openapi", "graphql", "grpc"
    content: str  # Raw file content


@dataclass
class SyncResult:
    """Result of syncing a single repository."""

    repo_id: UUID
    success: bool
    commit_sha: str | None = None
    specs_found: int = 0
    assets_created: int = 0
    assets_updated: int = 0
    contracts_published: int = 0
    proposals_created: int = 0
    services_created: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Git operations — subprocess with explicit args, no shell=True
# ---------------------------------------------------------------------------


def _sanitize_stderr(stderr: str, token: str | None) -> str:
    """Remove auth tokens from git stderr before including in error messages."""
    if token and token in stderr:
        return stderr.replace(token, "***")
    return stderr


@contextlib.asynccontextmanager
async def _ssh_key_env(ssh_key: str) -> AsyncIterator[dict[str, str]]:
    """Write an SSH deploy key to a temp file and yield GIT_SSH_COMMAND env vars.

    The temp file is created with mode 0600 (owner-only read/write) and
    deleted on exit.
    """
    fd, key_path = tempfile.mkstemp(prefix="tessera_ssh_", suffix=".pem")
    try:
        try:
            os.write(fd, ssh_key.encode("utf-8"))
            if not ssh_key.endswith("\n"):
                os.write(fd, b"\n")
        finally:
            os.close(fd)
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        yield {
            "GIT_SSH_COMMAND": (
                f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes"
            ),
        }
    finally:
        with contextlib.suppress(OSError):
            os.unlink(key_path)


def _inject_token(git_url: str, token: str | None) -> str:
    """Inject auth token into HTTPS git URL.

    Converts ``https://github.com/org/repo`` to
    ``https://x-access-token:{token}@github.com/org/repo``.
    """
    if not token or not git_url.startswith("https://"):
        return git_url
    return git_url.replace("https://", f"https://x-access-token:{token}@", 1)


async def _run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a git subprocess asynchronously.

    Args:
        args: Git command arguments (without the leading ``git``).
        cwd: Working directory.
        timeout: Timeout in seconds.
        extra_env: Additional environment variables merged into the subprocess env.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    timeout = timeout or settings.git_timeout
    cmd = ["git"] + args

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if extra_env:
        env.update(extra_env)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", f"Git operation timed out after {timeout}s"
    except BaseException:
        # CancelledError (from an outer asyncio.wait_for) or any other
        # interruption — kill the subprocess before re-raising so we
        # don't leak orphaned git processes.
        proc.kill()
        await proc.communicate()
        raise

    return (
        proc.returncode or 0,
        stdout_bytes.decode("utf-8", errors="replace").strip(),
        stderr_bytes.decode("utf-8", errors="replace").strip(),
    )


async def clone_or_pull(
    repo: RepoDB,
    token: str | None = None,
    ssh_key: str | None = None,
) -> tuple[str, str]:
    """Clone or pull a repository, returning (repo_dir, commit_sha).

    First sync: shallow clone (``--depth 1``).
    Subsequent syncs: ``git fetch --depth 1`` + ``git reset --hard FETCH_HEAD``.

    For SSH URLs (``git@``), uses the provided *ssh_key* via a temporary file
    and ``GIT_SSH_COMMAND``.  For HTTPS URLs, injects the *token* into the URL.

    Args:
        repo: The repository database model.
        token: Optional git auth token (HTTPS only).
        ssh_key: Optional PEM-encoded SSH deploy key (SSH URLs only).

    Returns:
        Tuple of (local_repo_path, HEAD_commit_sha).

    Raises:
        RuntimeError: If git operations fail.
    """
    base_dir = Path(settings.repo_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = base_dir / str(repo.id)

    is_ssh = repo.git_url.startswith("git@")
    auth_url = repo.git_url if is_ssh else _inject_token(repo.git_url, token)
    branch = repo.default_branch
    use_ssh = is_ssh and ssh_key is not None

    async def _do_clone_or_pull(extra_env: dict[str, str] | None) -> None:
        """Run the actual git clone/fetch+reset commands."""
        if (repo_dir / ".git").exists():
            rc, _, stderr = await _run_git(
                ["fetch", "--depth", "1", "--", auth_url, branch],
                cwd=str(repo_dir),
                extra_env=extra_env,
            )
            if rc != 0:
                raise RuntimeError(f"git fetch failed: {_sanitize_stderr(stderr, token)}")

            rc, _, stderr = await _run_git(
                ["reset", "--hard", "FETCH_HEAD"],
                cwd=str(repo_dir),
                extra_env=extra_env,
            )
            if rc != 0:
                raise RuntimeError(f"git reset failed: {_sanitize_stderr(stderr, token)}")
        else:
            rc, _, stderr = await _run_git(
                ["clone", "--depth", "1", "--branch", branch, "--", auth_url, str(repo_dir)],
                extra_env=extra_env,
            )
            if rc != 0:
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                raise RuntimeError(f"git clone failed: {_sanitize_stderr(stderr, token)}")

    if use_ssh:
        assert ssh_key is not None  # for mypy
        async with _ssh_key_env(ssh_key) as env:
            await _do_clone_or_pull(env)
    else:
        await _do_clone_or_pull(None)

    # Validate repo size
    max_bytes = settings.repo_max_size_mb * 1024 * 1024
    repo_size = _dir_size(repo_dir)
    if repo_size > max_bytes:
        shutil.rmtree(repo_dir, ignore_errors=True)
        raise RuntimeError(
            f"Repository exceeds size limit: "
            f"{repo_size / (1024 * 1024):.0f}MB > {settings.repo_max_size_mb}MB"
        )

    # Get current HEAD SHA
    rc, sha, stderr = await _run_git(
        ["rev-parse", "HEAD"],
        cwd=str(repo_dir),
    )
    if rc != 0:
        raise RuntimeError(f"git rev-parse failed: {_sanitize_stderr(stderr, token)}")

    return str(repo_dir), sha.strip()


def _dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            total += entry.stat().st_size
    return total


# ---------------------------------------------------------------------------
# Spec file discovery
# ---------------------------------------------------------------------------

# File extensions → spec type mapping
_OPENAPI_EXTENSIONS = {".yaml", ".yml", ".json"}
_GRPC_EXTENSIONS = {".proto"}
_GRAPHQL_EXTENSIONS = {".graphql", ".gql"}


def _classify_spec_file(file_path: Path, content: str) -> str | None:
    """Classify a spec file by extension and content.

    Returns:
        Spec type string ("openapi", "grpc", "graphql") or None.
    """
    ext = file_path.suffix.lower()

    if ext in _GRPC_EXTENSIONS:
        return "grpc"

    if ext in _GRAPHQL_EXTENSIONS:
        return "graphql"

    if ext in _OPENAPI_EXTENSIONS:
        # YAML/JSON — check for openapi key
        try:
            if ext == ".json":
                parsed = json.loads(content)
            else:
                parsed = yaml.safe_load(content)
            if isinstance(parsed, dict) and "openapi" in parsed:
                return "openapi"
        except Exception as e:
            logger.debug("Could not parse %s as YAML/JSON: %s", file_path, e)

    return None


def discover_specs(repo_dir: str, spec_paths: list[str]) -> list[DiscoveredSpec]:
    """Scan spec_paths globs for known spec file types.

    Args:
        repo_dir: Local path to the cloned repository.
        spec_paths: List of glob patterns or file paths to scan.

    Returns:
        List of discovered spec files.
    """
    root = Path(repo_dir)
    specs: list[DiscoveredSpec] = []
    seen: set[str] = set()

    for pattern in spec_paths:
        # Normalize pattern
        pattern = pattern.strip().strip("/")

        # If pattern is a directory (ends with / or no extension), scan recursively
        target = root / pattern
        if target.is_dir():
            candidates = list(target.rglob("*"))
        elif target.is_file():
            candidates = [target]
        else:
            # Treat as glob pattern
            candidates = list(root.glob(pattern))
            # Also try recursive glob if the pattern doesn't include **
            if not candidates and "**" not in pattern:
                candidates = list(root.glob("**/" + pattern))

        for candidate in candidates:
            if not candidate.is_file():
                continue

            # Reject symlinks — a cloned repo could contain symlinks
            # pointing outside the repo directory, allowing reads of
            # arbitrary host files.
            if candidate.is_symlink():
                continue

            rel_path = str(candidate.relative_to(root))
            if rel_path in seen:
                continue

            # Skip hidden directories and common non-spec paths
            parts = candidate.relative_to(root).parts
            if any(p.startswith(".") for p in parts):
                continue
            if any(p in ("node_modules", "vendor", "__pycache__", ".git") for p in parts):
                continue

            try:
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            spec_type = _classify_spec_file(candidate, content)
            if spec_type is not None:
                seen.add(rel_path)
                specs.append(
                    DiscoveredSpec(
                        file_path=rel_path,
                        spec_type=spec_type,
                        content=content,
                    )
                )

    return specs


# ---------------------------------------------------------------------------
# Service assignment
# ---------------------------------------------------------------------------


def _infer_service_name(spec_path: str) -> str:
    """Infer a service name from a spec file's directory path.

    Uses the nearest meaningful parent directory as the service name.
    E.g. ``services/orders/api/openapi.yaml`` → ``orders``.
    """
    parts = Path(spec_path).parent.parts

    # Filter out generic directory names
    generic = {"api", "proto", "graphql", "grpc", "openapi", "specs", "spec", "schema", "schemas"}
    meaningful = [p for p in parts if p.lower() not in generic and not p.startswith(".")]

    if meaningful:
        return meaningful[-1].replace("-", "_").replace(" ", "_")

    # Fallback: use the file stem
    return Path(spec_path).stem.replace("-", "_").replace(" ", "_")


def assign_spec_to_service(
    spec_path: str,
    services: list[ServiceDB],
) -> ServiceDB | None:
    """Find the service whose root_path is the longest prefix of the spec path.

    Args:
        spec_path: Repository-relative path to the spec file.
        services: Active services for this repo.

    Returns:
        The matching ServiceDB or None if no service matches.
    """
    best_match: ServiceDB | None = None
    best_length = 0

    for svc in services:
        root = svc.root_path.strip("/")
        # Normalize "." (from Path(".").str()) to empty string for matching
        if root == ".":
            root = ""
        if root == "" or root == "/":
            # Root service matches everything, but only as a fallback
            if best_match is None:
                best_match = svc
            continue

        # Check if the spec path starts with the service root_path
        if spec_path.startswith(root + "/") or spec_path == root:
            if len(root) > best_length:
                best_length = len(root)
                best_match = svc

    return best_match


# ---------------------------------------------------------------------------
# FQN generation for repo-synced assets
# ---------------------------------------------------------------------------


def generate_fqn(service_name: str, spec_type: str, operation_id: str) -> str:
    """Generate an FQN for a repo-synced asset.

    Format: ``{service_name}.{spec_type}.{operation_id}``
    """
    # Normalize service name
    svc = service_name.lower().replace("-", "_").replace(" ", "_")
    svc = "".join(c if c.isalnum() or c == "_" else "" for c in svc)
    while "__" in svc:
        svc = svc.replace("__", "_")
    svc = svc.strip("_") or "default"

    return f"{svc}.{spec_type}.{operation_id}"


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------


async def _ensure_service(
    session: AsyncSession,
    repo: RepoDB,
    spec_path: str,
    existing_services: list[ServiceDB],
) -> ServiceDB:
    """Find or create a service for a spec file.

    Tries to match against existing services by root_path. If no match,
    auto-creates a new service.
    """
    matched = assign_spec_to_service(spec_path, existing_services)
    if matched is not None:
        return matched

    # Auto-create service
    service_name = _infer_service_name(spec_path)
    parent = str(Path(spec_path).parent)
    root_path = "/" if parent == "." else parent

    # Check for name collision within the repo
    for svc in existing_services:
        if svc.name == service_name:
            # Name taken — append root path segment to disambiguate
            service_name = f"{service_name}_{Path(root_path).name}"
            break

    new_service = ServiceDB(
        name=service_name,
        repo_id=repo.id,
        root_path=root_path,
        owner_team_id=repo.owner_team_id,
    )
    session.add(new_service)
    await session.flush()
    await session.refresh(new_service)

    await audit.log_event(
        session=session,
        entity_type="service",
        entity_id=new_service.id,
        action=AuditAction.SERVICE_CREATED,
        actor_id=repo.owner_team_id,
        actor_type="agent",
        payload={
            "name": service_name,
            "repo_id": str(repo.id),
            "root_path": root_path,
            "auto_discovered": True,
        },
    )

    existing_services.append(new_service)
    return new_service


def _parse_spec(spec: DiscoveredSpec) -> list[dict[str, Any]]:
    """Parse a discovered spec file into a list of asset definitions.

    Each item has keys: fqn_suffix, resource_type, schema_def, metadata,
    guarantees, field_descriptions, field_tags, description.
    """
    results: list[dict[str, Any]] = []

    if spec.spec_type == "openapi":
        try:
            if spec.file_path.endswith(".json"):
                spec_dict = json.loads(spec.content)
            else:
                spec_dict = yaml.safe_load(spec.content)
        except Exception as e:
            logger.warning("Failed to parse OpenAPI spec %s: %s", spec.file_path, e)
            return []

        parse_result = parse_openapi(spec_dict)
        if parse_result.errors:
            for err in parse_result.errors:
                logger.warning("OpenAPI parse error in %s: %s", spec.file_path, err)

        for endpoint in parse_result.endpoints:
            # Build a compact operation identifier
            op_id = endpoint.operation_id
            if not op_id:
                path_part = (
                    endpoint.path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
                )
                op_id = (
                    f"{endpoint.method.lower()}_{path_part}"
                    if path_part
                    else endpoint.method.lower()
                )

            results.append(
                {
                    "fqn_suffix": f"rest.{op_id}",
                    "resource_type": ResourceType.API_ENDPOINT,
                    "schema_def": endpoint.combined_schema,
                    "metadata": {
                        "openapi_source": {
                            "api_title": parse_result.title,
                            "api_version": parse_result.version,
                            "path": endpoint.path,
                            "method": endpoint.method,
                            "operation_id": endpoint.operation_id,
                        },
                        "sync_source": spec.file_path,
                    },
                    "guarantees": endpoint.guarantees,
                    "description": endpoint.summary or endpoint.description,
                }
            )

    elif spec.spec_type == "grpc":
        grpc_result = parse_proto(spec.content)
        if grpc_result.errors:
            for err in grpc_result.errors:
                logger.warning("Proto parse error in %s: %s", spec.file_path, err)

        for rpc in grpc_result.rpc_methods:
            op_id = f"{rpc.service_name}_{rpc.method_name}"
            results.append(
                {
                    "fqn_suffix": f"grpc.{op_id}",
                    "resource_type": ResourceType.GRPC_SERVICE,
                    "schema_def": rpc.combined_schema,
                    "metadata": {
                        "grpc_source": {
                            "package": grpc_result.package,
                            "service": rpc.service_name,
                            "method": rpc.method_name,
                            "client_streaming": rpc.client_streaming,
                            "server_streaming": rpc.server_streaming,
                        },
                        "sync_source": spec.file_path,
                    },
                    "guarantees": None,
                    "description": None,
                }
            )

    elif spec.spec_type == "graphql":
        try:
            from tessera.services.graphql import (
                parse_graphql_introspection,
                sdl_to_introspection,
            )

            introspection = sdl_to_introspection(spec.content)
            gql_result = parse_graphql_introspection(introspection)
            if gql_result.errors:
                for err in gql_result.errors:
                    logger.warning("GraphQL parse error in %s: %s", spec.file_path, err)

            for op in gql_result.operations:
                results.append(
                    {
                        "fqn_suffix": f"graphql.{op.operation_type}_{op.name}",
                        "resource_type": ResourceType.GRAPHQL_QUERY,
                        "schema_def": op.combined_schema,
                        "metadata": {
                            "graphql_source": {
                                "schema_name": gql_result.schema_name,
                                "operation_name": op.name,
                                "operation_type": op.operation_type,
                            },
                            "sync_source": spec.file_path,
                        },
                        "guarantees": op.guarantees,
                        "description": op.description,
                    }
                )
        except ValueError as e:
            logger.warning("Failed to parse GraphQL SDL %s: %s", spec.file_path, e)

    return results


async def _ensure_asset(
    session: AsyncSession,
    fqn: str,
    service: ServiceDB,
    resource_type: ResourceType,
    metadata: dict[str, Any],
    description: str | None,
) -> tuple[AssetDB, bool]:
    """Find or create an asset by FQN.

    If the asset exists, updates its service_id and metadata.

    Returns:
        Tuple of (asset, created) where created is True if the asset was new.
    """
    result = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == fqn)
        .where(AssetDB.environment == "production")
        .where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()

    # Merge description into metadata so it's persisted (AssetDB has no
    # dedicated description column).
    if description:
        metadata = {**metadata, "description": description}

    if asset is not None:
        # Update if needed
        if asset.service_id != service.id:
            asset.service_id = service.id
        asset.metadata_ = {**asset.metadata_, **metadata}
        await session.flush()
        return asset, False

    # Create new asset
    asset = AssetDB(
        fqn=fqn,
        owner_team_id=service.owner_team_id,
        service_id=service.id,
        environment="production",
        resource_type=resource_type,
        metadata_=metadata,
    )
    session.add(asset)
    await session.flush()
    await session.refresh(asset)

    await audit.log_event(
        session=session,
        entity_type="asset",
        entity_id=asset.id,
        action=AuditAction.ASSET_CREATED,
        actor_id=service.owner_team_id,
        actor_type="agent",
        payload={"fqn": fqn, "service_id": str(service.id), "auto_discovered": True},
    )

    return asset, True


async def sync_repo(
    session: AsyncSession,
    repo: RepoDB,
    token: str | None = None,
) -> SyncResult:
    """Sync a single repository: clone/pull, discover specs, publish contracts.

    This is the core orchestrator called by both the manual trigger endpoint
    and the background polling worker.

    Token priority: explicit *token* arg > ``repo.git_token`` > ``settings.git_token``.
    SSH key: ``repo.ssh_key`` (no global fallback — deploy keys are per-repo).

    Args:
        session: Database session (caller manages the transaction).
        repo: The repository to sync.
        token: Optional git auth token override.

    Returns:
        SyncResult with details of what happened.
    """
    effective_token = token or repo.git_token or settings.git_token
    ssh_key: str | None = repo.ssh_key
    result = SyncResult(repo_id=repo.id, success=False)

    # 1. Clone or pull
    try:
        repo_dir, commit_sha = await clone_or_pull(repo, effective_token, ssh_key)
    except RuntimeError as e:
        result.errors.append(str(e))
        return result

    result.commit_sha = commit_sha

    # Short-circuit if nothing changed since last sync
    if repo.last_synced_commit == commit_sha:
        result.success = True
        result.warnings.append("No new commits since last sync")
        return result

    # 2. Discover spec files
    if not repo.spec_paths:
        result.warnings.append("No spec_paths configured — nothing to scan")
        result.success = True
        return result

    specs = await asyncio.to_thread(discover_specs, repo_dir, repo.spec_paths)
    result.specs_found = len(specs)

    if not specs:
        result.warnings.append("No spec files found matching configured paths")
        result.success = True
        return result

    # 3. Load existing services for this repo
    svc_result = await session.execute(
        select(ServiceDB).where(ServiceDB.repo_id == repo.id).where(ServiceDB.deleted_at.is_(None))
    )
    existing_services = list(svc_result.scalars().all())
    initial_service_count = len(existing_services)

    # 4. Parse specs and build contracts
    contracts_to_publish: list[ContractToPublish] = []
    created_asset_ids: set[UUID] = set()
    updated_asset_ids: set[UUID] = set()

    for spec in specs:
        parsed_items = _parse_spec(spec)
        if not parsed_items:
            continue

        for item in parsed_items:
            # Assign spec to a service (create if needed)
            service = await _ensure_service(session, repo, spec.file_path, existing_services)

            # Build FQN: {service_name}.{spec_type}.{operation_id}
            fqn = f"{service.name}.{item['fqn_suffix']}"

            # Ensure asset exists
            asset, was_created = await _ensure_asset(
                session,
                fqn=fqn,
                service=service,
                resource_type=item["resource_type"],
                metadata=item["metadata"],
                description=item.get("description"),
            )

            if was_created:
                created_asset_ids.add(asset.id)
            else:
                updated_asset_ids.add(asset.id)

            # Queue for publishing
            contracts_to_publish.append(
                ContractToPublish(
                    asset_id=asset.id,
                    schema_def=item["schema_def"],
                    compatibility_mode=CompatibilityMode.BACKWARD,
                    guarantees=item.get("guarantees"),
                )
            )

    result.services_created = len(existing_services) - initial_service_count
    result.assets_created = len(created_asset_ids)
    result.assets_updated = len(updated_asset_ids)

    # 5. Bulk publish contracts
    if contracts_to_publish:
        try:
            publish_result: BulkPublishResult = await bulk_publish_contracts(
                session=session,
                contracts=contracts_to_publish,
                published_by=repo.owner_team_id,
                dry_run=False,
                create_proposals_for_breaking=True,
            )
            result.contracts_published = publish_result.published
            result.proposals_created = publish_result.proposals_created

            # Collect any publish errors
            for pr in publish_result.results:
                if pr.error:
                    result.errors.append(f"Publish error for {pr.asset_fqn}: {pr.error}")
        except Exception as e:
            result.errors.append(f"Bulk publish failed: {e}")
            # Still record the commit so we don't retry the same failing
            # commit in an infinite loop on every poll cycle.
            repo.last_synced_at = datetime.now(UTC)
            repo.last_synced_commit = commit_sha
            await session.flush()
            return result

    # 6. Update repo sync state
    repo.last_synced_at = datetime.now(UTC)
    repo.last_synced_commit = commit_sha
    await session.flush()

    result.success = True
    return result


# ---------------------------------------------------------------------------
# Sync event persistence
# ---------------------------------------------------------------------------


async def save_sync_event(
    session: AsyncSession,
    result: SyncResult,
    *,
    duration_seconds: float | None = None,
    triggered_by: str = "worker",
) -> SyncEventDB:
    """Persist a sync result as a SyncEventDB row.

    Called from both the manual trigger endpoint and the background worker
    so that sync history is consistently recorded regardless of entry point.
    """
    event = SyncEventDB(
        repo_id=result.repo_id,
        success=result.success,
        commit_sha=result.commit_sha,
        specs_found=result.specs_found,
        contracts_published=result.contracts_published,
        proposals_created=result.proposals_created,
        services_created=result.services_created,
        assets_created=result.assets_created,
        assets_updated=result.assets_updated,
        errors=result.errors,
        duration_seconds=duration_seconds,
        triggered_by=triggered_by,
    )
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# Background polling worker
# ---------------------------------------------------------------------------


@dataclass
class _RepoSyncTarget:
    """Snapshot of repo fields needed for sync scheduling.

    Captures scalar values up front so we don't need to access ORM
    objects after a potential session rollback (which would expire them
    and raise MissingGreenlet in async SQLAlchemy).
    """

    repo_id: UUID
    name: str
    owner_team_id: UUID
    last_synced_at: datetime | None
    git_token: str | None
    ssh_key: str | None


async def _poll_once(session_maker: Any) -> None:
    """Run one polling cycle: find repos due for sync and sync them.

    Each repo gets its own session so that a rollback on one repo
    cannot expire ORM objects for subsequent repos.
    """
    # First, collect the list of repos due for sync.
    now = datetime.now(UTC)
    targets: list[_RepoSyncTarget] = []

    async with session_maker() as session:
        stmt = (
            select(RepoDB)
            .where(RepoDB.sync_enabled.is_(True))
            .where(RepoDB.deleted_at.is_(None))
            .where(func.json_array_length(RepoDB.spec_paths) > 0)
            .order_by(RepoDB.last_synced_at.asc().nullsfirst())
        )
        result = await session.execute(stmt)
        repos = list(result.scalars().all())

        for repo in repos:
            if repo.last_synced_at is not None:
                elapsed = (now - repo.last_synced_at).total_seconds()
                if elapsed < settings.sync_interval:
                    continue
            targets.append(
                _RepoSyncTarget(
                    repo_id=repo.id,
                    name=repo.name,
                    owner_team_id=repo.owner_team_id,
                    last_synced_at=repo.last_synced_at,
                    git_token=repo.git_token,
                    ssh_key=repo.ssh_key,
                )
            )

    # Process repos concurrently, bounded by sync_concurrency.
    semaphore = asyncio.Semaphore(settings.sync_concurrency)

    async def _sync_one(target: _RepoSyncTarget) -> None:
        async with semaphore, session_maker() as session:
            logger.info("Background sync starting for repo %s (%s)", target.name, target.repo_id)
            t0 = time.monotonic()
            sync_result: SyncResult | None = None
            try:
                repo_result = await session.execute(
                    select(RepoDB).where(RepoDB.id == target.repo_id)
                )
                repo = repo_result.scalar_one_or_none()
                if repo is None or repo.deleted_at is not None or not repo.sync_enabled:
                    return

                sync_result = await asyncio.wait_for(
                    sync_repo(session, repo),
                    timeout=settings.sync_timeout,
                )

                duration = time.monotonic() - t0
                if sync_result.success:
                    logger.info(
                        "Sync completed for %s: %d specs, %d contracts published (%.1fs)",
                        target.name,
                        sync_result.specs_found,
                        sync_result.contracts_published,
                        duration,
                    )
                else:
                    logger.warning("Sync failed for %s: %s", target.name, sync_result.errors)

                # Persist sync data, sync event, and audit log atomically.
                await save_sync_event(
                    session,
                    sync_result,
                    duration_seconds=duration,
                    triggered_by="worker",
                )
                await _log_sync_event(
                    session, target.repo_id, target.owner_team_id, sync_result
                ) if sync_result.success else await _log_sync_failed(
                    session,
                    target.repo_id,
                    target.owner_team_id,
                    sync_result.errors,
                    repo_name=target.name,
                    last_synced_at=target.last_synced_at,
                )
                await session.commit()

            except TimeoutError:
                await session.rollback()
                duration = time.monotonic() - t0
                logger.error("Sync timed out for repo %s", target.name)
                timeout_result = SyncResult(
                    repo_id=target.repo_id,
                    success=False,
                    errors=["Sync timed out"],
                )
                try:
                    await save_sync_event(
                        session,
                        timeout_result,
                        duration_seconds=duration,
                        triggered_by="worker",
                    )
                    await _log_sync_failed(
                        session,
                        target.repo_id,
                        target.owner_team_id,
                        ["Sync timed out"],
                        repo_name=target.name,
                        last_synced_at=target.last_synced_at,
                    )
                    await session.commit()
                except Exception:
                    logger.critical(
                        "AUDIT GAP: failed to persist sync event for repo %s "
                        "(repo_id=%s). The timeout occurred but no audit record "
                        "was saved. Manual investigation required.",
                        target.name,
                        target.repo_id,
                        exc_info=True,
                    )
            except Exception:
                await session.rollback()
                duration = time.monotonic() - t0
                logger.exception("Unexpected error syncing repo %s", target.name)
                error_result = SyncResult(
                    repo_id=target.repo_id,
                    success=False,
                    errors=["Unexpected error — see server logs"],
                )
                try:
                    await save_sync_event(
                        session,
                        error_result,
                        duration_seconds=duration,
                        triggered_by="worker",
                    )
                    await _log_sync_failed(
                        session,
                        target.repo_id,
                        target.owner_team_id,
                        ["Unexpected error — see server logs"],
                        repo_name=target.name,
                        last_synced_at=target.last_synced_at,
                    )
                    await session.commit()
                except Exception:
                    logger.critical(
                        "AUDIT GAP: failed to persist sync event for repo %s "
                        "(repo_id=%s). The sync error occurred but no audit "
                        "record was saved. Manual investigation required.",
                        target.name,
                        target.repo_id,
                        exc_info=True,
                    )

    await asyncio.gather(
        *[_sync_one(t) for t in targets],
        return_exceptions=True,
    )


async def _log_sync_event(
    session: AsyncSession,
    repo_id: UUID,
    owner_team_id: UUID,
    sync_result: SyncResult,
) -> None:
    """Log a successful sync audit event."""
    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo_id,
        action=AuditAction.REPO_SYNCED,
        actor_id=owner_team_id,
        actor_type="agent",
        payload={
            "commit_sha": sync_result.commit_sha,
            "specs_found": sync_result.specs_found,
            "contracts_published": sync_result.contracts_published,
            "proposals_created": sync_result.proposals_created,
            "services_created": sync_result.services_created,
        },
    )


async def _log_sync_failed(
    session: AsyncSession,
    repo_id: UUID,
    owner_team_id: UUID,
    errors: list[str],
    repo_name: str | None = None,
    last_synced_at: datetime | None = None,
) -> None:
    """Log a failed sync audit event and dispatch Slack notification."""
    from tessera.services.slack_dispatcher import dispatch_slack_notifications

    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo_id,
        action=AuditAction.REPO_SYNC_FAILED,
        actor_id=owner_team_id,
        actor_type="agent",
        payload={"errors": errors},
    )

    if repo_name:
        await dispatch_slack_notifications(
            session=session,
            event_type="repo.sync_failed",
            team_ids=[owner_team_id],
            payload={
                "repo_name": repo_name,
                "error_message": "; ".join(errors) if errors else "Unknown error",
                "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
                "repo_id": str(repo_id),
            },
        )


async def start_background_worker() -> asyncio.Task[None]:
    """Start the background repo sync polling loop.

    Returns the asyncio Task so the caller can cancel it on shutdown.
    """
    from tessera.db.database import get_async_session_maker

    session_maker = get_async_session_maker()

    async def _loop() -> None:
        logger.info("Repo sync background worker started (interval=%ds)", settings.sync_interval)
        while True:
            try:
                await _poll_once(session_maker)
            except Exception:
                logger.critical(
                    "Error in repo sync polling loop — "
                    "some repos may not have been synced this cycle",
                    exc_info=True,
                )
            await asyncio.sleep(settings.sync_interval)

    task = asyncio.create_task(_loop(), name="repo-sync-worker")
    return task
