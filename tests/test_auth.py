"""Tests for API key authentication."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import Base, TeamDB
from tessera.main import app
from tessera.services.auth import create_api_key, generate_api_key, hash_api_key, verify_api_key
from tessera.models.api_key import APIKeyCreate
from tessera.models.enums import APIKeyScope


# Test with auth enabled
TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")


def create_tables(connection):
    """Create all tables."""
    Base.metadata.create_all(connection, checkfirst=True)


def drop_tables(connection):
    """Drop all tables."""
    Base.metadata.drop_all(connection)


@pytest.fixture
async def auth_test_engine():
    """Create a test database engine for auth tests."""
    from tessera.db.database import dispose_engine

    connect_args = {}
    if _USE_SQLITE:
        connect_args = {"check_same_thread": False}

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args=connect_args,
    )
    yield engine
    await engine.dispose()
    # Also dispose the global engine if it was created
    await dispose_engine()


@pytest.fixture
async def auth_session(auth_test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a session for auth tests."""
    async with auth_test_engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(create_tables)

    async_session = async_sessionmaker(
        auth_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()

    async with auth_test_engine.begin() as conn:
        await conn.run_sync(drop_tables)


@pytest.fixture
async def auth_client(auth_test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with auth ENABLED."""
    from tessera.db import database
    from tessera.config import settings

    # Store original value
    original_auth_disabled = settings.auth_disabled

    # Enable auth for these tests
    settings.auth_disabled = False

    # Create schemas and tables
    async with auth_test_engine.begin() as conn:
        if not _USE_SQLITE:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.run_sync(create_tables)

    async_session = async_sessionmaker(
        auth_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[database.get_session] = get_test_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()

    # Restore original value
    settings.auth_disabled = original_auth_disabled

    async with auth_test_engine.begin() as conn:
        await conn.run_sync(drop_tables)


class TestAPIKeyGeneration:
    """Tests for API key generation."""

    def test_generate_api_key(self):
        """Test API key generation."""
        key, key_hash, prefix = generate_api_key("live")

        assert key.startswith("tess_live_")
        assert len(key) > 20
        assert key_hash.startswith("$argon2id$")  # argon2 hash format
        assert prefix.startswith("tess_live_")

    def test_hash_and_verify_api_key(self):
        """Test API key hashing and verification with argon2."""
        key = "tess_live_abc123"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)

        # With argon2, same key produces different hashes (salted)
        assert hash1 != hash2  # Different salts
        assert hash1.startswith("$argon2id$")
        assert hash2.startswith("$argon2id$")

        # But verification should work with either hash
        assert verify_api_key(key, hash1)
        assert verify_api_key(key, hash2)

        # Wrong key should fail verification
        assert not verify_api_key("wrong_key", hash1)
        assert not verify_api_key("tess_live_xyz789", hash1)


class TestAPIKeyService:
    """Tests for API key service."""

    async def test_create_api_key(self, auth_session: AsyncSession):
        """Test creating an API key."""
        # Create a team first
        team = TeamDB(name="test-team")
        auth_session.add(team)
        await auth_session.flush()

        # Create API key
        key_data = APIKeyCreate(
            name="Test Key",
            team_id=team.id,
            scopes=[APIKeyScope.READ, APIKeyScope.WRITE],
        )
        api_key = await create_api_key(auth_session, key_data)

        assert api_key.key.startswith("tess_live_")
        assert api_key.name == "Test Key"
        assert api_key.team_id == team.id
        assert APIKeyScope.READ in api_key.scopes
        assert APIKeyScope.WRITE in api_key.scopes

    async def test_create_api_key_team_not_found(self, auth_session: AsyncSession):
        """Test creating an API key for non-existent team."""
        from uuid import uuid4

        key_data = APIKeyCreate(
            name="Test Key",
            team_id=uuid4(),
            scopes=[APIKeyScope.READ],
        )

        with pytest.raises(ValueError, match="not found"):
            await create_api_key(auth_session, key_data)


class TestAuthEndpoints:
    """Tests for authentication on endpoints."""

    async def test_unauthenticated_request_rejected(self, auth_client: AsyncClient):
        """Test that unauthenticated requests are rejected."""
        # Try to create an asset without auth
        response = await auth_client.post(
            "/api/v1/assets",
            json={
                "fqn": "test.asset",
                "owner_team_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 401
        data = response.json()
        # App uses custom error handler that wraps in {"error": {...}}
        assert data["error"]["code"] == "MISSING_API_KEY"

    async def test_invalid_api_key_rejected(self, auth_client: AsyncClient):
        """Test that invalid API keys are rejected."""
        response = await auth_client.post(
            "/api/v1/assets",
            json={
                "fqn": "test.asset",
                "owner_team_id": "00000000-0000-0000-0000-000000000000",
            },
            headers={"Authorization": "Bearer invalid_key"},
        )
        assert response.status_code == 401
        data = response.json()
        # App uses custom error handler that wraps in {"error": {...}}
        assert data["error"]["code"] == "INVALID_API_KEY"

    async def test_health_endpoints_no_auth(self, auth_client: AsyncClient):
        """Test that health endpoints don't require auth."""
        response = await auth_client.get("/health")
        assert response.status_code == 200

        response = await auth_client.get("/health/ready")
        assert response.status_code == 200

        response = await auth_client.get("/health/live")
        assert response.status_code == 200

    async def test_read_endpoints_no_auth(self, auth_client: AsyncClient):
        """Test that GET endpoints don't require auth."""
        # List teams (read operation)
        response = await auth_client.get("/api/v1/teams")
        assert response.status_code == 200

        # List assets (read operation)
        response = await auth_client.get("/api/v1/assets")
        assert response.status_code == 200


class TestBootstrapKey:
    """Tests for bootstrap API key functionality."""

    async def test_bootstrap_key_creates_team(self, auth_test_engine):
        """Test that bootstrap key can create first team."""
        from tessera.db import database
        from tessera.config import settings

        # Set up bootstrap key
        original_auth_disabled = settings.auth_disabled
        original_bootstrap_key = settings.bootstrap_api_key

        settings.auth_disabled = False
        settings.bootstrap_api_key = "test_bootstrap_key_12345"

        try:
            # Create tables
            async with auth_test_engine.begin() as conn:
                if not _USE_SQLITE:
                    await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
                    await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
                    await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
                await conn.run_sync(create_tables)

            async_session = async_sessionmaker(
                auth_test_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
                async with async_session() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise

            app.dependency_overrides[database.get_session] = get_test_session

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                # Create team with bootstrap key
                response = await client.post(
                    "/api/v1/teams",
                    json={"name": "bootstrap-team"},
                    headers={"Authorization": f"Bearer {settings.bootstrap_api_key}"},
                )
                assert response.status_code == 201
                data = response.json()
                assert data["name"] == "bootstrap-team"

            app.dependency_overrides.clear()

            # Clean up
            async with auth_test_engine.begin() as conn:
                await conn.run_sync(drop_tables)

        finally:
            settings.auth_disabled = original_auth_disabled
            settings.bootstrap_api_key = original_bootstrap_key
