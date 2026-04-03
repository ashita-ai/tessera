"""Tests for web login routes (POST /login)."""

import os

os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tessera.db.models import Base

TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_USE_SQLITE = TEST_DATABASE_URL.startswith("sqlite")

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def auth_client():
    """Client with auth enabled so web login actually works."""
    from tessera.config import settings
    from tessera.db import database
    from tessera.main import app

    original_auth = settings.auth_disabled
    settings.auth_disabled = False

    connect_args = {"check_same_thread": False} if _USE_SQLITE else {}
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, connect_args=connect_args)

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=True))

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
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
        follow_redirects=False,
    ) as client:
        # Seed a human user with password via direct DB insert
        from argon2 import PasswordHasher

        from tessera.db.models import TeamDB, UserDB
        from tessera.models.enums import UserRole, UserType

        hasher = PasswordHasher()
        async with session_maker() as session:
            team = TeamDB(name="login-test-team", metadata_={"test": True})
            session.add(team)
            await session.flush()

            human_user = UserDB(
                username="humanlogin",
                name="Human Login",
                user_type=UserType.HUMAN,
                password_hash=hasher.hash("testpassword123"),
                role=UserRole.USER,
                team_id=team.id,
            )
            session.add(human_user)

            bot_user = UserDB(
                username="botlogin",
                name="Bot Login",
                user_type=UserType.BOT,
                password_hash=hasher.hash("botpassword123"),
                role=UserRole.USER,
                team_id=team.id,
            )
            session.add(bot_user)
            await session.commit()

        yield client

    app.dependency_overrides.clear()
    settings.auth_disabled = original_auth

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c))
    await engine.dispose()


class TestWebLogin:
    """Tests for POST /login web route."""

    async def test_human_login_success(self, auth_client: AsyncClient):
        """Human user can log in via web form."""
        resp = await auth_client.post(
            "/login",
            data={"username": "humanlogin", "password": "testpassword123"},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    async def test_human_login_wrong_password(self, auth_client: AsyncClient):
        """Wrong password redirects to login with error."""
        resp = await auth_client.post(
            "/login",
            data={"username": "humanlogin", "password": "wrongpassword"},
        )
        assert resp.status_code == 302
        assert "error=invalid" in resp.headers["location"]

    async def test_bot_login_blocked(self, auth_client: AsyncClient):
        """Bot user cannot log in via web UI even with valid password."""
        resp = await auth_client.post(
            "/login",
            data={"username": "botlogin", "password": "botpassword123"},
        )
        assert resp.status_code == 302
        assert "error=invalid" in resp.headers["location"]

    async def test_nonexistent_user_login(self, auth_client: AsyncClient):
        """Login with nonexistent username redirects with error."""
        resp = await auth_client.post(
            "/login",
            data={"username": "nosuchuser", "password": "anything"},
        )
        assert resp.status_code == 302
        assert "error=invalid" in resp.headers["location"]
