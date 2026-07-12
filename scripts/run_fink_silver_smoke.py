"""Run a live Fink/ZTF Bronze-to-Silver smoke pipeline."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from src.ingestion.fink_api_client import FinkAPIClient
from src.models.alerts import SilverBatch
from src.processing.bronze_processor import BronzeProcessor
from src.processing.silver_processor import SilverProcessor
from src.utils.config import ProcessingSettings, StorageSettings

DATABRICKS_COLUMNS = [
    "object_id",
    "candidate_id",
    "ra",
    "dec",
    "magpsf",
    "sigmapsf",
    "filter_id",
    "jd",
    "mjd",
    "observation_date",
    "fink_class",
    "rb_score",
    "drb_score",
    "source",
    "bronze_processing_id",
    "silver_processing_id",
    "raw_payload_hash",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--class", dest="fink_class", default="SN candidate")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--storage-base", type=Path, default=Path("./data/smoke"))
    parser.add_argument("--databricks-sql-output", type=Path)
    return parser.parse_args()


def run_smoke(
    fink_class: str,
    limit: int,
    storage_base: Path,
    databricks_sql_output: Path | None = None,
) -> dict[str, Any]:
    storage = StorageSettings(base_path=storage_base, file_format="parquet")
    processing = ProcessingSettings(schema_validation_mode="strict")

    client = FinkAPIClient()
    raw_alerts = client.get_latest_alert_records(fink_class=fink_class, n=limit)

    bronze_processor = BronzeProcessor(
        storage_settings=storage,
        processing_settings=processing,
    )
    bronze_batch = bronze_processor.process_alerts(
        raw_alerts,
        source="fink_api",
        source_version="v1",
    )
    bronze_output = bronze_processor.write_batch(bronze_batch)

    silver_processor = SilverProcessor(
        storage_settings=storage,
        processing_settings=processing,
    )
    silver_batch = silver_processor.process_batch(bronze_batch)
    silver_output = silver_processor.write_batch(silver_batch)

    if databricks_sql_output is not None:
        databricks_sql_output.parent.mkdir(parents=True, exist_ok=True)
        databricks_sql_output.write_text(generate_databricks_sql(silver_batch), encoding="utf-8")

    return {
        "requested": limit,
        "fetched": len(raw_alerts),
        "bronze_count": bronze_batch.count,
        "silver_count": silver_batch.count,
        "silver_rejected": silver_batch.rejected_count,
        "silver_duplicates": silver_batch.duplicate_count,
        "bronze_output": str(bronze_output),
        "silver_output": str(silver_output),
    }


def generate_databricks_sql(silver_batch: SilverBatch) -> str:
    """Generate bounded SQL VALUES input for a Databricks smoke table."""
    rows = [alert.to_flat_dict() for alert in silver_batch.alerts]
    if not rows:
        return (
            "SELECT "
            + ", ".join(f"CAST(NULL AS STRING) AS {column}" for column in DATABRICKS_COLUMNS)
            + " WHERE false"
        )

    values = []
    for row in rows:
        values.append(
            "(" + ", ".join(_sql_literal(row.get(column)) for column in DATABRICKS_COLUMNS) + ")"
        )

    return (
        "SELECT * FROM VALUES\n  "
        + ",\n  ".join(values)
        + "\nAS t("
        + ", ".join(DATABRICKS_COLUMNS)
        + ")"
    )


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return "NULL"
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def main() -> None:
    args = parse_args()
    summary = run_smoke(
        fink_class=args.fink_class,
        limit=args.limit,
        storage_base=args.storage_base,
        databricks_sql_output=args.databricks_sql_output,
    )
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
