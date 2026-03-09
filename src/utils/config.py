"""Pydantic-based configuration management for Agentic Galactic Discovery.

This module provides centralized configuration using Pydantic models with
support for environment variables, .env files, and sensible defaults.

Example usage:
    from src.utils.config import get_settings

    settings = get_settings()
    print(settings.fink.base_url)
    print(settings.storage.bronze_path)
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging level."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class FinkSettings(BaseSettings):
    """Configuration for Fink API client.

    Attributes:
        base_url: Base URL for the Fink REST API.
        timeout_seconds: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed requests.
        retry_backoff_base: Base delay (seconds) for exponential backoff.
        rate_limit_requests: Maximum requests per rate limit window.
        rate_limit_window_seconds: Rate limit window duration in seconds.
        default_output_format: Default output format for API responses.
    """

    model_config = SettingsConfigDict(env_prefix="FINK_")

    base_url: str = "https://api.fink-portal.org"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_base: float = Field(default=2.0, ge=1.0, le=10.0)
    rate_limit_requests: int = Field(default=100, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    default_output_format: Literal["json", "csv", "parquet", "votable"] = "json"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base URL does not have trailing slash."""
        return v.rstrip("/")


class StorageSettings(BaseSettings):
    """Configuration for data storage paths and formats.

    Attributes:
        base_path: Root directory for all data storage.
        bronze_path: Path for bronze layer data (relative to base_path).
        silver_path: Path for silver layer data (relative to base_path).
        gold_path: Path for gold layer data (relative to base_path).
        checkpoint_path: Path for streaming checkpoints.
        file_format: Default file format for local storage.
        partition_columns: Default columns to partition by.
        enable_delta: Whether to use Delta Lake format (requires Databricks).
    """

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    base_path: Path = Field(default=Path("./data"))
    bronze_path: str = "bronze/alerts"
    silver_path: str = "silver/alerts"
    gold_path: str = "gold/alerts"
    checkpoint_path: str = "checkpoints"
    file_format: Literal["parquet", "delta", "json"] = "parquet"
    partition_columns: list[str] = Field(default_factory=lambda: ["observation_date"])
    enable_delta: bool = False

    @property
    def bronze_full_path(self) -> Path:
        """Get the full path to bronze layer storage."""
        return self.base_path / self.bronze_path

    @property
    def silver_full_path(self) -> Path:
        """Get the full path to silver layer storage."""
        return self.base_path / self.silver_path

    @property
    def gold_full_path(self) -> Path:
        """Get the full path to gold layer storage."""
        return self.base_path / self.gold_path

    @property
    def checkpoint_full_path(self) -> Path:
        """Get the full path to checkpoint storage."""
        return self.base_path / self.checkpoint_path


class ProcessingSettings(BaseSettings):
    """Configuration for data processing pipeline.

    Attributes:
        batch_size: Number of alerts to process in each batch.
        max_alerts_per_request: Maximum alerts to fetch in a single API request.
        enable_image_processing: Whether to process image cutouts.
        schema_validation_mode: How to handle schema validation failures.
        deduplication_window_hours: Time window for deduplication (in hours).
        min_detection_significance: Minimum SNR for valid detections.
    """

    model_config = SettingsConfigDict(env_prefix="PROCESSING_")

    batch_size: int = Field(default=1000, ge=1, le=100000)
    max_alerts_per_request: int = Field(default=100, ge=1, le=10000)
    enable_image_processing: bool = False
    schema_validation_mode: Literal["strict", "warn", "ignore"] = "strict"
    deduplication_window_hours: int = Field(default=24, ge=1)
    min_detection_significance: float = Field(default=5.0, ge=0.0)


class LoggingSettings(BaseSettings):
    """Configuration for structured logging.

    Attributes:
        level: Minimum log level to output.
        format: Log output format (json for production, console for development).
        include_timestamps: Whether to include timestamps in log output.
        log_file: Optional file path for log output.
    """

    model_config = SettingsConfigDict(env_prefix="LOG_")

    level: LogLevel = LogLevel.INFO
    format: Literal["json", "console"] = "console"
    include_timestamps: bool = True
    log_file: Path | None = None


class AnthropicSettings(BaseSettings):
    """Configuration for Claude API (Anthropic).

    Attributes:
        api_key: Anthropic API key (loaded from environment).
        model: Model to use for agent operations.
        max_tokens: Maximum tokens for model responses.
        temperature: Sampling temperature for model responses.
    """

    model_config = SettingsConfigDict(env_prefix="ANTHROPIC_")

    api_key: str | None = None
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = Field(default=4096, ge=1, le=100000)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


class Settings(BaseSettings):
    """Main application settings combining all configuration sections.

    This is the primary configuration class. Use get_settings() to obtain
    a cached instance.

    Attributes:
        environment: Current deployment environment.
        app_name: Application name for logging and identification.
        debug: Enable debug mode (more verbose logging, etc.).
        fink: Fink API configuration.
        storage: Data storage configuration.
        processing: Processing pipeline configuration.
        logging: Logging configuration.
        anthropic: Claude API configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGD_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "agentic-galactic-discovery"
    debug: bool = False

    fink: FinkSettings = Field(default_factory=FinkSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)

    @model_validator(mode="after")
    def adjust_settings_for_environment(self) -> "Settings":
        """Adjust settings based on environment."""
        if self.environment == Environment.DEVELOPMENT:
            # Enable debug mode in development by default
            if not self.debug:
                object.__setattr__(self, "debug", True)
            # Use console logging in development
            if self.logging.format != "console":
                self.logging.format = "console"
        elif self.environment == Environment.PRODUCTION:
            # Use JSON logging in production
            if self.logging.format != "json":
                self.logging.format = "json"
            # Ensure debug is off in production
            if self.debug:
                object.__setattr__(self, "debug", False)
        return self

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        directories = [
            self.storage.bronze_full_path,
            self.storage.silver_full_path,
            self.storage.gold_full_path,
            self.storage.checkpoint_full_path,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Returns:
        Singleton Settings instance loaded from environment and .env file.

    Example:
        settings = get_settings()
        print(settings.fink.base_url)
    """
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache to force reload.

    Useful for testing or when configuration needs to be reloaded.
    """
    get_settings.cache_clear()
