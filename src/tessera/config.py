"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://tessera:tessera@localhost:5432/tessera"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False

    # Git sync
    git_sync_path: Path = Path("./contracts")

    # Webhooks
    webhook_url: str | None = None
    webhook_secret: str | None = None


settings = Settings()
