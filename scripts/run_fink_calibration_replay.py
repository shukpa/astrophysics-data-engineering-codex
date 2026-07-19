"""Replay a bounded, BTS-labelled ZTF object sample through Bronze/Silver/Gold.

Example:

    python scripts/run_fink_calibration_replay.py \
        --manifest tests/fixtures/calibration/ztf_bts_replay_manifest.json \
        --split-date 2021-01-01 --max-objects 20 --max-alerts 100 \
        --max-alerts-per-object 100 \
        --no-crossmatch
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.analysis.calibration import (
    LabelledGoldAlert,
    evaluate_replay,
    select_object_disjoint_records,
)
from src.ingestion.fink_api_client import FinkAPIClient, canonicalize_fink_alert_record
from src.processing.bronze_processor import BronzeProcessor
from src.processing.gold_processor import GoldProcessor
from src.processing.silver_processor import SilverProcessor
from src.utils.config import CrossmatchSettings, ProcessingSettings, StorageSettings

HARD_OBJECT_CAP = 1000
HARD_ALERTS_PER_OBJECT_CAP = 1000
HARD_ALERT_CAP = 1000


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a provenance-bearing BTS replay manifest."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects:
        raise ValueError("Replay manifest must contain a non-empty objects list")
    required = {"object_id", "truth_class", "truth_is_rare", "label_source"}
    for row in objects:
        missing = required - set(row)
        if missing:
            raise ValueError(f"Replay manifest row is missing fields: {sorted(missing)}")
    object_ids = [row["object_id"] for row in objects]
    if len(set(object_ids)) != len(object_ids):
        raise ValueError("Replay manifest contains duplicate object_id values")
    return manifest, objects


def run_replay(
    manifest_path: Path,
    *,
    storage_base: Path,
    split_date: str,
    max_objects: int = 100,
    max_alerts: int = 100,
    max_alerts_per_object: int = 100,
    enable_crossmatch: bool = False,
    client: FinkAPIClient | None = None,
) -> dict[str, Any]:
    """Run a bounded labelled-object replay and write predictions/metrics."""
    if not 1 <= max_objects <= HARD_OBJECT_CAP:
        raise ValueError(f"max_objects must be between 1 and {HARD_OBJECT_CAP}")
    if not 1 <= max_alerts_per_object <= HARD_ALERTS_PER_OBJECT_CAP:
        raise ValueError(
            f"max_alerts_per_object must be between 1 and {HARD_ALERTS_PER_OBJECT_CAP}"
        )
    if not 1 <= max_alerts <= HARD_ALERT_CAP:
        raise ValueError(f"max_alerts must be between 1 and {HARD_ALERT_CAP}")

    manifest, object_rows = load_manifest(manifest_path)
    selected = object_rows[:max_objects]
    labels = {row["object_id"]: row for row in selected}
    fink = client or FinkAPIClient()
    raw_alerts: list[dict[str, Any]] = []
    fetched_by_object: dict[str, int] = {}

    object_ids = list(labels)
    for index, object_id in enumerate(object_ids):
        remaining = max_alerts - len(raw_alerts)
        if remaining <= 0:
            break
        remaining_objects = len(object_ids) - index
        fair_share = (remaining + remaining_objects - 1) // remaining_objects
        frame = fink.get_object(object_id)
        records = frame.tail(min(max_alerts_per_object, fair_share, remaining)).to_dict("records")
        fetched_by_object[object_id] = len(records)
        raw_alerts.extend(canonicalize_fink_alert_record(record) for record in records)

    storage = StorageSettings(base_path=storage_base, file_format="parquet")
    processing = ProcessingSettings(schema_validation_mode="strict")
    bronze = BronzeProcessor(storage_settings=storage, processing_settings=processing)
    bronze_batch = bronze.process_alerts(
        raw_alerts, source="fink_ztf_bts_replay", source_version="v1"
    )
    bronze_output = bronze.write_batch(bronze_batch)
    silver = SilverProcessor(storage_settings=storage, processing_settings=processing)
    silver_batch = silver.process_batch(bronze_batch)
    silver_output = silver.write_batch(silver_batch)
    gold = GoldProcessor(
        storage_settings=storage,
        crossmatch_settings=CrossmatchSettings(),
        enable_crossmatch=enable_crossmatch,
    )
    gold_batch = gold.process_batch(silver_batch)
    gold_output = gold.write_batch(gold_batch)

    labelled = [
        LabelledGoldAlert(
            alert=alert,
            truth_class=labels[alert.object_id]["truth_class"],
            truth_is_rare=labels[alert.object_id]["truth_is_rare"],
            label_source=labels[alert.object_id]["label_source"],
            tns_id=labels[alert.object_id].get("tns_id"),
        )
        for alert in gold_batch.alerts
        if alert.object_id in labels
    ]
    disjoint, split_metadata = select_object_disjoint_records(labelled, split_date=split_date)
    evaluation = evaluate_replay(disjoint, split_date=split_date)
    output_dir = storage_base / "calibration"
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.parquet"
    pd.DataFrame(evaluation["predictions"]).to_parquet(predictions_path, index=False)
    metrics_path = output_dir / "metrics.json"
    summary = {
        "manifest": str(manifest_path),
        "manifest_source": manifest.get("source_url"),
        "objects_requested": len(selected),
        "alerts_fetched": len(raw_alerts),
        "max_alerts": max_alerts,
        "fetched_by_object": fetched_by_object,
        "bronze_count": bronze_batch.count,
        "silver_count": silver_batch.count,
        "silver_rejected": silver_batch.rejected_count,
        "gold_count": gold_batch.count,
        "crossmatch_enabled": enable_crossmatch,
        "crossmatch_failed": gold_batch.crossmatch_failed_count,
        "split_date": split_date,
        **split_metadata,
        "metrics": evaluation["metrics"],
        "interpretation": evaluation["interpretation"],
        "bronze_output": str(bronze_output),
        "silver_output": str(silver_output),
        "gold_output": str(gold_output),
        "predictions_output": str(predictions_path),
        "metrics_output": str(metrics_path),
    }
    metrics_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--storage-base", type=Path, default=Path("./data/calibration-replay"))
    parser.add_argument("--split-date", default="2021-01-01")
    parser.add_argument("--max-objects", type=int, default=100)
    parser.add_argument("--max-alerts", type=int, default=100)
    parser.add_argument("--max-alerts-per-object", type=int, default=100)
    parser.add_argument("--no-crossmatch", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_replay(
        args.manifest,
        storage_base=args.storage_base,
        split_date=args.split_date,
        max_objects=args.max_objects,
        max_alerts=args.max_alerts,
        max_alerts_per_object=args.max_alerts_per_object,
        enable_crossmatch=not args.no_crossmatch,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
