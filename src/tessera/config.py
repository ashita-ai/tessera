"""Application configuration."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",  # No prefix, use exact names
    )

    # Environment
    environment: str = "development"

    # Database
    database_url: str = "postgresql+asyncpg://tessera:tessera@localhost:5432/tessera"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Git sync (optional - must be explicitly configured for sync endpoints)
    git_sync_path: Path | None = None

    # Webhooks
    webhook_url: str | None = None
    webhook_secret: str | None = None

    # Authentication
    auth_disabled: bool = False  # Set to True to disable auth (development only)
    bootstrap_api_key: str | None = None  # Initial admin API key for bootstrapping

    # Redis cache (optional)
    redis_url: str | None = None  # e.g., redis://localhost:6379/0
    cache_ttl: int = 300  # Default cache TTL in seconds (5 minutes)

    # Database connection pool
    db_pool_size: int = 20  # Base pool size
    db_max_overflow: int = 10  # Additional connections under load
    db_pool_timeout: int = 30  # Seconds to wait for connection
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour


settings = Settings()
