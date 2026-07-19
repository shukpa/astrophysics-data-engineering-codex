"""Tests for temporal replay/calibration metrics."""

from __future__ import annotations

import pytest
from tests.test_processing.test_classifier import make_gold

from src.analysis.calibration import (
    LabelledGoldAlert,
    coarse_class,
    evaluate_replay,
    select_object_disjoint_records,
)


def labelled(**overrides) -> LabelledGoldAlert:
    alert_overrides = overrides.pop("alert_overrides", {})
    return LabelledGoldAlert(
        alert=make_gold(**alert_overrides),
        truth_class=overrides.pop("truth_class", "SN Ia"),
        truth_is_rare=overrides.pop("truth_is_rare", False),
        label_source=overrides.pop("label_source", "ZTF BTS Sample Explorer"),
        tns_id=overrides.pop("tns_id", None),
        **overrides,
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("SN candidate", "supernova"),
        ("SN Ia", "supernova"),
        ("SLSN-II", "supernova"),
        ("TDE", "tde"),
        ("LBV", "galactic_variable"),
        ("AGN", "active_galaxy"),
        ("Unknown", "unknown"),
    ],
)
def test_coarse_class(label: str, expected: str) -> None:
    assert coarse_class(label) == expected


def test_temporal_replay_reports_accuracy_false_positives_and_misses() -> None:
    records = [
        labelled(alert_overrides={"object_id": "ZTF20train", "observation_date": "2020-08-01"}),
        labelled(
            truth_class="TDE",
            truth_is_rare=True,
            alert_overrides={
                "object_id": "ZTF21rare",
                "observation_date": "2021-08-01",
                "fink_class": None,
                "drb_score": 0.4,
            },
        ),
        labelled(
            alert_overrides={
                "object_id": "ZTF21falsepositive",
                "observation_date": "2021-08-02",
                "fink_class": None,
                "drb_score": 0.4,
            }
        ),
        labelled(
            truth_class="SLSN-II",
            truth_is_rare=True,
            alert_overrides={
                "object_id": "ZTF21missed",
                "observation_date": "2021-08-03",
                "fink_class": "SN candidate",
                "simbad_otype": "SN",
            },
        ),
    ]

    result = evaluate_replay(records, split_date="2021-01-01")

    assert result["metrics"]["train"]["alerts"] == 1
    validation = result["metrics"]["validation"]
    assert validation["alerts"] == 3
    assert validation["rare_review_targets"] == 2
    assert validation["true_positive"] == 1
    assert validation["false_positive"] == 1
    assert validation["false_negative"] == 1
    assert validation["precision"] == pytest.approx(0.5)
    assert validation["recall"] == pytest.approx(0.5)
    assert validation["false_positive_rate"] == pytest.approx(1.0)
    assert "Routing diagnostics only" in result["interpretation"]


def test_temporal_replay_rejects_object_leakage() -> None:
    records = [
        labelled(alert_overrides={"object_id": "ZTF20cross", "observation_date": "2020-12-31"}),
        labelled(alert_overrides={"object_id": "ZTF20cross", "observation_date": "2021-01-01"}),
    ]

    with pytest.raises(ValueError, match="crosses temporal split"):
        evaluate_replay(records, split_date="2021-01-01")


def test_crossing_objects_are_kept_only_in_validation_cohort() -> None:
    records = [
        labelled(alert_overrides={"object_id": "ZTF20train", "observation_date": "2020-01-01"}),
        labelled(alert_overrides={"object_id": "ZTF20cross", "observation_date": "2020-12-31"}),
        labelled(alert_overrides={"object_id": "ZTF20cross", "observation_date": "2021-01-01"}),
    ]

    selected, metadata = select_object_disjoint_records(records, split_date="2021-01-01")
    result = evaluate_replay(selected, split_date="2021-01-01")

    assert metadata["cross_split_objects"] == ["ZTF20cross"]
    assert metadata["alerts_excluded_for_disjoint_split"] == 1
    assert metadata["cross_split_policy"] == "validation_only"
    assert result["metrics"]["train"]["objects"] == 1
    assert result["metrics"]["validation"]["objects"] == 1
