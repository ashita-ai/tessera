"""Tests for database initialization and configuration."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInitDb:
    """Tests for init_db function."""

    @pytest.mark.asyncio
    async def test_init_db_skips_when_auto_create_disabled(self):
        """init_db returns early when auto_create_tables is False."""
        with patch("tessera.db.database.settings") as mock_settings:
            mock_settings.auto_create_tables = False

            from tessera.db.database import init_db

            # Should return without doing anything
            await init_db()

    @pytest.mark.asyncio
    async def test_init_db_creates_tables_when_enabled(self):
        """init_db creates tables when auto_create_tables is True."""
        mock_conn = AsyncMock()
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine.begin = mock_begin

        with (
            patch("tessera.db.database.settings") as mock_settings,
            patch("tessera.db.database.get_engine", return_value=mock_engine),
            patch("tessera.db.database.Base") as mock_base,
        ):
            mock_settings.auto_create_tables = True
            mock_settings.database_url = "sqlite+aiosqlite:///:memory:"

            from tessera.db.database import init_db

            await init_db()

            # Should have called create_all
            mock_conn.run_sync.assert_called_once_with(mock_base.metadata.create_all)

    @pytest.mark.asyncio
    async def test_init_db_creates_schemas_for_postgres(self):
        """init_db creates schemas before tables for PostgreSQL."""
        mock_conn = AsyncMock()
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine.begin = mock_begin

        with (
            patch("tessera.db.database.settings") as mock_settings,
            patch("tessera.db.database.get_engine", return_value=mock_engine),
            patch("tessera.db.database.Base"),
        ):
            mock_settings.auto_create_tables = True
            mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost/db"

            from tessera.db.database import init_db

            await init_db()

            # Should have created schemas
            assert mock_conn.execute.call_count == 3  # core, workflow, audit schemas


class TestAutoCreateTablesSetting:
    """Tests for auto_create_tables config setting."""

    def test_auto_create_tables_default_is_true(self):
        """auto_create_tables defaults to True for development."""
        from tessera.config import Settings

        settings = Settings(database_url="sqlite:///:memory:")
        assert settings.auto_create_tables is True

    def test_auto_create_tables_can_be_disabled(self):
        """auto_create_tables can be set to False."""
        from tessera.config import Settings

        settings = Settings(database_url="sqlite:///:memory:", auto_create_tables=False)
        assert settings.auto_create_tables is False
