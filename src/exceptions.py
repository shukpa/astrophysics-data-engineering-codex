"""Custom exception hierarchy for Agentic Galactic Discovery.

All custom exceptions inherit from AGDError to enable catching any
project-specific exception while preserving the ability to catch
specific error types.
"""

from typing import Any


class AGDError(Exception):
    """Base exception for all Agentic Galactic Discovery errors.

    Args:
        message: Human-readable error description.
        details: Optional dictionary with additional context about the error.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


# Configuration Errors
class ConfigurationError(AGDError):
    """Error in configuration loading or validation."""

    pass


class MissingConfigError(ConfigurationError):
    """Required configuration value is missing."""

    pass


# Ingestion Errors
class IngestionError(AGDError):
    """Error during data ingestion from external sources."""

    pass


class FinkAPIError(IngestionError):
    """Error communicating with the Fink API."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if status_code is not None:
            details["status_code"] = status_code
        if endpoint is not None:
            details["endpoint"] = endpoint
        super().__init__(message, details)
        self.status_code = status_code
        self.endpoint = endpoint


class RateLimitError(FinkAPIError):
    """Rate limit exceeded when calling external API."""

    pass


# Processing Errors
class ProcessingError(AGDError):
    """Error during data processing in the pipeline."""

    pass


class SchemaValidationError(ProcessingError):
    """Alert data does not conform to expected schema."""

    def __init__(
        self,
        message: str,
        alert_id: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if alert_id is not None:
            details["alert_id"] = alert_id
        if field is not None:
            details["field"] = field
        super().__init__(message, details)
        self.alert_id = alert_id
        self.field = field


class BronzeProcessingError(ProcessingError):
    """Error during bronze layer processing."""

    pass


class SilverProcessingError(ProcessingError):
    """Error during silver layer processing."""

    pass


class GoldProcessingError(ProcessingError):
    """Error during gold layer processing."""

    pass


# Storage Errors
class StorageError(AGDError):
    """Error during data storage operations."""

    pass


class WriteError(StorageError):
    """Error writing data to storage."""

    pass


class ReadError(StorageError):
    """Error reading data from storage."""

    pass


# Cross-Reference Errors
class CrossReferenceError(AGDError):
    """Error during cross-referencing with external catalogs."""

    pass


class SIMBADError(CrossReferenceError):
    """Error querying SIMBAD database."""

    pass


class GaiaError(CrossReferenceError):
    """Error querying Gaia catalog."""

    pass


# Agent Errors
class AgentError(AGDError):
    """Error in AI agent operations."""

    pass


class ClassificationError(AgentError):
    """Error during alert classification."""

    pass


class AnomalyDetectionError(AgentError):
    """Error during anomaly detection."""

    pass
