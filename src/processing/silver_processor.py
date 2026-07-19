"""Silver layer processor for validated astronomical alert records.

The silver layer turns bronze alerts into cleaned, deduplicated records that are
ready for catalog enrichment and downstream anomaly scoring. It stays in the hot
path and does not use LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from src.crossref.utils import none_if_nan
from src.exceptions import SilverProcessingError, WriteError
from src.models.alerts import AlertBatch, BronzeAlert, SilverAlert, SilverBatch
from src.utils.config import ProcessingSettings, Settings, StorageSettings, get_settings

logger = structlog.get_logger(__name__)


class SilverProcessor:
    """Processes bronze alerts into the silver layer.

    Silver processing applies data-quality filters, canonicalizes the flattened
    storage shape, deduplicates repeated alerts, and keeps provenance back to
    the bronze/source records.
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
        self._log = logger.bind(component="silver_processor")

    @property
    def output_path(self) -> Path:
        """Get the configured silver layer output path."""
        return self._storage.silver_full_path

    def process_batch(
        self,
        batch: AlertBatch,
        batch_id: str | None = None,
    ) -> SilverBatch:
        """Process a bronze alert batch into a silver alert batch."""
        batch_id = batch_id or self._generate_batch_id()
        self._log.info(
            "silver_processing_started",
            batch_id=batch_id,
            source_batch_id=batch.batch_id,
            alert_count=batch.count,
        )

        silver_alerts: list[SilverAlert] = []
        rejected_count = 0

        for bronze_alert in batch.alerts:
            is_valid, reasons = self._quality_check(bronze_alert)
            if not is_valid:
                rejected_count += 1
                self._log.warning(
                    "silver_alert_rejected",
                    object_id=bronze_alert.object_id,
                    candidate_id=bronze_alert.candidate_id,
                    reasons=reasons,
                )
                continue

            try:
                silver_alerts.append(
                    self._to_silver_alert(
                        bronze_alert=bronze_alert,
                        silver_processing_id=batch_id,
                    )
                )
            except Exception as exc:
                rejected_count += 1
                self._log.warning(
                    "silver_alert_conversion_failed",
                    object_id=bronze_alert.object_id,
                    candidate_id=bronze_alert.candidate_id,
                    error=str(exc),
                )

        deduped_alerts = self._deduplicate(silver_alerts)
        duplicate_count = len(silver_alerts) - len(deduped_alerts)

        self._log.info(
            "silver_processing_completed",
            batch_id=batch_id,
            successful=len(deduped_alerts),
            rejected=rejected_count,
            duplicates=duplicate_count,
        )

        return SilverBatch(
            alerts=deduped_alerts,
            batch_id=batch_id,
            source_batch_id=batch.batch_id,
            source_count=batch.count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
        )

    def write_batch(
        self,
        batch: SilverBatch,
        partition_by_date: bool = True,
        idempotent: bool = True,
    ) -> Path:
        """Write a silver batch to storage, merging replayed candidates by default."""
        if batch.count == 0:
            self._log.warning("write_silver_batch_empty", batch_id=batch.batch_id)
            return self.output_path

        try:
            self.output_path.mkdir(parents=True, exist_ok=True)
            alerts = list(batch.alerts)
            existing_alerts: list[SilverAlert] = []
            suffix = "*.json" if self._storage.file_format == "json" else "*.parquet"
            if idempotent and any(self.output_path.rglob(suffix)):
                existing_alerts = self._read_existing_alerts(alerts)
                alerts = self._deduplicate(existing_alerts + alerts)
            df = pd.DataFrame([alert.to_flat_dict() for alert in alerts])
            df["candidate_id"] = pd.array([alert.candidate_id for alert in alerts], dtype="Int64")
            df["source_candidate_id"] = pd.array(
                [alert.source_candidate_id for alert in alerts], dtype="Int64"
            )

            if self._storage.file_format == "json":
                output_file = self._write_json(df, batch.batch_id, replace_existing=idempotent)
            else:
                if idempotent and not partition_by_date:
                    raise ValueError("Idempotent silver writes require partition_by_date=True")
                output_file = self._write_parquet(
                    df,
                    batch.batch_id,
                    partition_by_date,
                    replace_partitions=idempotent,
                )

            self._log.info(
                "write_silver_batch_completed",
                batch_id=batch.batch_id,
                output_file=str(output_file),
                records_written=len(alerts),
                replay_duplicates=len(existing_alerts) + batch.count - len(alerts),
            )
            return output_file
        except Exception as exc:
            raise WriteError(
                f"Failed to write silver batch {batch.batch_id}: {exc}",
                details={"batch_id": batch.batch_id, "error": str(exc)},
            ) from exc

    def read_silver_data(
        self,
        observation_date: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Read silver layer data back from storage."""
        if not self.output_path.exists():
            self._log.warning("silver_path_not_found", path=str(self.output_path))
            return pd.DataFrame()

        try:
            if self._storage.file_format == "json":
                json_files = list(self.output_path.glob("*.json"))
                if not json_files:
                    return pd.DataFrame()
                df = pd.concat([pd.read_json(path) for path in json_files], ignore_index=True)
                if observation_date and "observation_date" in df.columns:
                    df = df[df["observation_date"] == observation_date]
            else:
                filters = None
                if observation_date:
                    filters = [("observation_date", "=", observation_date)]
                df = pd.read_parquet(self.output_path, filters=filters, engine="pyarrow")

            if limit is not None:
                df = df.head(limit)
            return df
        except Exception as exc:
            raise SilverProcessingError(
                f"Failed to read silver data: {exc}",
                details={"path": str(self.output_path), "error": str(exc)},
            ) from exc

    def get_statistics(self) -> dict[str, Any]:
        """Get summary statistics about the silver layer."""
        df = self.read_silver_data()
        if df.empty:
            return {
                "total_records": 0,
                "unique_objects": 0,
                "date_range": None,
                "classifications": {},
            }

        stats: dict[str, Any] = {
            "total_records": len(df),
            "unique_objects": df["object_id"].nunique() if "object_id" in df.columns else 0,
        }
        if "observation_date" in df.columns:
            observation_dates = df["observation_date"].astype(str)
            stats["date_range"] = {
                "min": observation_dates.min(),
                "max": observation_dates.max(),
            }
        if "fink_class" in df.columns:
            stats["classifications"] = df["fink_class"].value_counts().to_dict()
        return stats

    def _quality_check(self, bronze_alert: BronzeAlert) -> tuple[bool, list[str]]:
        alert = bronze_alert.alert
        reasons: list[str] = []

        numeric_checks = {
            "ra": alert.ra,
            "dec": alert.dec,
            "magpsf": alert.magpsf,
            "sigmapsf": alert.sigmapsf,
            "jd": alert.jd,
        }
        for field, value in numeric_checks.items():
            if not self._is_finite_number(value):
                reasons.append(f"{field}_missing_or_non_finite")

        if alert.sigmapsf > 1.0:
            reasons.append("sigmapsf_gt_1")
        if alert.rb is not None and alert.rb < 0.2:
            reasons.append("rb_score_lt_0_2")

        return len(reasons) == 0, reasons

    def _to_silver_alert(
        self,
        bronze_alert: BronzeAlert,
        silver_processing_id: str,
    ) -> SilverAlert:
        raw_payload_json = self._serialize_raw_payload(bronze_alert.raw_payload)
        return SilverAlert(
            object_id=bronze_alert.alert.objectId,
            candidate_id=bronze_alert.alert.candid,
            ra=bronze_alert.alert.ra,
            dec=bronze_alert.alert.dec,
            magpsf=bronze_alert.alert.magpsf,
            sigmapsf=bronze_alert.alert.sigmapsf,
            filter_id=bronze_alert.alert.fid,
            filter_name=bronze_alert.alert.filter_name,
            jd=bronze_alert.alert.jd,
            mjd=bronze_alert.alert.mjd,
            observation_date=bronze_alert.observation_date
            or bronze_alert.ingestion_timestamp.strftime("%Y-%m-%d"),
            fink_class=bronze_alert.alert.v__fink_class,
            cds_xmatch=bronze_alert.alert.d__cdsxmatch,
            rb_score=bronze_alert.alert.rb,
            drb_score=bronze_alert.alert.drb,
            num_previous_detections=sum(
                1
                for candidate in bronze_alert.alert.prv_candidates or []
                if candidate.get("magpsf") is not None
            ),
            source=bronze_alert.source,
            source_version=bronze_alert.source_version,
            bronze_processing_id=bronze_alert.processing_id,
            silver_processing_id=silver_processing_id,
            source_object_id=bronze_alert.alert.objectId,
            source_candidate_id=bronze_alert.alert.candid,
            ingestion_timestamp=bronze_alert.ingestion_timestamp,
            raw_payload_hash=self._hash_raw_payload(raw_payload_json),
            raw_payload_json=raw_payload_json,
        )

    def _deduplicate(self, alerts: list[SilverAlert]) -> list[SilverAlert]:
        grouped: dict[tuple[str, Any], SilverAlert] = {}

        for alert in alerts:
            key = self._dedupe_key(alert)
            current = grouped.get(key)
            if current is None or self._dedupe_rank(alert) > self._dedupe_rank(current):
                grouped[key] = alert

        return list(grouped.values())

    def _dedupe_key(self, alert: SilverAlert) -> tuple[str, Any]:
        if alert.candidate_id is not None:
            return ("candidate_id", alert.candidate_id)
        return ("fallback", alert.object_id, round(alert.jd, 8), alert.filter_id)

    def _dedupe_rank(self, alert: SilverAlert) -> tuple[float, float, datetime]:
        return (
            alert.drb_score if alert.drb_score is not None else -math.inf,
            alert.rb_score if alert.rb_score is not None else -math.inf,
            alert.ingestion_timestamp,
        )

    def _write_parquet(
        self,
        df: pd.DataFrame,
        batch_id: str,
        partition_by_date: bool,
        replace_partitions: bool = False,
    ) -> Path:
        if partition_by_date and "observation_date" in df.columns:
            table = pa.Table.from_pandas(df)
            pq.write_to_dataset(
                table,
                root_path=str(self.output_path),
                partition_cols=["observation_date"],
                existing_data_behavior=(
                    "delete_matching" if replace_partitions else "overwrite_or_ignore"
                ),
            )
            return self.output_path

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_file = self.output_path / f"silver_alerts_{batch_id}_{timestamp}.parquet"
        df.to_parquet(output_file, index=False, engine="pyarrow")
        return output_file

    def _write_json(self, df: pd.DataFrame, batch_id: str, replace_existing: bool = False) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_file = self.output_path / f"silver_alerts_{batch_id}_{timestamp}.json"
        df.to_json(output_file, orient="records", indent=2)
        if replace_existing:
            for existing_file in self.output_path.glob("*.json"):
                if existing_file != output_file:
                    existing_file.unlink()
        return output_file

    def _read_existing_alerts(self, alerts: list[SilverAlert]) -> list[SilverAlert]:
        """Read only the observation dates touched by an incoming batch."""
        if self._storage.file_format == "json":
            existing = self.read_silver_data()
        else:
            frames = [
                self.read_silver_data(observation_date=date)
                for date in {alert.observation_date for alert in alerts}
            ]
            existing = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if existing.empty:
            return []
        return [
            SilverAlert(**{key: none_if_nan(value) for key, value in record.items()})
            for record in existing.to_dict("records")
        ]

    def _generate_batch_id(self) -> str:
        return f"silver_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def _serialize_raw_payload(self, payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload, sort_keys=True, default=str)

    def _hash_raw_payload(self, payload_json: str | None) -> str | None:
        if payload_json is None:
            return None
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    def _is_finite_number(self, value: float | int | None) -> bool:
        return value is not None and math.isfinite(float(value))


def create_silver_processor(
    settings: Settings | None = None,
) -> SilverProcessor:
    """Factory function to create a configured SilverProcessor."""
    return SilverProcessor(settings=settings)
