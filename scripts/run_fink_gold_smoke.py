"""Run a Bronze-to-Silver-to-Gold smoke pipeline.

By default this pulls live Fink/ZTF alerts and cross-matches against live
Gaia DR3 + SIMBAD:

    python scripts/run_fink_gold_smoke.py --limit 25

For offline environments (no egress to api.fink-portal.org /
gea.esac.esa.int / simbad.cds.unistra.fr) a synthetic source exercises the
full medallion plumbing without any network access:

    python scripts/run_fink_gold_smoke.py --source synthetic --no-crossmatch
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.ingestion.fink_api_client import FinkAPIClient
from src.processing.bronze_processor import BronzeProcessor
from src.processing.gold_processor import GoldProcessor
from src.processing.silver_processor import SilverProcessor
from src.utils.config import CrossmatchSettings, ProcessingSettings, StorageSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--class", dest="fink_class", default="SN candidate")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--storage-base", type=Path, default=Path("./data/smoke"))
    parser.add_argument(
        "--source",
        choices=["live", "synthetic"],
        default="live",
        help="'live' pulls from the Fink API; 'synthetic' generates offline alerts.",
    )
    parser.add_argument(
        "--no-crossmatch",
        action="store_true",
        help="Skip Gaia/SIMBAD queries (offline mode); match columns stay null.",
    )
    return parser.parse_args()


def synthetic_alert_records(fink_class: str, n: int) -> list[dict[str, Any]]:
    """Deterministic synthetic alerts for offline smoke runs.

    Positions sweep along the celestial equator; every alert carries a small
    prv_candidates history so gold light-curve features are exercised.
    """
    records: list[dict[str, Any]] = []
    for i in range(n):
        jd = 2461000.5 + i * 0.01
        records.append(
            {
                "objectId": f"ZTF26synth{i:04d}",
                "candid": 900000000000 + i,
                "ra": (10.0 + i * 3.7) % 360.0,
                "dec": -30.0 + (i * 2.9) % 60.0,
                "magpsf": 17.5 + (i % 5) * 0.3,
                "sigmapsf": 0.05,
                "fid": (i % 2) + 1,
                "jd": jd,
                "rb": 0.9,
                "drb": 0.95,
                "v:fink_class": fink_class,
                "prv_candidates": [
                    {"jd": jd - 2.0, "fid": 1, "magpsf": 18.4 + (i % 5) * 0.3, "sigmapsf": 0.08},
                    {"jd": jd - 1.0, "fid": 2, "magpsf": 18.0 + (i % 5) * 0.3, "sigmapsf": 0.07},
                ],
            }
        )
    return records


def run_smoke(
    fink_class: str,
    limit: int,
    storage_base: Path,
    source: str = "live",
    enable_crossmatch: bool = True,
) -> dict[str, Any]:
    storage = StorageSettings(base_path=storage_base, file_format="parquet")
    processing = ProcessingSettings(schema_validation_mode="strict")
    crossmatch = CrossmatchSettings()

    if source == "synthetic":
        raw_alerts = synthetic_alert_records(fink_class=fink_class, n=limit)
    else:
        client = FinkAPIClient()
        raw_alerts = client.get_latest_alert_records(fink_class=fink_class, n=limit)

    bronze_processor = BronzeProcessor(
        storage_settings=storage,
        processing_settings=processing,
    )
    bronze_batch = bronze_processor.process_alerts(
        raw_alerts,
        source="fink_api" if source == "live" else "synthetic",
        source_version="v1",
    )
    bronze_output = bronze_processor.write_batch(bronze_batch)

    silver_processor = SilverProcessor(
        storage_settings=storage,
        processing_settings=processing,
    )
    silver_batch = silver_processor.process_batch(bronze_batch)
    silver_output = silver_processor.write_batch(silver_batch)

    gold_processor = GoldProcessor(
        storage_settings=storage,
        crossmatch_settings=crossmatch,
        enable_crossmatch=enable_crossmatch,
    )
    gold_batch = gold_processor.process_batch(silver_batch)
    gold_output = gold_processor.write_batch(gold_batch)

    return {
        "source": source,
        "crossmatch_enabled": enable_crossmatch,
        "requested": limit,
        "fetched": len(raw_alerts),
        "bronze_count": bronze_batch.count,
        "silver_count": silver_batch.count,
        "silver_rejected": silver_batch.rejected_count,
        "silver_duplicates": silver_batch.duplicate_count,
        "gold_count": gold_batch.count,
        "gold_gaia_matched": gold_batch.matched_gaia_count,
        "gold_simbad_matched": gold_batch.matched_simbad_count,
        "gold_crossmatch_failed": gold_batch.crossmatch_failed_count,
        "bronze_output": str(bronze_output),
        "silver_output": str(silver_output),
        "gold_output": str(gold_output),
    }


def main() -> None:
    args = parse_args()
    summary = run_smoke(
        fink_class=args.fink_class,
        limit=args.limit,
        storage_base=args.storage_base,
        source=args.source,
        enable_crossmatch=not args.no_crossmatch,
    )
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
