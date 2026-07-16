"""Tests for the nightly report CLI (offline; synthetic gold batches)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scripts.nightly_report import load_gold_alerts, run_report
from scripts.run_fink_gold_smoke import run_smoke
from tests.test_processing.test_classifier import make_gold

SLDE_FIXTURE = Path("tests/fixtures/euclid/slde_q1_sample.json")


def write_gold_parquet(alerts, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([a.to_flat_dict() for a in alerts]).to_parquet(path, index=False)
    return path


def test_load_gold_alerts_cleans_parquet_nans(tmp_path: Path) -> None:
    alerts = [
        make_gold(object_id="ZTF26clean01"),
        make_gold(
            object_id="ZTF26clean02",
            candidate_id=None,
            gaia_g_mag=None,
            simbad_otype=None,
            lc_amplitude=None,
        ),
    ]
    gold_file = write_gold_parquet(alerts, tmp_path / "gold" / "batch.parquet")

    loaded = load_gold_alerts(gold_file)
    assert len(loaded) == 2
    reloaded = {a.object_id: a for a in loaded}
    assert reloaded["ZTF26clean02"].candidate_id is None
    assert reloaded["ZTF26clean02"].gaia_g_mag is None
    assert reloaded["ZTF26clean01"].candidate_id == 123456789


def test_run_report_on_mixed_batch(tmp_path: Path) -> None:
    alerts = [
        # A boring, well-classified variable star (LOW).
        make_gold(
            object_id="ZTF26vstar01",
            fink_class="Variable Star",
            is_likely_stellar=True,
            simbad_otype="RR*",
        ),
        # A lens-field hit: CRITICAL, always escalates.
        make_gold(
            object_id="ZTF26lenshit1",
            lens_field_transient=True,
            lens_name="EUCL J175707.2+653936",
            lens_separation_arcsec=2.4,
        ),
        # A kilonova candidate (HIGH).
        make_gold(object_id="ZTF26kilonova", fink_class="Kilonova candidate"),
        # A wildly off-baseline AGN (warm path, genuine-anomaly path).
        make_gold(
            object_id="ZTF26weirdagn",
            fink_class="AGN",
            simbad_otype="QSO",
            lc_mag_rate_per_day=3.0,
            lc_amplitude=None,
            lc_n_detections=12,
            drb_score=0.99,
        ),
    ]
    gold_file = write_gold_parquet(alerts, tmp_path / "gold" / "batch.parquet")

    summary = run_report(gold_file, tmp_path / "reports")

    assert summary["alerts_processed"] == 4
    assert summary["classified"] == 4
    assert summary["lens_field_matches"] == 1
    assert summary["critical"] >= 1
    assert summary["escalated"] >= 2  # lens hit + weird AGN
    assert summary["warm_path_assessed"] >= 2

    report = Path(summary["report_output"]).read_text(encoding="utf-8")
    assert "# AGD Nightly Report" in report
    assert "ZTF26lenshit1" in report
    assert "lens_field_transient" in report
    assert "## System metrics" in report
    assert "False-alarm probability" in report
    assert "Escalate: True" in report

    # Machine-readable outputs exist and carry the rigor fields.
    classifications = pd.read_parquet(summary["classifications_output"])
    assert len(classifications) == 4
    assert "follow_up_priority" in classifications.columns
    assessments = pd.read_parquet(summary["assessments_output"])
    for column in (
        "baseline_comparison",
        "deviation_sigma",
        "false_alarm_probability",
        "systematics",
        "escalate",
    ):
        assert column in assessments.columns


def test_run_report_empty_batch(tmp_path: Path) -> None:
    empty_dir = tmp_path / "gold"
    empty_dir.mkdir()
    summary = run_report(empty_dir, tmp_path / "reports")
    assert summary["alerts_processed"] == 0
    assert summary["classifications_output"] is None
    assert Path(summary["report_output"]).exists()


def test_end_to_end_smoke_gold_into_nightly_report(tmp_path: Path) -> None:
    """Acceptance: the agent runs on a real (synthetic) nightly batch."""
    smoke = run_smoke(
        fink_class="SN candidate",
        limit=8,
        storage_base=tmp_path / "data",
        source="synthetic",
        enable_crossmatch=False,
        lens_catalog_path=SLDE_FIXTURE,
    )
    summary = run_report(Path(smoke["gold_output"]), tmp_path / "reports")

    assert summary["alerts_processed"] == 8
    assert summary["classified"] == 8
    report = Path(summary["report_output"]).read_text(encoding="utf-8")
    assert "SN candidate | 8" in report.replace("|  ", "| ")
    # Synthetic positions don't overlap Q1 lenses: explicit zero, not absence.
    assert summary["lens_field_matches"] == 0
