"""Central Configuration Management Module for Basalt Workflow Engine.

Provides type-safe, environment-aware configuration objects using Pydantic Settings v2.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, Enum):
    """Supported logging severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Environment(str, Enum):
    """Runtime environment profiles."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseSettings(BaseModel):
    """Configuration settings for SQLite database persistence."""

    url: str = Field(
        default="sqlite+aiosqlite:///./basalt.db",
        description="SQLAlchemy async database connection URL.",
    )
    echo: bool = Field(
        default=False,
        description="Enable verbose SQL query logging.",
    )
    pool_size: int = Field(
        default=10,
        ge=1,
        description="Database connection pool size.",
    )
    max_overflow: int = Field(
        default=20,
        ge=0,
        description="Maximum connection pool overflow limit.",
    )
    pool_timeout: float = Field(
        default=30.0,
        gt=0.0,
        description="Timeout in seconds for acquiring connection from pool.",
    )
    connection_timeout: float = Field(
        default=10.0,
        gt=0.0,
        description="SQLite connection timeout in seconds.",
    )
    wal_mode: bool = Field(
        default=True,
        description="Enable Write-Ahead Logging (WAL) mode for SQLite.",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure database URL specifies an async SQLite driver."""
        if not v.startswith("sqlite+aiosqlite://"):
            raise ValueError(
                "Database URL must start with 'sqlite+aiosqlite://' for async support."
            )
        return v


class EngineSettings(BaseModel):
    """Configuration settings for core workflow execution engine."""

    max_concurrent_workers: int = Field(
        default=16,
        ge=1,
        le=128,
        description="Maximum concurrent task workers in pool.",
    )
    default_step_timeout_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Default timeout in seconds for individual step execution.",
    )
    default_dag_timeout_seconds: float = Field(
        default=3600.0,
        gt=0.0,
        description="Default timeout in seconds for total DAG workflow execution.",
    )
    enable_context_interpolation: bool = Field(
        default=True,
        description="Enable expression template interpolation (${steps.id.output}).",
    )
    context_template_pattern: str = Field(
        default=r"\$\{([^\}]+)\}",
        description="Regular expression pattern for matching template variables.",
    )
    cleanup_completed_runs_days: int = Field(
        default=30,
        ge=0,
        description="Days after which completed workflow runs are pruned.",
    )


class ResilienceSettings(BaseModel):
    """Configuration settings for retries, backoff, and circuit breakers."""

    default_max_retries: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Default maximum retry attempts for failed steps.",
    )
    default_initial_backoff_seconds: float = Field(
        default=1.0,
        gt=0.0,
        description="Default initial backoff delay in seconds.",
    )
    default_max_backoff_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Default maximum backoff delay cap in seconds.",
    )
    default_backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        description="Exponential growth factor for backoff delay calculation.",
    )
    enable_jitter: bool = Field(
        default=True,
        description="Add randomized jitter to backoff delay intervals.",
    )
    circuit_breaker_failure_threshold: int = Field(
        default=5,
        ge=1,
        description="Consequent failure count before opening circuit breaker.",
    )
    circuit_breaker_recovery_time_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Time in seconds to remain in OPEN state before testing recovery.",
    )
    dlq_max_size: int = Field(
        default=1000,
        ge=10,
        description="Maximum entries stored in Dead-Letter Queue before rotation.",
    )


class APISettings(BaseModel):
    """Configuration settings for FastAPI REST application."""

    host: str = Field(
        default="0.0.0.0",
        description="Interface host IP address to bind REST API server.",
    )
    port: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description="TCP port number to bind REST API server.",
    )
    debug: bool = Field(
        default=False,
        description="Enable FastAPI debug mode.",
    )
    title: str = Field(
        default="Basalt Workflow Engine API",
        description="OpenAPI specification title.",
    )
    version: str = Field(
        default="0.1.0",
        description="API semantic version string.",
    )
    docs_url: str | None = Field(
        default="/docs",
        description="URL path for Swagger interactive documentation.",
    )
    redoc_url: str | None = Field(
        default="/redoc",
        description="URL path for ReDoc documentation.",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origin URLs.",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials in CORS preflight requests.",
    )
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed HTTP methods for CORS.",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed HTTP headers for CORS.",
    )
    api_key_header_name: str = Field(
        default="X-Basalt-API-Key",
        description="HTTP header name used for API key authentication.",
    )
    secret_key: SecretStr = Field(
        default=SecretStr("strata-secret-key-change-in-production"),
        description="Secret key used for HMAC signature validation.",
    )


class TriggerSettings(BaseModel):
    """Configuration settings for event triggers and schedulers."""

    enable_cron_scheduler: bool = Field(
        default=True,
        description="Enable background Cron schedule evaluator.",
    )
    enable_interval_scheduler: bool = Field(
        default=True,
        description="Enable background interval timer evaluator.",
    )
    enable_webhooks: bool = Field(
        default=True,
        description="Enable HTTP Webhook trigger endpoint ingestion.",
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        gt=0.0,
        description="Frequency in seconds for evaluating trigger rules.",
    )
    webhook_secret_header: str = Field(
        default="X-Basalt-Signature",
        description="HTTP header containing webhook HMAC signature.",
    )


class Settings(BaseSettings):
    """Root Application Settings object loading from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="BASALT_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Active runtime environment profile.",
    )
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Application logging verbosity level.",
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    api: APISettings = Field(default_factory=APISettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)

    def is_production(self) -> bool:
        """Check if application is running in production profile."""
        return self.environment == Environment.PRODUCTION

    def is_testing(self) -> bool:
        """Check if application is running in testing profile."""
        return self.environment == Environment.TESTING

    def get_sqlite_path(self) -> Path | None:
        """Extract filesystem Path from SQLite database URL if local file."""
        if "///" in self.db.url:
            path_str = self.db.url.split("///")[-1]
            if path_str != ":memory:":
                return Path(path_str).resolve()
        return None

    def to_dict(self) -> dict[str, Any]:
        """Dump settings dictionary omitting sensitive SecretStr fields."""
        data = self.model_dump()
        if "api" in data and "secret_key" in data["api"]:
            data["api"]["secret_key"] = "***REDACTED***"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve global cached Settings singleton instance."""
    return Settings()


def set_settings(settings: Settings) -> None:
    """Override cached settings instance (useful for unit tests)."""
    get_settings.cache_clear()
    global _override_settings
    _override_settings = settings


_override_settings: Settings | None = None
