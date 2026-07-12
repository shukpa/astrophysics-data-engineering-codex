"""Tests for the Bronze-to-Silver-to-Gold smoke script."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scripts.run_fink_gold_smoke import run_smoke, synthetic_alert_records

from src.ingestion.fink_api_client import FinkAPIClient


def test_synthetic_records_are_deterministic_and_valid() -> None:
    records = synthetic_alert_records("SN candidate", 5)
    assert len(records) == 5
    assert records == synthetic_alert_records("SN candidate", 5)
    assert all(0 <= record["ra"] < 360 for record in records)
    assert all(record["prv_candidates"] for record in records)


def test_run_smoke_synthetic_offline_end_to_end(tmp_path: Path) -> None:
    summary = run_smoke(
        fink_class="SN candidate",
        limit=6,
        storage_base=tmp_path / "data",
        source="synthetic",
        enable_crossmatch=False,
    )

    assert summary["fetched"] == 6
    assert summary["bronze_count"] == 6
    assert summary["silver_count"] == 6
    assert summary["gold_count"] == 6
    assert summary["gold_crossmatch_failed"] == 0

    # Gold parquet exists with cross-match + feature columns present
    gold_df = pd.read_parquet(summary["gold_output"])
    assert len(gold_df) == 6
    for column in ("gaia_source_id", "simbad_otype", "is_likely_stellar", "lc_n_detections"):
        assert column in gold_df.columns
    assert "raw_payload_json" not in gold_df.columns
    # Synthetic alerts carry 2 prv detections + current epoch
    assert set(gold_df["lc_n_detections"]) == {3}


def test_run_smoke_live_source_with_mocked_fink(monkeypatch, tmp_path: Path) -> None:
    def fake_latest_records(
        _self: FinkAPIClient,
        fink_class: str,
        n: int,
    ) -> list[dict]:
        return synthetic_alert_records(fink_class, n)

    monkeypatch.setattr(FinkAPIClient, "get_latest_alert_records", fake_latest_records)

    summary = run_smoke(
        fink_class="SN candidate",
        limit=3,
        storage_base=tmp_path / "data",
        source="live",
        enable_crossmatch=False,
    )

    assert summary["source"] == "live"
    assert summary["gold_count"] == 3
