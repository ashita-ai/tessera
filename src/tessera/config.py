"""Application configuration."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default session secret - MUST be overridden in production
DEFAULT_SESSION_SECRET = "tessera-dev-secret-key-change-in-production"


class Settings(BaseSettings):  # type: ignore[misc]
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
    auto_create_tables: bool = True  # Set to False in production (use Alembic migrations)

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
    cors_allow_methods: list[str] = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Webhooks
    webhook_url: str | None = None
    webhook_secret: str | None = None

    # Slack notifications
    slack_webhook_url: str | None = None

    # Authentication
    auth_disabled: bool = False  # Set to True to disable auth (development only)
    bootstrap_api_key: str | None = None  # Initial admin API key for bootstrapping
    session_secret_key: str = DEFAULT_SESSION_SECRET  # Session signing key

    # Redis cache (optional)
    redis_url: str | None = None  # e.g., redis://localhost:6379/0
    cache_ttl: int = 300  # Default cache TTL in seconds (5 minutes)
    cache_ttl_contract: int = 600  # 10 minutes
    cache_ttl_asset: int = 300  # 5 minutes
    cache_ttl_team: int = 300  # 5 minutes
    cache_ttl_schema: int = 3600  # 1 hour

    # Rate Limiting
    rate_limit_read: str = "1000/minute"
    rate_limit_write: str = "100/minute"
    rate_limit_admin: str = "50/minute"
    rate_limit_global: str = "5000/minute"
    rate_limit_enabled: bool = True

    # Resource Constraints
    max_schema_size_bytes: int = 1_000_000  # 1MB
    max_schema_properties: int = 1000
    max_fqn_length: int = 1000
    max_team_name_length: int = 255
    default_environment: str = "production"

    # Analysis Defaults
    impact_depth_default: int = 5
    impact_depth_max: int = 10

    # Pagination Defaults
    pagination_limit_default: int = 50
    pagination_limit_max: int = 100

    # Database connection pool
    db_pool_size: int = 20  # Base pool size
    db_max_overflow: int = 10  # Additional connections under load
    db_pool_timeout: int = 30  # Seconds to wait for connection
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour


settings = Settings()
