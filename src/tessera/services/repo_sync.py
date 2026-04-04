"""Git-based repository sync worker and spec discovery.

Clones/pulls registered repos, discovers spec files, parses them using
existing sync logic (OpenAPI, GraphQL, gRPC), and creates/updates assets
and contracts through the contract publisher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tessera.config import settings
from tessera.db import AssetDB, RepoDB, ServiceDB
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
) -> tuple[int, str, str]:
    """Run a git subprocess asynchronously.

    Args:
        args: Git command arguments (without the leading ``git``).
        cwd: Working directory.
        timeout: Timeout in seconds.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    timeout = timeout or settings.git_timeout
    cmd = ["git"] + args

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", f"Git operation timed out after {timeout}s"

    return (
        proc.returncode or 0,
        stdout_bytes.decode("utf-8", errors="replace").strip(),
        stderr_bytes.decode("utf-8", errors="replace").strip(),
    )


async def clone_or_pull(
    repo: RepoDB,
    token: str | None = None,
) -> tuple[str, str]:
    """Clone or pull a repository, returning (repo_dir, commit_sha).

    First sync: shallow clone (``--depth 1``).
    Subsequent syncs: ``git fetch --depth 1`` + ``git reset --hard FETCH_HEAD``.

    Args:
        repo: The repository database model.
        token: Optional git auth token.

    Returns:
        Tuple of (local_repo_path, HEAD_commit_sha).

    Raises:
        RuntimeError: If git operations fail.
    """
    base_dir = Path(settings.repo_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = base_dir / str(repo.id)

    auth_url = _inject_token(repo.git_url, token)
    branch = repo.default_branch

    if (repo_dir / ".git").exists():
        # Pull: fetch + reset
        rc, _, stderr = await _run_git(
            ["fetch", "--depth", "1", auth_url, branch],
            cwd=str(repo_dir),
        )
        if rc != 0:
            raise RuntimeError(f"git fetch failed: {stderr}")

        rc, _, stderr = await _run_git(
            ["reset", "--hard", "FETCH_HEAD"],
            cwd=str(repo_dir),
        )
        if rc != 0:
            raise RuntimeError(f"git reset failed: {stderr}")
    else:
        # Clone: shallow clone
        rc, _, stderr = await _run_git(
            ["clone", "--depth", "1", "--branch", branch, auth_url, str(repo_dir)],
        )
        if rc != 0:
            # Clean up partial clone
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed: {stderr}")

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
        raise RuntimeError(f"git rev-parse failed: {stderr}")

    return str(repo_dir), sha.strip()


def _dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    for entry in path.rglob("*"):
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
        except Exception:
            pass

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
        if root == "" or root == "/":
            # Root service matches everything, but only as a fallback
            if best_match is None:
                best_match = svc
            continue

        # Check if the spec path starts with the service root_path
        if spec_path.startswith(root + "/") or spec_path.startswith(root):
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
    root_path = str(Path(spec_path).parent) or "/"

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
        # GraphQL SDL files can't be parsed by our introspection parser.
        # Log a warning — full SDL support requires the graphql-core library.
        logger.info(
            "GraphQL SDL file %s detected but SDL parsing is not yet supported. "
            "Use the /api/v1/sync/graphql endpoint with an introspection response instead.",
            spec.file_path,
        )

    return results


async def _ensure_asset(
    session: AsyncSession,
    fqn: str,
    service: ServiceDB,
    resource_type: ResourceType,
    metadata: dict[str, Any],
    description: str | None,
) -> AssetDB:
    """Find or create an asset by FQN.

    If the asset exists, updates its service_id and metadata.
    """
    result = await session.execute(
        select(AssetDB)
        .where(AssetDB.fqn == fqn)
        .where(AssetDB.environment == "production")
        .where(AssetDB.deleted_at.is_(None))
    )
    asset = result.scalar_one_or_none()

    if asset is not None:
        # Update if needed
        if asset.service_id != service.id:
            asset.service_id = service.id
        asset.metadata_ = {**asset.metadata_, **metadata}
        await session.flush()
        return asset

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

    return asset


async def sync_repo(
    session: AsyncSession,
    repo: RepoDB,
    token: str | None = None,
) -> SyncResult:
    """Sync a single repository: clone/pull, discover specs, publish contracts.

    This is the core orchestrator called by both the manual trigger endpoint
    and the background polling worker.

    Args:
        session: Database session (caller manages the transaction).
        repo: The repository to sync.
        token: Optional git auth token override. Falls back to settings.git_token.

    Returns:
        SyncResult with details of what happened.
    """
    token = token or settings.git_token
    result = SyncResult(repo_id=repo.id, success=False)

    # 1. Clone or pull
    try:
        repo_dir, commit_sha = await clone_or_pull(repo, token)
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
    asset_ids_created: set[UUID] = set()

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
            asset = await _ensure_asset(
                session,
                fqn=fqn,
                service=service,
                resource_type=item["resource_type"],
                metadata=item["metadata"],
                description=item.get("description"),
            )

            if asset.id not in asset_ids_created:
                asset_ids_created.add(asset.id)

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
    result.assets_created = len(asset_ids_created)

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
            return result

    # 6. Update repo sync state
    repo.last_synced_at = datetime.now(UTC)
    repo.last_synced_commit = commit_sha
    await session.flush()

    result.success = True
    return result


# ---------------------------------------------------------------------------
# Background polling worker
# ---------------------------------------------------------------------------


async def _poll_once(session_maker: Any) -> None:
    """Run one polling cycle: find repos due for sync and sync them."""
    async with session_maker() as session:
        # Find repos due for sync
        now = datetime.now(UTC)
        stmt = (
            select(RepoDB)
            .where(RepoDB.sync_enabled.is_(True))
            .where(RepoDB.deleted_at.is_(None))
            .where(RepoDB.spec_paths != "[]")  # Has spec paths configured
            .order_by(RepoDB.last_synced_at.asc().nullsfirst())
        )
        result = await session.execute(stmt)
        repos = list(result.scalars().all())

        for repo in repos:
            # Check if repo is due for sync
            if repo.last_synced_at is not None:
                elapsed = (now - repo.last_synced_at).total_seconds()
                if elapsed < settings.sync_interval:
                    continue

            logger.info("Background sync starting for repo %s (%s)", repo.name, repo.id)
            try:
                sync_result = await asyncio.wait_for(
                    sync_repo(session, repo),
                    timeout=settings.git_timeout,
                )
                await session.commit()

                if sync_result.success:
                    logger.info(
                        "Sync completed for %s: %d specs, %d contracts published",
                        repo.name,
                        sync_result.specs_found,
                        sync_result.contracts_published,
                    )
                    await _log_sync_event(session, repo, sync_result)
                    await session.commit()
                else:
                    logger.warning("Sync failed for %s: %s", repo.name, sync_result.errors)
                    await _log_sync_failed(session, repo, sync_result.errors)
                    await session.commit()

            except TimeoutError:
                await session.rollback()
                logger.error("Sync timed out for repo %s", repo.name)
                await _log_sync_failed(session, repo, ["Sync timed out"])
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Unexpected error syncing repo %s", repo.name)
                try:
                    await _log_sync_failed(session, repo, ["Unexpected error — see server logs"])
                    await session.commit()
                except Exception:
                    logger.exception("Failed to log sync failure for repo %s", repo.name)


async def _log_sync_event(
    session: AsyncSession,
    repo: RepoDB,
    sync_result: SyncResult,
) -> None:
    """Log a successful sync audit event."""
    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo.id,
        action=AuditAction.REPO_SYNCED,
        actor_id=repo.owner_team_id,
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
    repo: RepoDB,
    errors: list[str],
) -> None:
    """Log a failed sync audit event."""
    await audit.log_event(
        session=session,
        entity_type="repo",
        entity_id=repo.id,
        action=AuditAction.REPO_SYNC_FAILED,
        actor_id=repo.owner_team_id,
        actor_type="agent",
        payload={"errors": errors},
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
                logger.exception("Error in repo sync polling loop")
            await asyncio.sleep(settings.sync_interval)

    task = asyncio.create_task(_loop(), name="repo-sync-worker")
    return task
