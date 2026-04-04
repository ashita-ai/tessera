"""Tests for RepoDB and ServiceDB models.

Covers model creation, unique constraint enforcement, soft-delete behavior,
and FK relationships/cascades.
"""

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import AssetDB, Base, RepoDB, ServiceDB, TeamDB

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


@pytest.fixture
async def fk_session() -> AsyncGenerator[AsyncSession, None]:
    """Session with FK enforcement enabled (needed for SQLite FK tests)."""
    connect_args = {}
    if _USE_SQLITE:
        connect_args = {"check_same_thread": False}

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, connect_args=connect_args)

    if _USE_SQLITE:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_fk(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    async with engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_repo(test_session: AsyncSession) -> None:
    """RepoDB can be created with all required fields."""
    team = TeamDB(name="repo-test-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="order-service",
        git_url="https://github.com/acme/order-service.git",
        default_branch="main",
        spec_paths=["api/openapi.yaml"],
        owner_team_id=team.id,
        sync_enabled=True,
        codeowners_path=".github/CODEOWNERS",
    )
    test_session.add(repo)
    await test_session.flush()

    result = await test_session.get(RepoDB, repo.id)
    assert result is not None
    assert result.name == "order-service"
    assert result.git_url == "https://github.com/acme/order-service.git"
    assert result.default_branch == "main"
    assert result.spec_paths == ["api/openapi.yaml"]
    assert result.owner_team_id == team.id
    assert result.sync_enabled is True
    assert result.codeowners_path == ".github/CODEOWNERS"
    assert result.last_synced_at is None
    assert result.last_synced_commit is None
    assert result.created_at is not None
    assert result.deleted_at is None


@pytest.mark.asyncio
async def test_create_repo_defaults(test_session: AsyncSession) -> None:
    """RepoDB uses correct defaults for optional fields."""
    team = TeamDB(name="defaults-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="minimal-repo",
        git_url="https://github.com/acme/minimal.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    assert repo.default_branch == "main"
    assert repo.spec_paths == []
    assert repo.sync_enabled is True
    assert repo.codeowners_path is None


@pytest.mark.asyncio
async def test_create_service(test_session: AsyncSession) -> None:
    """ServiceDB can be created with all required fields."""
    team = TeamDB(name="svc-test-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-repo",
        git_url="https://github.com/acme/svc-repo.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    service = ServiceDB(
        name="order-service",
        repo_id=repo.id,
        root_path="services/orders/",
        otel_service_name="order-service",
        owner_team_id=team.id,
    )
    test_session.add(service)
    await test_session.flush()

    result = await test_session.get(ServiceDB, service.id)
    assert result is not None
    assert result.name == "order-service"
    assert result.repo_id == repo.id
    assert result.root_path == "services/orders/"
    assert result.otel_service_name == "order-service"
    assert result.owner_team_id == team.id
    assert result.created_at is not None
    assert result.deleted_at is None


@pytest.mark.asyncio
async def test_service_default_root_path(test_session: AsyncSession) -> None:
    """ServiceDB defaults root_path to '/'."""
    team = TeamDB(name="root-path-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="root-path-repo",
        git_url="https://github.com/acme/root-path.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    service = ServiceDB(
        name="single-service",
        repo_id=repo.id,
        owner_team_id=team.id,
    )
    test_session.add(service)
    await test_session.flush()

    assert service.root_path == "/"


@pytest.mark.asyncio
async def test_repo_team_relationship(test_session: AsyncSession) -> None:
    """RepoDB.owner_team relationship loads correctly."""
    team = TeamDB(name="rel-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="rel-repo",
        git_url="https://github.com/acme/rel-repo.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    # selectin loading means owner_team is already populated
    assert repo.owner_team is not None
    assert repo.owner_team.id == team.id
    assert repo.owner_team.name == "rel-team"


@pytest.mark.asyncio
async def test_repo_services_relationship(test_session: AsyncSession) -> None:
    """RepoDB.services lists linked services."""
    team = TeamDB(name="multi-svc-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="monorepo",
        git_url="https://github.com/acme/monorepo.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    svc1 = ServiceDB(name="svc-a", repo_id=repo.id, root_path="a/", owner_team_id=team.id)
    svc2 = ServiceDB(name="svc-b", repo_id=repo.id, root_path="b/", owner_team_id=team.id)
    test_session.add_all([svc1, svc2])
    await test_session.flush()

    # Refresh to populate the relationship
    await test_session.refresh(repo, ["services"])
    assert len(repo.services) == 2
    names = {s.name for s in repo.services}
    assert names == {"svc-a", "svc-b"}


@pytest.mark.asyncio
async def test_service_repo_relationship(test_session: AsyncSession) -> None:
    """ServiceDB.repo relationship loads correctly (selectin)."""
    team = TeamDB(name="svc-rel-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-rel-repo",
        git_url="https://github.com/acme/svc-rel.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    service = ServiceDB(name="svc-x", repo_id=repo.id, owner_team_id=team.id)
    test_session.add(service)
    await test_session.flush()

    assert service.repo is not None
    assert service.repo.id == repo.id
    assert service.repo.name == "svc-rel-repo"


@pytest.mark.asyncio
async def test_asset_service_relationship(test_session: AsyncSession) -> None:
    """AssetDB.service_id FK links asset to a service."""
    team = TeamDB(name="asset-svc-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="asset-svc-repo",
        git_url="https://github.com/acme/asset-svc.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    service = ServiceDB(name="order-svc", repo_id=repo.id, owner_team_id=team.id)
    test_session.add(service)
    await test_session.flush()

    asset = AssetDB(
        fqn="order-svc.rest.create_order",
        owner_team_id=team.id,
        service_id=service.id,
    )
    test_session.add(asset)
    await test_session.flush()

    result = await test_session.get(AssetDB, asset.id)
    assert result is not None
    assert result.service_id == service.id


@pytest.mark.asyncio
async def test_asset_service_id_nullable(test_session: AsyncSession) -> None:
    """AssetDB.service_id is nullable — existing assets work without a service."""
    team = TeamDB(name="no-svc-team")
    test_session.add(team)
    await test_session.flush()

    asset = AssetDB(
        fqn="standalone.rest.endpoint",
        owner_team_id=team.id,
    )
    test_session.add(asset)
    await test_session.flush()

    assert asset.service_id is None


@pytest.mark.asyncio
async def test_service_assets_relationship(test_session: AsyncSession) -> None:
    """ServiceDB.assets lists linked assets."""
    team = TeamDB(name="svc-assets-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-assets-repo",
        git_url="https://github.com/acme/svc-assets.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    service = ServiceDB(name="payments", repo_id=repo.id, owner_team_id=team.id)
    test_session.add(service)
    await test_session.flush()

    a1 = AssetDB(fqn="payments.rest.charge", owner_team_id=team.id, service_id=service.id)
    a2 = AssetDB(fqn="payments.rest.refund", owner_team_id=team.id, service_id=service.id)
    test_session.add_all([a1, a2])
    await test_session.flush()

    await test_session.refresh(service, ["assets"])
    assert len(service.assets) == 2
    fqns = {a.fqn for a in service.assets}
    assert fqns == {"payments.rest.charge", "payments.rest.refund"}


# --- Unique constraint enforcement ---


@pytest.mark.asyncio
async def test_repo_unique_name_among_active(test_session: AsyncSession) -> None:
    """Two active repos cannot share the same name."""
    team = TeamDB(name="uniq-name-team")
    test_session.add(team)
    await test_session.flush()

    repo1 = RepoDB(
        name="dupe-repo",
        git_url="https://github.com/acme/dupe1.git",
        owner_team_id=team.id,
    )
    test_session.add(repo1)
    await test_session.flush()

    repo2 = RepoDB(
        name="dupe-repo",
        git_url="https://github.com/acme/dupe2.git",
        owner_team_id=team.id,
    )
    test_session.add(repo2)

    with pytest.raises(IntegrityError):
        await test_session.flush()


@pytest.mark.asyncio
async def test_repo_unique_git_url_among_active(test_session: AsyncSession) -> None:
    """Two active repos cannot share the same git_url."""
    team = TeamDB(name="uniq-url-team")
    test_session.add(team)
    await test_session.flush()

    repo1 = RepoDB(
        name="repo-a",
        git_url="https://github.com/acme/shared.git",
        owner_team_id=team.id,
    )
    test_session.add(repo1)
    await test_session.flush()

    repo2 = RepoDB(
        name="repo-b",
        git_url="https://github.com/acme/shared.git",
        owner_team_id=team.id,
    )
    test_session.add(repo2)

    with pytest.raises(IntegrityError):
        await test_session.flush()


@pytest.mark.asyncio
async def test_service_unique_name_repo_among_active(test_session: AsyncSession) -> None:
    """Two active services in the same repo cannot share the same name."""
    team = TeamDB(name="svc-uniq-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-uniq-repo",
        git_url="https://github.com/acme/svc-uniq.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    svc1 = ServiceDB(name="orders", repo_id=repo.id, root_path="a/", owner_team_id=team.id)
    test_session.add(svc1)
    await test_session.flush()

    svc2 = ServiceDB(name="orders", repo_id=repo.id, root_path="b/", owner_team_id=team.id)
    test_session.add(svc2)

    with pytest.raises(IntegrityError):
        await test_session.flush()


@pytest.mark.asyncio
async def test_service_same_name_different_repos(test_session: AsyncSession) -> None:
    """Services in different repos can share the same name."""
    team = TeamDB(name="cross-repo-team")
    test_session.add(team)
    await test_session.flush()

    repo1 = RepoDB(
        name="cross-repo-1",
        git_url="https://github.com/acme/cross1.git",
        owner_team_id=team.id,
    )
    repo2 = RepoDB(
        name="cross-repo-2",
        git_url="https://github.com/acme/cross2.git",
        owner_team_id=team.id,
    )
    test_session.add_all([repo1, repo2])
    await test_session.flush()

    svc1 = ServiceDB(name="orders", repo_id=repo1.id, owner_team_id=team.id)
    svc2 = ServiceDB(name="orders", repo_id=repo2.id, owner_team_id=team.id)
    test_session.add_all([svc1, svc2])
    await test_session.flush()

    # Both should persist without error
    assert svc1.id != svc2.id


# --- Soft-delete behavior ---


@pytest.mark.asyncio
async def test_repo_soft_delete_allows_name_reuse(test_session: AsyncSession) -> None:
    """After soft-deleting a repo, the name can be reused by a new repo."""
    team = TeamDB(name="soft-del-team")
    test_session.add(team)
    await test_session.flush()

    repo1 = RepoDB(
        name="recyclable",
        git_url="https://github.com/acme/recyclable.git",
        owner_team_id=team.id,
    )
    test_session.add(repo1)
    await test_session.flush()

    # Soft-delete the first repo
    repo1.deleted_at = datetime.now(UTC)
    await test_session.flush()

    # Create a new repo with the same name
    repo2 = RepoDB(
        name="recyclable",
        git_url="https://github.com/acme/recyclable-v2.git",
        owner_team_id=team.id,
    )
    test_session.add(repo2)
    await test_session.flush()

    assert repo2.id != repo1.id


@pytest.mark.asyncio
async def test_repo_soft_delete_allows_git_url_reuse(test_session: AsyncSession) -> None:
    """After soft-deleting a repo, the git_url can be reused."""
    team = TeamDB(name="url-recycle-team")
    test_session.add(team)
    await test_session.flush()

    repo1 = RepoDB(
        name="url-repo-1",
        git_url="https://github.com/acme/reusable-url.git",
        owner_team_id=team.id,
    )
    test_session.add(repo1)
    await test_session.flush()

    repo1.deleted_at = datetime.now(UTC)
    await test_session.flush()

    repo2 = RepoDB(
        name="url-repo-2",
        git_url="https://github.com/acme/reusable-url.git",
        owner_team_id=team.id,
    )
    test_session.add(repo2)
    await test_session.flush()

    assert repo2.id != repo1.id


@pytest.mark.asyncio
async def test_service_soft_delete_allows_name_reuse(test_session: AsyncSession) -> None:
    """After soft-deleting a service, its name+repo can be reused."""
    team = TeamDB(name="svc-recycle-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-recycle-repo",
        git_url="https://github.com/acme/svc-recycle.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    svc1 = ServiceDB(name="recyclable-svc", repo_id=repo.id, owner_team_id=team.id)
    test_session.add(svc1)
    await test_session.flush()

    svc1.deleted_at = datetime.now(UTC)
    await test_session.flush()

    svc2 = ServiceDB(name="recyclable-svc", repo_id=repo.id, owner_team_id=team.id)
    test_session.add(svc2)
    await test_session.flush()

    assert svc2.id != svc1.id


# --- FK integrity ---


@pytest.mark.asyncio
async def test_repo_requires_valid_team(fk_session: AsyncSession) -> None:
    """RepoDB.owner_team_id must reference an existing team."""
    repo = RepoDB(
        name="orphan-repo",
        git_url="https://github.com/acme/orphan.git",
        owner_team_id=uuid4(),  # Non-existent team
    )
    fk_session.add(repo)

    with pytest.raises(IntegrityError):
        await fk_session.flush()


@pytest.mark.asyncio
async def test_service_requires_valid_repo(fk_session: AsyncSession) -> None:
    """ServiceDB.repo_id must reference an existing repo."""
    team = TeamDB(name="orphan-svc-team")
    fk_session.add(team)
    await fk_session.flush()

    service = ServiceDB(
        name="orphan-svc",
        repo_id=uuid4(),  # Non-existent repo
        owner_team_id=team.id,
    )
    fk_session.add(service)

    with pytest.raises(IntegrityError):
        await fk_session.flush()


@pytest.mark.asyncio
async def test_service_requires_valid_team(fk_session: AsyncSession) -> None:
    """ServiceDB.owner_team_id must reference an existing team."""
    team = TeamDB(name="valid-team-for-repo")
    fk_session.add(team)
    await fk_session.flush()

    repo = RepoDB(
        name="has-repo",
        git_url="https://github.com/acme/has-repo.git",
        owner_team_id=team.id,
    )
    fk_session.add(repo)
    await fk_session.flush()

    service = ServiceDB(
        name="bad-team-svc",
        repo_id=repo.id,
        owner_team_id=uuid4(),  # Non-existent team
    )
    fk_session.add(service)

    with pytest.raises(IntegrityError):
        await fk_session.flush()


@pytest.mark.asyncio
async def test_asset_invalid_service_id_rejected(fk_session: AsyncSession) -> None:
    """AssetDB.service_id must reference an existing service if set."""
    team = TeamDB(name="bad-svc-id-team")
    fk_session.add(team)
    await fk_session.flush()

    asset = AssetDB(
        fqn="bad.rest.endpoint",
        owner_team_id=team.id,
        service_id=uuid4(),  # Non-existent service
    )
    fk_session.add(asset)

    with pytest.raises(IntegrityError):
        await fk_session.flush()


# --- Query filtering with soft-delete ---


@pytest.mark.asyncio
async def test_query_active_repos(test_session: AsyncSession) -> None:
    """Filtering by deleted_at IS NULL excludes soft-deleted repos."""
    team = TeamDB(name="filter-team")
    test_session.add(team)
    await test_session.flush()

    active = RepoDB(
        name="active-repo",
        git_url="https://github.com/acme/active.git",
        owner_team_id=team.id,
    )
    deleted = RepoDB(
        name="deleted-repo",
        git_url="https://github.com/acme/deleted.git",
        owner_team_id=team.id,
        deleted_at=datetime.now(UTC),
    )
    test_session.add_all([active, deleted])
    await test_session.flush()

    result = await test_session.execute(select(RepoDB).where(RepoDB.deleted_at.is_(None)))
    repos = result.scalars().all()
    names = [r.name for r in repos]
    assert "active-repo" in names
    assert "deleted-repo" not in names


@pytest.mark.asyncio
async def test_query_active_services(test_session: AsyncSession) -> None:
    """Filtering by deleted_at IS NULL excludes soft-deleted services."""
    team = TeamDB(name="svc-filter-team")
    test_session.add(team)
    await test_session.flush()

    repo = RepoDB(
        name="svc-filter-repo",
        git_url="https://github.com/acme/svc-filter.git",
        owner_team_id=team.id,
    )
    test_session.add(repo)
    await test_session.flush()

    active = ServiceDB(name="active-svc", repo_id=repo.id, owner_team_id=team.id)
    deleted = ServiceDB(
        name="deleted-svc",
        repo_id=repo.id,
        root_path="old/",
        owner_team_id=team.id,
        deleted_at=datetime.now(UTC),
    )
    test_session.add_all([active, deleted])
    await test_session.flush()

    result = await test_session.execute(select(ServiceDB).where(ServiceDB.deleted_at.is_(None)))
    services = result.scalars().all()
    names = [s.name for s in services]
    assert "active-svc" in names
    assert "deleted-svc" not in names
