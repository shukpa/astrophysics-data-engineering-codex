"""Tests for the configuration module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.config import (
    AnthropicSettings,
    Environment,
    FinkSettings,
    LoggingSettings,
    LogLevel,
    ProcessingSettings,
    Settings,
    StorageSettings,
    clear_settings_cache,
    get_settings,
)


class TestFinkSettings:
    """Tests for FinkSettings configuration."""

    def test_default_values(self) -> None:
        """Test that FinkSettings has correct defaults."""
        settings = FinkSettings()

        assert settings.base_url == "https://api.fink-portal.org"
        assert settings.timeout_seconds == 30
        assert settings.max_retries == 3
        assert settings.retry_backoff_base == 2.0
        assert settings.rate_limit_requests == 100
        assert settings.rate_limit_window_seconds == 60
        assert settings.default_output_format == "json"

    def test_base_url_trailing_slash_removed(self) -> None:
        """Test that trailing slashes are removed from base_url."""
        settings = FinkSettings(base_url="https://api.fink-portal.org/")
        assert settings.base_url == "https://api.fink-portal.org"

    def test_timeout_validation(self) -> None:
        """Test timeout validation bounds."""
        # Valid timeout
        settings = FinkSettings(timeout_seconds=60)
        assert settings.timeout_seconds == 60

        # Invalid timeout (too low)
        with pytest.raises(ValueError):
            FinkSettings(timeout_seconds=0)

        # Invalid timeout (too high)
        with pytest.raises(ValueError):
            FinkSettings(timeout_seconds=500)

    def test_max_retries_validation(self) -> None:
        """Test max_retries validation bounds."""
        settings = FinkSettings(max_retries=5)
        assert settings.max_retries == 5

        with pytest.raises(ValueError):
            FinkSettings(max_retries=-1)

        with pytest.raises(ValueError):
            FinkSettings(max_retries=15)


class TestStorageSettings:
    """Tests for StorageSettings configuration."""

    def test_default_values(self) -> None:
        """Test that StorageSettings has correct defaults."""
        settings = StorageSettings()

        assert settings.base_path == Path("./data")
        assert settings.bronze_path == "bronze/alerts"
        assert settings.silver_path == "silver/alerts"
        assert settings.gold_path == "gold/alerts"
        assert settings.file_format == "parquet"
        assert settings.enable_delta is False

    def test_full_path_properties(self) -> None:
        """Test that full path properties combine correctly."""
        settings = StorageSettings(base_path=Path("/data/lake"))

        assert settings.bronze_full_path == Path("/data/lake/bronze/alerts")
        assert settings.silver_full_path == Path("/data/lake/silver/alerts")
        assert settings.gold_full_path == Path("/data/lake/gold/alerts")
        assert settings.checkpoint_full_path == Path("/data/lake/checkpoints")

    def test_partition_columns_default(self) -> None:
        """Test default partition columns."""
        settings = StorageSettings()
        assert settings.partition_columns == ["observation_date"]


class TestProcessingSettings:
    """Tests for ProcessingSettings configuration."""

    def test_default_values(self) -> None:
        """Test that ProcessingSettings has correct defaults."""
        settings = ProcessingSettings()

        assert settings.batch_size == 1000
        assert settings.max_alerts_per_request == 100
        assert settings.enable_image_processing is False
        assert settings.schema_validation_mode == "strict"
        assert settings.deduplication_window_hours == 24
        assert settings.min_detection_significance == 5.0

    def test_batch_size_validation(self) -> None:
        """Test batch_size validation."""
        settings = ProcessingSettings(batch_size=5000)
        assert settings.batch_size == 5000

        with pytest.raises(ValueError):
            ProcessingSettings(batch_size=0)

    def test_validation_modes(self) -> None:
        """Test valid schema validation modes."""
        for mode in ["strict", "warn", "ignore"]:
            settings = ProcessingSettings(schema_validation_mode=mode)
            assert settings.schema_validation_mode == mode


class TestLoggingSettings:
    """Tests for LoggingSettings configuration."""

    def test_default_values(self) -> None:
        """Test that LoggingSettings has correct defaults."""
        settings = LoggingSettings()

        assert settings.level == LogLevel.INFO
        assert settings.format == "console"
        assert settings.include_timestamps is True
        assert settings.log_file is None

    def test_log_levels(self) -> None:
        """Test all log levels are valid."""
        for level in LogLevel:
            settings = LoggingSettings(level=level)
            assert settings.level == level


class TestAnthropicSettings:
    """Tests for AnthropicSettings configuration."""

    def test_default_values(self) -> None:
        """Test that AnthropicSettings has correct defaults."""
        settings = AnthropicSettings()

        assert settings.api_key is None
        assert settings.model == "claude-sonnet-4-20250514"
        assert settings.max_tokens == 4096
        assert settings.temperature == 0.0

    def test_temperature_validation(self) -> None:
        """Test temperature validation bounds."""
        settings = AnthropicSettings(temperature=0.5)
        assert settings.temperature == 0.5

        with pytest.raises(ValueError):
            AnthropicSettings(temperature=-0.1)

        with pytest.raises(ValueError):
            AnthropicSettings(temperature=1.5)


class TestSettings:
    """Tests for main Settings class."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def test_default_values(self) -> None:
        """Test that Settings has correct defaults."""
        settings = Settings()

        assert settings.environment == Environment.DEVELOPMENT
        assert settings.app_name == "agentic-galactic-discovery"
        assert settings.debug is True  # Auto-enabled in development

    def test_nested_settings(self) -> None:
        """Test that nested settings are accessible."""
        settings = Settings()

        assert settings.fink.base_url == "https://api.fink-portal.org"
        assert settings.storage.bronze_path == "bronze/alerts"
        assert settings.processing.batch_size == 1000
        assert settings.logging.level == LogLevel.INFO

    def test_environment_adjustment_development(self) -> None:
        """Test settings adjustment for development environment."""
        settings = Settings(environment=Environment.DEVELOPMENT)

        assert settings.debug is True
        assert settings.logging.format == "console"

    def test_environment_adjustment_production(self) -> None:
        """Test settings adjustment for production environment."""
        settings = Settings(environment=Environment.PRODUCTION)

        assert settings.debug is False
        assert settings.logging.format == "json"

    def test_ensure_directories(self, tmp_path: Path) -> None:
        """Test that ensure_directories creates all required paths."""
        storage = StorageSettings(base_path=tmp_path)
        settings = Settings(storage=storage)

        settings.ensure_directories()

        assert (tmp_path / "bronze/alerts").exists()
        assert (tmp_path / "silver/alerts").exists()
        assert (tmp_path / "gold/alerts").exists()
        assert (tmp_path / "checkpoints").exists()


class TestGetSettings:
    """Tests for the get_settings function."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caching(self) -> None:
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_clear_cache(self) -> None:
        """Test that clear_settings_cache forces reload."""
        settings1 = get_settings()
        clear_settings_cache()
        settings2 = get_settings()
        # New instance should be created (though equal)
        assert settings1 is not settings2

    def test_environment_variable_override(self) -> None:
        """Test that environment variables override defaults."""
        clear_settings_cache()

        with patch.dict(os.environ, {"AGD_ENVIRONMENT": "production"}):
            clear_settings_cache()
            settings = Settings()
            assert settings.environment == Environment.PRODUCTION
