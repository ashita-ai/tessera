"""Application configuration."""

from pydantic import Field, field_validator, model_validator
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

    # ── Environment ──────────────────────────────────────────────

    environment: str = Field(
        default="development",
        description="Runtime environment. Controls security validations "
        "and middleware behavior. Values: development, test, production.",
    )

    # ── Logging ──────────────────────────────────────────────────

    log_level: str = Field(
        default="INFO",
        description="Root log level. Values: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    log_format: str = Field(
        default="text",
        description="Log output format. 'text' for human-readable (development), "
        "'json' for structured JSON (production, CloudWatch, Datadog).",
    )

    # ── Database ─────────────────────────────────────────────────

    database_url: str = Field(
        default="postgresql+asyncpg://tessera:tessera@localhost:5432/tessera",
        description="SQLAlchemy async database URL. "
        "Use postgresql+asyncpg:// for production, sqlite+aiosqlite:// for tests.",
    )
    auto_create_tables: bool = Field(
        default=True,
        description="Auto-create tables on startup. "
        "WARNING: Must be False in production — use Alembic migrations instead.",
    )

    # ── CORS ─────────────────────────────────────────────────────

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        description="Allowed CORS origins. Accepts a JSON list or comma-separated string.",
    )
    cors_allow_methods: list[str] = Field(
        default=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods for CORS. "
        "In production, restricted to this list; in dev, allows all.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ── Webhooks ─────────────────────────────────────────────────

    webhook_url: str | None = Field(
        default=None,
        description="Default webhook URL for event notifications. Per-team webhooks override this.",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="HMAC secret for signing webhook payloads. "
        "Recipients verify signatures to authenticate events.",
    )
    webhook_allowed_domains: list[str] = Field(
        default=[],
        description="Allowlist of domains for webhook URLs. "
        "Empty list allows all domains. Comma-separated string or JSON list.",
    )
    webhook_dns_timeout: float = Field(
        default=5.0,
        description="DNS resolution timeout in seconds for webhook URL validation.",
    )

    @field_validator("webhook_allowed_domains", mode="before")
    @classmethod
    def parse_webhook_allowed_domains(cls, v: str | list[str]) -> list[str]:
        """Parse webhook allowed domains from comma-separated string or list."""
        if isinstance(v, str):
            return [domain.strip() for domain in v.split(",") if domain.strip()]
        return v

    # ── Slack ────────────────────────────────────────────────────

    slack_webhook_url: str | None = Field(
        default=None,
        description="Slack incoming webhook URL for notifications.",
    )
    slack_enabled: bool = Field(
        default=False,
        description="Enable team-scoped Slack notifications globally.",
    )
    tessera_base_url: str = Field(
        default="http://localhost:3000",
        description="Base URL for deep links in Slack messages.",
    )
    slack_rate_limit_per_second: int = Field(
        default=1,
        description="Max Slack API calls per second (Slack's limit is 1/sec per channel).",
    )

    # ── Authentication ───────────────────────────────────────────

    auth_disabled: bool = Field(
        default=False,
        description="Disable authentication. WARNING: Development only — "
        "all requests receive mock admin credentials.",
    )
    bootstrap_api_key: str | None = Field(
        default=None,
        description="Initial admin API key for bootstrapping. "
        "Used to create the first team and API keys.",
    )
    session_secret_key: str = Field(
        default=DEFAULT_SESSION_SECRET,
        description="Secret key for signing session cookies. "
        "WARNING: Must be changed from default in production.",
    )

    # ── Admin Bootstrap ──────────────────────────────────────────

    admin_username: str | None = Field(
        default=None,
        description="Bootstrap admin username. Creates or updates an admin "
        "user on startup (idempotent, safe for k8s restarts). "
        "Bootstrap is skipped unless both ADMIN_USERNAME and ADMIN_PASSWORD are set.",
    )
    admin_password: str | None = Field(
        default=None,
        description="Bootstrap admin user password. "
        "WARNING: Use a strong password in production; rotated via env var. "
        "Bootstrap is skipped unless both ADMIN_USERNAME and ADMIN_PASSWORD are set.",
    )
    admin_name: str = Field(
        default="Admin",
        description="Display name for the bootstrap admin user.",
    )
    admin_email: str | None = Field(
        default=None,
        description="Optional email for the bootstrap admin user.",
    )

    # ── Demo Mode ────────────────────────────────────────────────

    demo_mode: bool = Field(
        default=False,
        description="Show demo credentials on the login page.",
    )

    # ── Redis Cache ──────────────────────────────────────────────

    redis_url: str | None = Field(
        default=None,
        description="Redis connection URL (e.g. redis://localhost:6379/0). "
        "When unset, caching is disabled and all operations fall through.",
    )
    redis_connect_timeout: float = Field(
        default=0.05,
        description="Redis socket connect timeout in seconds. "
        "Low values (50ms) ensure fast failure when Redis is unavailable.",
    )
    redis_socket_timeout: float = Field(
        default=0.05,
        description="Redis socket operation timeout in seconds.",
    )
    cache_ttl: int = Field(
        default=300,
        description="Default cache TTL in seconds (5 minutes).",
    )
    cache_ttl_contract: int = Field(
        default=600,
        description="Cache TTL for contracts in seconds (10 minutes).",
    )
    cache_ttl_asset: int = Field(
        default=300,
        description="Cache TTL for assets in seconds (5 minutes).",
    )
    cache_ttl_team: int = Field(
        default=300,
        description="Cache TTL for teams in seconds (5 minutes).",
    )
    cache_ttl_schema: int = Field(
        default=3600,
        description="Cache TTL for schema diffs in seconds (1 hour). "
        "Longer because schemas change infrequently.",
    )

    # ── Rate Limiting ────────────────────────────────────────────

    rate_limit_read: str = Field(
        default="1000/minute",
        description="Per-key rate limit for read (GET) endpoints.",
    )
    rate_limit_write: str = Field(
        default="100/minute",
        description="Per-key rate limit for write (POST/PUT/PATCH) endpoints.",
    )
    rate_limit_admin: str = Field(
        default="50/minute",
        description="Per-key rate limit for admin (DELETE, key management) endpoints.",
    )
    rate_limit_auth: str = Field(
        default="30/minute",
        description="Per-key rate limit for authentication attempts. "
        "Stricter to prevent brute-force attacks.",
    )
    rate_limit_global: str = Field(
        default="5000/minute",
        description="Global rate limit across all endpoints per key.",
    )
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting. "
        "WARNING: Must be True in production to prevent API abuse.",
    )
    rate_limit_expensive: str = Field(
        default="20/minute",
        description="Per-team rate limit for expensive operations (schema diff, lineage analysis).",
    )
    rate_limit_bulk: str = Field(
        default="10/minute",
        description="Per-team rate limit for bulk operations.",
    )
    rate_limit_agent_read: str = Field(
        default="5000/minute",
        description="Per-key rate limit for agent read (GET) endpoints.",
    )
    rate_limit_agent_write: str = Field(
        default="500/minute",
        description="Per-key rate limit for agent write (POST/PUT/PATCH) endpoints.",
    )
    rate_limit_agent_admin: str = Field(
        default="250/minute",
        description="Per-key rate limit for agent admin (DELETE, key management) endpoints.",
    )

    # ── Resource Constraints ─────────────────────────────────────

    max_schema_size_bytes: int = Field(
        default=1_000_000,
        description="Maximum schema size in bytes (1 MB). "
        "Prevents DoS from extremely large schema payloads.",
    )
    max_schema_properties: int = Field(
        default=1000,
        description="Maximum total properties across all nesting levels in a schema.",
    )
    max_schema_nesting_depth: int = Field(
        default=10,
        description="Maximum nesting depth for schema objects. "
        "Prevents DoS from deeply recursive schema definitions.",
    )
    max_fqn_length: int = Field(
        default=1000,
        description="Maximum length for fully-qualified asset names.",
    )
    max_team_name_length: int = Field(
        default=255,
        description="Maximum length for team names.",
    )
    default_environment: str = Field(
        default="production",
        description="Default environment tag for assets created without one.",
    )

    # ── Analysis ─────────────────────────────────────────────────

    impact_depth_default: int = Field(
        default=5,
        description="Default depth for impact/lineage analysis traversal.",
    )
    impact_depth_max: int = Field(
        default=10,
        description="Maximum allowed depth for impact/lineage analysis. "
        "Caps user-provided depth to prevent expensive recursive queries.",
    )

    # ── Proposal Expiration ──────────────────────────────────────

    proposal_default_expiration_days: int = Field(
        default=30,
        description="Days until a pending proposal expires automatically.",
    )
    proposal_auto_expire_enabled: bool = Field(
        default=True,
        description="Enable automatic expiration of stale proposals.",
    )

    # ── Pagination ───────────────────────────────────────────────

    pagination_limit_default: int = Field(
        default=50,
        description="Default page size when limit is not specified.",
    )
    pagination_limit_max: int = Field(
        default=100,
        description="Maximum allowed page size. Requests above this are clamped.",
    )

    # ── Database Connection Pool ─────────────────────────────────

    db_pool_size: int = Field(
        default=20,
        description="Base connection pool size.",
    )
    db_max_overflow: int = Field(
        default=10,
        description="Additional connections allowed beyond pool_size under load.",
    )
    db_pool_timeout: int = Field(
        default=30,
        description="Seconds to wait for a connection from the pool before raising.",
    )
    db_pool_recycle: int = Field(
        default=3600,
        description="Recycle (close and reopen) connections after this many seconds. "
        "Prevents stale connections from accumulating.",
    )

    # ── Repo Sync ──────────────────────────────────────────────

    repo_dir: str = Field(
        default="./data/repos",
        description="Directory for cloned repositories.",
        alias="TESSERA_REPO_DIR",
    )
    git_token: str | None = Field(
        default=None,
        description="Git auth token for private repos. "
        "Injected into HTTPS clone URLs as x-access-token.",
        alias="TESSERA_GIT_TOKEN",
    )
    sync_interval: int = Field(
        default=60,
        description="Background worker poll interval in seconds.",
        alias="TESSERA_SYNC_INTERVAL",
    )
    repo_max_size_mb: int = Field(
        default=500,
        description="Maximum clone size in megabytes.",
        alias="TESSERA_REPO_MAX_SIZE_MB",
    )
    git_timeout: int = Field(
        default=120,
        description="Git operation timeout in seconds.",
        alias="TESSERA_GIT_TIMEOUT",
    )
    sync_timeout: int = Field(
        default=600,
        description="Overall sync operation timeout in seconds. "
        "Should be larger than git_timeout since a sync involves "
        "multiple git operations plus DB work.",
        alias="TESSERA_SYNC_TIMEOUT",
    )

    # ── OTEL Dependency Discovery ─────────────────────────────

    otel_enabled: bool = Field(
        default=False,
        description="Enable OTEL-based dependency discovery. "
        "When False, OTEL config CRUD endpoints still work but sync is a no-op.",
        alias="TESSERA_OTEL_ENABLED",
    )
    otel_poll_interval: int = Field(
        default=3600,
        description="Default polling interval in seconds for OTEL backends.",
        alias="TESSERA_OTEL_POLL_INTERVAL",
    )
    otel_min_confidence: float = Field(
        default=0.3,
        description="Minimum confidence score to create an OTEL-discovered dependency edge.",
        alias="TESSERA_OTEL_MIN_CONFIDENCE",
    )
    otel_stale_multiplier: int = Field(
        default=3,
        description="Mark OTEL dependency stale after N * lookback_seconds without observation.",
        alias="TESSERA_OTEL_STALE_MULTIPLIER",
    )

    @model_validator(mode="after")
    def validate_production_config(self) -> "Settings":
        """Validate configuration is safe for production deployment.

        Fails fast if production environment has dangerous settings that could
        compromise security or data integrity.
        """
        # Session secret must be changed from default in any non-dev/test environment.
        # This catches staging, production, and any other environment with real data.
        if (
            self.environment not in ("development", "test")
            and self.session_secret_key == DEFAULT_SESSION_SECRET
        ):
            raise ValueError(
                f"SESSION_SECRET_KEY must be set to a unique value in {self.environment}. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        if self.environment != "production":
            return self

        errors: list[str] = []

        # Auto-create tables should be disabled (use migrations instead)
        if self.auto_create_tables:
            errors.append(
                "AUTO_CREATE_TABLES must be False in production. "
                "Use Alembic migrations for schema changes."
            )

        # Authentication must be enabled
        if self.auth_disabled:
            errors.append(
                "AUTH_DISABLED must be False in production. "
                "Authentication is required for security."
            )

        # Rate limiting should be enabled
        if not self.rate_limit_enabled:
            errors.append(
                "RATE_LIMIT_ENABLED should be True in production. "
                "Disabling rate limits exposes the API to abuse."
            )

        if errors:
            raise ValueError(
                "Production configuration validation failed:\n- " + "\n- ".join(errors)
            )

        return self


settings = Settings()
