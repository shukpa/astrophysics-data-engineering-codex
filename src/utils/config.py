"""Pydantic-based configuration management for Agentic Galactic Discovery.

This module provides centralized configuration using Pydantic models with
support for environment variables, .env files, and sensible defaults.

Example usage:
    from src.utils.config import get_settings

    settings = get_settings()
    print(settings.fink.base_url)
    print(settings.storage.bronze_path)
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
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
        default_output_format: API response format supported by the client.
    """

    model_config = SettingsConfigDict(env_prefix="FINK_")

    base_url: str = "https://api.ztf.fink-portal.org"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_base: float = Field(default=2.0, ge=1.0, le=10.0)
    default_output_format: Literal["json"] = "json"

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
        file_format: Local storage format. Delta is explicitly unsupported.
        enable_delta: Reserved compatibility flag; enabling it is rejected.
    """

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    base_path: Path = Field(default=Path("./data"))
    bronze_path: str = "bronze/alerts"
    silver_path: str = "silver/alerts"
    gold_path: str = "gold/alerts"
    euclid_bronze_path: str = "bronze/euclid"
    euclid_silver_path: str = "silver/euclid"
    checkpoint_path: str = "checkpoints"
    file_format: Literal["parquet", "delta", "json"] = "parquet"
    enable_delta: bool = False

    @model_validator(mode="after")
    def reject_unsupported_delta(self) -> "StorageSettings":
        """Reject Delta configuration until a real Delta writer is implemented."""
        if self.file_format == "delta" or self.enable_delta:
            raise ValueError(
                "Delta storage is not implemented by the local processors; "
                "use file_format='parquet' and enable_delta=False."
            )
        return self

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
    def euclid_bronze_full_path(self) -> Path:
        """Get the full path to Euclid bronze layer storage."""
        return self.base_path / self.euclid_bronze_path

    @property
    def euclid_silver_full_path(self) -> Path:
        """Get the full path to Euclid silver layer storage."""
        return self.base_path / self.euclid_silver_path

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
    """

    model_config = SettingsConfigDict(env_prefix="PROCESSING_")

    batch_size: int = Field(default=1000, ge=1, le=100000)
    max_alerts_per_request: int = Field(default=100, ge=1, le=10000)
    enable_image_processing: bool = False
    schema_validation_mode: Literal["strict", "warn", "ignore"] = "strict"


class CrossmatchSettings(BaseSettings):
    """Configuration for catalog cross-matching (gold layer).

    Attributes:
        radius_arcsec: Cone-search radius for catalog cross-matches (arcsec).
        gaia_catalog: Fully qualified Gaia TAP table to query.
        gaia_timeout_seconds: Timeout for Gaia TAP queries.
        gaia_max_rows: Maximum rows to request per Gaia cone search.
        simbad_timeout_seconds: Timeout for SIMBAD queries.
        max_retries: Maximum retry attempts for catalog queries.
        cache_enabled: Whether to cache catalog query results locally.
        cache_path: Directory for the local Parquet query cache
            (relative to StorageSettings.base_path).
        parallax_snr_threshold: Minimum parallax/parallax_error for a
            significant (stellar) parallax detection.
        pm_snr_threshold: Minimum total-proper-motion SNR for a significant
            (stellar) proper-motion detection.
        tap_proxy_url: Optional CONNECT-proxy URL for Gaia TAP queries. When
            set, the Gaia client tunnels astroquery's TAP connections through
            it (astroquery ignores HTTPS_PROXY). Leave unset for direct
            network access. SIMBAD does not need this (it uses requests).
        tap_ca_bundle: Optional CA bundle to trust when tap_proxy_url is set
            and the proxy re-terminates TLS with its own certificate.
    """

    model_config = SettingsConfigDict(env_prefix="CROSSMATCH_")

    radius_arcsec: float = Field(default=5.0, gt=0, le=3600)
    gaia_catalog: str = "gaiadr3.gaia_source"
    gaia_timeout_seconds: int = Field(default=60, ge=1, le=600)
    gaia_max_rows: int = Field(default=50, ge=1, le=10000)
    simbad_timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    cache_enabled: bool = True
    cache_path: str = "cache/crossref"
    parallax_snr_threshold: float = Field(default=5.0, ge=0.0)
    pm_snr_threshold: float = Field(default=5.0, ge=0.0)
    tap_proxy_url: str | None = None
    tap_ca_bundle: str | None = None


class EuclidSettings(BaseSettings):
    """Configuration for Euclid open-data ingestion (batch TAP catalogues).

    Attributes:
        mer_table: Fully qualified MER final catalogue table on the ESA TAP
            service (verified live against tap_schema on 2026-07-12).
        timeout_seconds: Timeout for Euclid TAP queries.
        max_rows: Maximum rows to request per MER cone search.
        cache_path: Directory for the local Parquet query cache
            (relative to StorageSettings.base_path).
        dr_tag: Data-release tag stamped into provenance for every ingested
            row ("Q1" now; switch to "DR1F" at the DR1-Foundation swap-in).
        lens_allowed_grades: SLDE candidate grades kept by the silver layer.
        lens_match_radius_arcsec: Radius for the gold-layer lens-field
            cross-match (transient within this distance of a lens candidate
            is flagged ``lens_field_transient``). Default is generous vs.
            typical Einstein radii (~1-3") to catch offset lensed images.
        tap_proxy_url: Optional CONNECT-proxy URL for Euclid TAP queries
            (astroquery's TAP layer ignores HTTPS_PROXY; see tap_proxy.py).
        tap_ca_bundle: Optional CA bundle when the proxy re-terminates TLS.
    """

    model_config = SettingsConfigDict(env_prefix="EUCLID_")

    mer_table: str = "catalogue.mer_catalogue"
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    max_rows: int = Field(default=500, ge=1, le=100000)
    cache_path: str = "cache/euclid"
    dr_tag: str = "Q1"
    lens_allowed_grades: list[str] = Field(default_factory=lambda: ["A", "B"])
    lens_match_radius_arcsec: float = Field(default=10.0, gt=0, le=3600)
    tap_proxy_url: str | None = None
    tap_ca_bundle: str | None = None


class ClassificationSettings(BaseSettings):
    """Configuration for the Tier-1 classification-confidence framework.

    The hot-path baseline classifier (``src/processing/classifier.py``) is
    deterministic and LLM-free (architecture rule 1). Fink's broker classes
    are the v0 baseline; an own light-curve-feature model is the upgrade path.

    Attributes:
        anomaly_score_threshold: Anomaly score at/above which an event is
            handed to the warm-path anomaly agent.
        high_priority_classes: Fink classes that are scientifically valuable
            known types (follow-up priority HIGH).
        low_priority_classes: Well-characterised known types (priority LOW,
            archive only).
    """

    model_config = SettingsConfigDict(env_prefix="CLASSIFICATION_")

    anomaly_score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    high_priority_classes: list[str] = Field(
        default_factory=lambda: [
            "Kilonova candidate",
            "Early SN Ia candidate",
            "Microlensing candidate",
        ]
    )
    low_priority_classes: list[str] = Field(
        default_factory=lambda: [
            "Variable Star",
            "YSO",
            "Solar System MPC",
            "Solar System candidate",
        ]
    )


class AnomalySettings(BaseSettings):
    """Configuration for the warm-path anomaly agent.

    Attributes:
        outlier_sigma_threshold: Deviation (in sigma vs the class baseline)
            at/above which an event counts as a statistical outlier.
        minimum_detections_for_analysis: Light-curve detections required
            before deviations are considered meaningful (single-epoch
            "anomalies" are overwhelmingly artifacts).
        max_false_alarm_probability: Trials-corrected false-alarm probability
            an assessment must beat before a non-CRITICAL event escalates.
    """

    model_config = SettingsConfigDict(env_prefix="ANOMALY_")

    outlier_sigma_threshold: float = Field(default=3.0, ge=0.0)
    minimum_detections_for_analysis: int = Field(default=5, ge=1)
    max_false_alarm_probability: float = Field(default=0.01, gt=0.0, le=1.0)


class ReportSettings(BaseSettings):
    """Configuration for the nightly report CLI.

    Attributes:
        include_top_n_events: How many top anomalies to include.
        minimum_priority: Lowest follow-up priority included in the
            notification-worthy section of the report.
        output_path: Directory for generated reports
            (relative to StorageSettings.base_path).
    """

    model_config = SettingsConfigDict(env_prefix="REPORT_")

    include_top_n_events: int = Field(default=20, ge=1, le=1000)
    minimum_priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    output_path: str = "reports"


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
        crossmatch: Catalog cross-match configuration (gold layer).
        euclid: Euclid open-data ingestion configuration.
        classification: Tier-1 classification framework configuration.
        anomaly: Warm-path anomaly agent configuration.
        report: Nightly report configuration.
        logging: Logging configuration.
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
    crossmatch: CrossmatchSettings = Field(default_factory=CrossmatchSettings)
    euclid: EuclidSettings = Field(default_factory=EuclidSettings)
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    anomaly: AnomalySettings = Field(default_factory=AnomalySettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

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
