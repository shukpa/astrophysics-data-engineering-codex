"""Ingest Euclid Q1 open data into the AGD medallion.

Two catalogue products, each with full provenance:

1. **MER final catalogue** (live ESA TAP cone search) -> Euclid bronze.
2. **SLDE strong-lens catalogue** (local JSON/CSV; not exposed via ESA TAP)
   -> Euclid bronze (raw rows) -> silver (validated, grade-filtered
   EuclidLensCandidate rows).

Offline environments can skip the live MER pull:

    python scripts/ingest_euclid_q1.py --skip-mer \
        --slde-path tests/fixtures/euclid/slde_q1_sample.json

Live (EDF-F cone by default; set EUCLID_TAP_PROXY_URL / EUCLID_TAP_CA_BUNDLE
behind a CONNECT proxy):

    python scripts/ingest_euclid_q1.py --discover
"""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.euclid_client import EuclidClient
from src.processing.euclid_lens_processor import EuclidLensProcessor, load_lens_rows
from src.utils.config import EuclidSettings, StorageSettings

# Q1 Deep Field Fornax centre — the default MER cone target.
EDF_F_RA = 52.93
EDF_F_DEC = -28.09


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-base", type=Path, default=Path("./data"))
    parser.add_argument(
        "--slde-path",
        type=Path,
        default=Path("tests/fixtures/euclid/slde_q1_sample.json"),
        help="SLDE catalogue file (JSON/CSV). Default is the bundled sample; "
        "point at the published table for science use.",
    )
    parser.add_argument("--skip-mer", action="store_true", help="Skip the live MER TAP pull.")
    parser.add_argument("--mer-ra", type=float, default=EDF_F_RA)
    parser.add_argument("--mer-dec", type=float, default=EDF_F_DEC)
    parser.add_argument("--mer-radius-deg", type=float, default=0.05)
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Run live tap_schema discovery first and print catalogue tables.",
    )
    return parser.parse_args()


def write_mer_bronze(
    df: pd.DataFrame,
    provenance: dict[str, Any],
    storage: StorageSettings,
) -> Path:
    """Persist MER rows + provenance columns to the Euclid bronze layer."""
    batch_id = f"mer_bronze_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    out_dir = storage.euclid_bronze_full_path
    out_dir.mkdir(parents=True, exist_ok=True)

    enriched = df.copy()
    enriched["_ingest_source"] = provenance["source"]
    enriched["_ingest_table"] = provenance["table"]
    enriched["_ingest_query"] = provenance["query"]
    enriched["_ingest_dr_tag"] = provenance["dr_tag"]
    enriched["_ingest_retrieved_at"] = provenance["retrieved_at"]
    enriched["_ingest_batch_id"] = batch_id

    output = out_dir / f"{batch_id}.parquet"
    enriched.to_parquet(output, index=False)
    return output


def run_ingest(
    storage_base: Path,
    slde_path: Path,
    skip_mer: bool = False,
    mer_ra: float = EDF_F_RA,
    mer_dec: float = EDF_F_DEC,
    mer_radius_deg: float = 0.05,
    discover: bool = False,
) -> dict[str, Any]:
    storage = StorageSettings(base_path=storage_base)
    euclid_settings = EuclidSettings()
    summary: dict[str, Any] = {"dr_tag": euclid_settings.dr_tag}

    # --- MER final catalogue (live TAP) -> bronze ---
    if not skip_mer:
        # Cache under THIS run's storage base (the client's default derives
        # from global settings, which would leak outside --storage-base).
        client = EuclidClient(
            euclid_settings=euclid_settings,
            cache_dir=storage.base_path / euclid_settings.cache_path,
        )
        if discover:
            tables = client.discover_tables("catalogue")
            summary["discovered_catalogue_tables"] = len(tables)
        mer_df, provenance = client.mer_cone_search(
            ra=mer_ra, dec=mer_dec, radius_deg=mer_radius_deg
        )
        mer_output = write_mer_bronze(mer_df, provenance, storage)
        summary["mer_rows"] = len(mer_df)
        summary["mer_bronze_output"] = str(mer_output)
        summary["mer_cache_hit"] = provenance["cache_hit"]
    else:
        summary["mer_rows"] = "skipped"

    # --- SLDE lens catalogue (file) -> bronze -> silver ---
    processor = EuclidLensProcessor(storage_settings=storage, euclid_settings=euclid_settings)
    raw_rows = load_lens_rows(slde_path)
    bronze_output = processor.write_bronze(raw_rows, source=str(slde_path))
    catalog, counters = processor.process_catalog(raw_rows, source=str(slde_path))
    silver_output = processor.write_silver(catalog)

    summary.update(
        {
            "slde_source": str(slde_path),
            "slde_input": counters["input"],
            "slde_kept": counters["kept"],
            "slde_rejected_grade": counters["rejected_grade"],
            "slde_rejected_invalid": counters["rejected_invalid"],
            "slde_by_grade": catalog.by_grade(),
            "slde_bronze_output": str(bronze_output),
            "slde_silver_output": str(silver_output),
            "silver_lenses_readable": len(processor.read_silver_lenses()),
        }
    )
    return summary


def main() -> None:
    args = parse_args()
    summary = run_ingest(
        storage_base=args.storage_base,
        slde_path=args.slde_path,
        skip_mer=args.skip_mer,
        mer_ra=args.mer_ra,
        mer_dec=args.mer_dec,
        mer_radius_deg=args.mer_radius_deg,
        discover=args.discover,
    )
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
