"""Bronze layer processor for astronomical alert data.

The bronze layer is the first stage in the medallion architecture:
- Receives raw alerts from ingestion (Fink API)
- Validates schema with configurable strictness
- Writes to Delta-compatible format (Parquet locally, Delta on Databricks)
- Preserves all original data for audit purposes
- Partitions by observation date for efficient queries

This processor is designed for the "hot path" and does not use LLM calls.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from src.exceptions import (
    BronzeProcessingError,
    SchemaValidationError,
    WriteError,
)
from src.models.alerts import AlertBatch, BronzeAlert, ZTFAlert
from src.utils.config import ProcessingSettings, Settings, StorageSettings, get_settings

logger = structlog.get_logger(__name__)


class BronzeProcessor:
    """Processes raw alerts into the bronze layer of the medallion architecture.

    The bronze layer stores data in its rawest usable form:
    - Schema validation to catch malformed data
    - Minimal transformation (just adding metadata)
    - Append-only writes for data integrity
    - Partitioning by observation date

    Args:
        settings: Application settings. If None, uses global settings.
        storage_settings: Override storage settings for testing.
        processing_settings: Override processing settings for testing.

    Example:
        processor = BronzeProcessor()
        batch = processor.process_alerts(raw_alerts)
        processor.write_batch(batch)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        storage_settings: StorageSettings | None = None,
        processing_settings: ProcessingSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage_settings or self._settings.storage
        self._processing = processing_settings or self._settings.processing
        self._log = logger.bind(component="bronze_processor")

    @property
    def output_path(self) -> Path:
        """Get the configured bronze layer output path."""
        return self._storage.bronze_full_path

    def process_alerts(
        self,
        raw_alerts: list[dict[str, Any]],
        source: str = "fink_api",
        source_version: str | None = None,
        batch_id: str | None = None,
    ) -> AlertBatch:
        """Process a list of raw alert dictionaries into a validated batch.

        Args:
            raw_alerts: List of raw alert dictionaries from the API.
            source: Identifier for the data source.
            source_version: Version of the source API/schema.
            batch_id: Optional batch ID. Generated if not provided.

        Returns:
            AlertBatch containing validated BronzeAlert objects.

        Raises:
            BronzeProcessingError: If processing fails and validation is strict.
        """
        batch_id = batch_id or self._generate_batch_id()
        self._log.info(
            "processing_alerts_started",
            batch_id=batch_id,
            alert_count=len(raw_alerts),
            source=source,
        )

        bronze_alerts: list[BronzeAlert] = []
        validation_errors: list[dict[str, Any]] = []

        for idx, raw_alert in enumerate(raw_alerts):
            try:
                bronze_alert = self._process_single_alert(
                    raw_alert=raw_alert,
                    source=source,
                    source_version=source_version,
                    processing_id=batch_id,
                )
                bronze_alerts.append(bronze_alert)
            except SchemaValidationError as e:
                validation_errors.append(
                    {
                        "index": idx,
                        "error": str(e),
                        "alert_id": raw_alert.get("objectId", "unknown"),
                    }
                )
                self._handle_validation_error(e, raw_alert, idx)

        self._log.info(
            "processing_alerts_completed",
            batch_id=batch_id,
            successful=len(bronze_alerts),
            failed=len(validation_errors),
        )

        if validation_errors and self._processing.schema_validation_mode == "strict":
            if len(bronze_alerts) == 0:
                raise BronzeProcessingError(
                    "All alerts failed validation",
                    details={"errors": validation_errors[:10]},  # Limit error details
                )

        return AlertBatch(
            alerts=bronze_alerts,
            batch_id=batch_id,
            source_query={"source": source, "count": len(raw_alerts)},
        )

    def _process_single_alert(
        self,
        raw_alert: dict[str, Any],
        source: str,
        source_version: str | None,
        processing_id: str,
    ) -> BronzeAlert:
        """Process a single raw alert into a BronzeAlert.

        Args:
            raw_alert: Raw alert dictionary.
            source: Data source identifier.
            source_version: Source API version.
            processing_id: Batch processing ID.

        Returns:
            Validated BronzeAlert.

        Raises:
            SchemaValidationError: If the alert fails validation.
        """
        try:
            # Parse the core ZTF alert structure
            ztf_alert = ZTFAlert(**raw_alert)

            # Wrap in bronze layer with metadata
            bronze_alert = BronzeAlert(
                alert=ztf_alert,
                source=source,
                source_version=source_version,
                raw_payload=raw_alert,
                processing_id=processing_id,
            )

            return bronze_alert

        except Exception as e:
            raise SchemaValidationError(
                f"Failed to validate alert: {e}",
                alert_id=raw_alert.get("objectId"),
                details={"raw_error": str(e)},
            ) from e

    def _handle_validation_error(
        self,
        error: SchemaValidationError,
        raw_alert: dict[str, Any],
        index: int,
    ) -> None:
        """Handle a validation error according to the configured mode.

        Args:
            error: The validation error.
            raw_alert: The raw alert that failed validation.
            index: Index of the alert in the batch.
        """
        mode = self._processing.schema_validation_mode

        if mode == "strict":
            self._log.error(
                "validation_error_strict",
                index=index,
                alert_id=raw_alert.get("objectId"),
                error=str(error),
            )
        elif mode == "warn":
            self._log.warning(
                "validation_error_warn",
                index=index,
                alert_id=raw_alert.get("objectId"),
                error=str(error),
            )
        # mode == "ignore": silently skip

    def write_batch(
        self,
        batch: AlertBatch,
        partition_by_date: bool = True,
    ) -> Path:
        """Write an alert batch to the bronze layer storage.

        Args:
            batch: AlertBatch to write.
            partition_by_date: Whether to partition by observation date.

        Returns:
            Path to the written data.

        Raises:
            WriteError: If writing fails.
        """
        if batch.count == 0:
            self._log.warning("write_batch_empty", batch_id=batch.batch_id)
            return self.output_path

        self._log.info(
            "write_batch_started",
            batch_id=batch.batch_id,
            alert_count=batch.count,
            output_path=str(self.output_path),
        )

        try:
            # Ensure output directory exists
            self.output_path.mkdir(parents=True, exist_ok=True)

            # Convert to DataFrame for Parquet writing
            records = [alert.to_flat_dict() for alert in batch.alerts]
            df = pd.DataFrame(records)

            # Write based on storage format
            if self._storage.file_format == "parquet":
                output_file = self._write_parquet(df, batch.batch_id, partition_by_date)
            elif self._storage.file_format == "json":
                output_file = self._write_json(df, batch.batch_id)
            else:
                # Default to parquet for delta (will be actual Delta on Databricks)
                output_file = self._write_parquet(df, batch.batch_id, partition_by_date)

            self._log.info(
                "write_batch_completed",
                batch_id=batch.batch_id,
                output_file=str(output_file),
                records_written=len(records),
            )

            return output_file

        except Exception as e:
            raise WriteError(
                f"Failed to write batch {batch.batch_id}: {e}",
                details={"batch_id": batch.batch_id, "error": str(e)},
            ) from e

    def _write_parquet(
        self,
        df: pd.DataFrame,
        batch_id: str,
        partition_by_date: bool,
    ) -> Path:
        """Write DataFrame to Parquet format.

        Args:
            df: DataFrame to write.
            batch_id: Batch identifier for filename.
            partition_by_date: Whether to partition by observation_date.

        Returns:
            Path to written file or directory.
        """
        if partition_by_date and "observation_date" in df.columns:
            # Write partitioned dataset
            table = pa.Table.from_pandas(df)
            pq.write_to_dataset(
                table,
                root_path=str(self.output_path),
                partition_cols=["observation_date"],
                existing_data_behavior="overwrite_or_ignore",
            )
            return self.output_path
        else:
            # Write single file
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"alerts_{batch_id}_{timestamp}.parquet"
            output_file = self.output_path / filename
            df.to_parquet(output_file, index=False, engine="pyarrow")
            return output_file

    def _write_json(self, df: pd.DataFrame, batch_id: str) -> Path:
        """Write DataFrame to JSON format (for debugging/development).

        Args:
            df: DataFrame to write.
            batch_id: Batch identifier for filename.

        Returns:
            Path to written file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"alerts_{batch_id}_{timestamp}.json"
        output_file = self.output_path / filename
        df.to_json(output_file, orient="records", indent=2)
        return output_file

    def _generate_batch_id(self) -> str:
        """Generate a unique batch ID."""
        return f"bronze_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def read_bronze_data(
        self,
        observation_date: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Read bronze layer data back from storage.

        Args:
            observation_date: Filter by specific date (YYYY-MM-DD).
            limit: Maximum number of records to return.

        Returns:
            DataFrame containing bronze alert data.
        """
        if not self.output_path.exists():
            self._log.warning("bronze_path_not_found", path=str(self.output_path))
            return pd.DataFrame()

        try:
            if self._storage.file_format == "parquet":
                # Read partitioned or non-partitioned parquet
                filters = None
                if observation_date:
                    filters = [("observation_date", "=", observation_date)]

                df = pd.read_parquet(
                    self.output_path,
                    filters=filters,
                    engine="pyarrow",
                )
            else:
                # Read JSON files
                json_files = list(self.output_path.glob("*.json"))
                if not json_files:
                    return pd.DataFrame()
                dfs = [pd.read_json(f) for f in json_files]
                df = pd.concat(dfs, ignore_index=True)

                if observation_date and "observation_date" in df.columns:
                    df = df[df["observation_date"] == observation_date]

            if limit:
                df = df.head(limit)

            return df

        except Exception as e:
            self._log.error("read_bronze_error", error=str(e))
            return pd.DataFrame()

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about the bronze layer data.

        Returns:
            Dictionary with statistics including record counts, date ranges, etc.
        """
        df = self.read_bronze_data()

        if df.empty:
            return {
                "total_records": 0,
                "unique_objects": 0,
                "date_range": None,
                "classifications": {},
            }

        stats = {
            "total_records": len(df),
            "unique_objects": df["object_id"].nunique() if "object_id" in df.columns else 0,
        }

        if "observation_date" in df.columns:
            stats["date_range"] = {
                "min": df["observation_date"].min(),
                "max": df["observation_date"].max(),
            }

        if "fink_class" in df.columns:
            stats["classifications"] = df["fink_class"].value_counts().to_dict()

        return stats


def create_bronze_processor(
    settings: Settings | None = None,
) -> BronzeProcessor:
    """Factory function to create a configured BronzeProcessor.

    Args:
        settings: Optional settings override.

    Returns:
        Configured BronzeProcessor instance.
    """
    return BronzeProcessor(settings=settings)
