"""Tests for the Euclid Q1 ingest script (offline; MER TAP mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
from scripts.ingest_euclid_q1 import run_ingest
from scripts.run_fink_gold_smoke import run_smoke

from src.ingestion.euclid_client import EuclidClient

SLDE_FIXTURE = Path("tests/fixtures/euclid/slde_q1_sample.json")
MER_FIXTURE = Path("tests/fixtures/euclid/mer_q1_sample.json")


def test_run_ingest_offline_slde_only(tmp_path: Path) -> None:
    summary = run_ingest(
        storage_base=tmp_path / "data",
        slde_path=SLDE_FIXTURE,
        skip_mer=True,
    )

    assert summary["mer_rows"] == "skipped"
    assert summary["slde_input"] == 20
    assert summary["slde_kept"] == 16  # 4 grade-C rows filtered by default
    assert summary["slde_rejected_grade"] == 4
    assert summary["slde_by_grade"] == {"A": 8, "B": 8}
    assert summary["silver_lenses_readable"] == 16

    bronze = pd.read_parquet(summary["slde_bronze_output"])
    assert len(bronze) == 20  # bronze preserves ALL raw rows
    assert "_ingest_dr_tag" in bronze.columns

    silver = pd.read_parquet(summary["slde_silver_output"])
    assert len(silver) == 16
    assert set(silver["grade"]) == {"A", "B"}


def test_run_ingest_with_mocked_mer(tmp_path: Path) -> None:
    mer_df = pd.read_json(MER_FIXTURE)

    with patch.object(EuclidClient, "_execute_adql", return_value=mer_df):
        summary = run_ingest(
            storage_base=tmp_path / "data",
            slde_path=SLDE_FIXTURE,
            skip_mer=False,
        )

    assert summary["mer_rows"] == 20
    assert summary["mer_cache_hit"] is False

    bronze = pd.read_parquet(summary["mer_bronze_output"])
    assert len(bronze) == 20
    # Provenance columns attached to every MER bronze row.
    for column in (
        "_ingest_source",
        "_ingest_table",
        "_ingest_query",
        "_ingest_dr_tag",
        "_ingest_retrieved_at",
        "_ingest_batch_id",
    ):
        assert column in bronze.columns
    assert (bronze["_ingest_dr_tag"] == "Q1").all()
    assert (bronze["_ingest_source"] == "esa_euclid_tap").all()


def test_gold_smoke_lens_field_job(tmp_path: Path) -> None:
    """Acceptance: the lens_field_transient job runs through the smoke CLI.

    Synthetic transients don't sit on Q1 lens positions, so zero matches is
    the expected (fine) outcome — the point is that the job executes and the
    columns exist.
    """
    summary = run_smoke(
        fink_class="SN candidate",
        limit=5,
        storage_base=tmp_path / "data",
        source="synthetic",
        enable_crossmatch=False,
        lens_catalog_path=SLDE_FIXTURE,
    )

    assert summary["lens_catalog_size"] == 16  # grade-filtered
    assert summary["gold_lens_matched"] == 0  # expected: no overlap

    gold = pd.read_parquet(summary["gold_output"])
    assert "lens_field_transient" in gold.columns
    assert "lens_name" in gold.columns
    assert (~gold["lens_field_transient"].astype(bool)).all()
