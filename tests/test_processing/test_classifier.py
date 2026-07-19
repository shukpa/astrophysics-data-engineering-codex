"""Tests for the Tier-1 hot-path baseline classifier (deterministic, offline)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models.alerts import GoldAlert
from src.models.classification import FollowUpPriority
from src.processing.classifier import (
    CLASSIFIER_VERSION,
    BaselineClassifier,
    fink_category,
    simbad_category,
)
from src.utils.config import ClassificationSettings

NOW = datetime(2026, 7, 14, 3, 0, 0, tzinfo=UTC)


def make_gold(**overrides) -> GoldAlert:
    """Build a GoldAlert with sensible defaults for classifier tests."""
    base = {
        "object_id": "ZTF26abcdefg",
        "candidate_id": 123456789,
        "ra": 150.0,
        "dec": 2.2,
        "magpsf": 18.5,
        "sigmapsf": 0.05,
        "filter_id": 1,
        "filter_name": "g",
        "jd": 2461234.5,
        "mjd": 61234.0,
        "observation_date": "2026-07-13",
        "fink_class": "SN candidate",
        "rb_score": 0.9,
        "drb_score": 0.95,
        "lc_n_detections": 8,
        "source": "fink_api",
        "source_object_id": "ZTF26abcdefg",
        "ingestion_timestamp": NOW,
        "silver_timestamp": NOW,
    }
    base.update(overrides)
    return GoldAlert(**base)


class TestCategories:
    def test_simbad_stellar_variants(self) -> None:
        for otype in ("V*", "RR*", "CV*", "*iC", "YSO", "Mira"):
            assert simbad_category(otype) == "stellar"

    def test_simbad_extragalactic_variants(self) -> None:
        for otype in ("G", "QSO", "AGN", "Sy1", "BLL", "SN"):
            assert simbad_category(otype) == "extragalactic"

    def test_simbad_unknown_and_missing(self) -> None:
        assert simbad_category(None) is None
        assert simbad_category("Radio") is None

    def test_fink_categories(self) -> None:
        assert fink_category("SN candidate") == "extragalactic"
        assert fink_category("Variable Star") == "stellar"
        assert fink_category("Solar System MPC") is None
        assert fink_category(None) is None


class TestClassify:
    def test_known_fink_class_is_primary(self) -> None:
        result = BaselineClassifier().classify(make_gold())
        assert result.primary_class == "SN candidate"
        assert result.classifier_version == CLASSIFIER_VERSION
        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.anomaly_score <= 1.0

    def test_unknown_class_gets_low_confidence(self) -> None:
        known = BaselineClassifier().classify(make_gold())
        unknown = BaselineClassifier().classify(make_gold(fink_class=None))
        assert unknown.primary_class == "Unknown"
        assert unknown.confidence < known.confidence

    def test_stellar_contradiction_lowers_confidence_and_adds_alternative(self) -> None:
        clean = BaselineClassifier().classify(make_gold())
        contradicted = BaselineClassifier().classify(
            make_gold(is_likely_stellar=True, stellar_evidence="parallax_snr=12")
        )
        assert contradicted.confidence < clean.confidence
        assert any(a.label == "Variable Star" for a in contradicted.alternatives)

    def test_simbad_agreement_raises_confidence(self) -> None:
        neutral = BaselineClassifier().classify(make_gold(fink_class="AGN"))
        agreeing = BaselineClassifier().classify(make_gold(fink_class="AGN", simbad_otype="QSO"))
        assert agreeing.confidence > neutral.confidence

    def test_simbad_contradiction_adds_alternative(self) -> None:
        result = BaselineClassifier().classify(
            make_gold(fink_class="SN candidate", simbad_otype="RR*")
        )
        assert any(a.label == "Variable Star" for a in result.alternatives)

    def test_anomaly_score_tracks_poor_fit(self) -> None:
        clean = BaselineClassifier().classify(make_gold(simbad_otype="SN"))
        messy = BaselineClassifier().classify(
            make_gold(
                fink_class=None,
                is_likely_stellar=True,
                stellar_evidence="pm_snr=9",
                drb_score=0.5,
            )
        )
        assert messy.anomaly_score > clean.anomaly_score

    def test_per_filter_features_prevent_color_from_looking_like_variability(self) -> None:
        band = {
            "filter_id": 1,
            "filter_name": "g",
            "n_detections": 2,
            "time_span_days": 2.0,
            "mag_brightest": 19.0,
            "mag_faintest": 19.0,
            "mag_mean": 19.0,
            "mag_weighted_mean": 19.0,
            "mean_sigmapsf": 0.05,
            "amplitude": 0.0,
            "amplitude_uncertainty": 0.07,
            "median_cadence_days": 2.0,
            "mag_rate_per_day": 0.0,
            "mag_rate_uncertainty": 0.04,
        }
        alert = make_gold(
            lc_amplitude=2.0,
            lc_mag_rate_per_day=2.0,
            lc_per_filter={
                "g": band,
                "r": {**band, "filter_id": 2, "filter_name": "r", "mag_mean": 17.0},
            },
        )

        result = BaselineClassifier().classify(alert)

        assert result.anomaly_score < 0.7
        assert result.follow_up_priority is not FollowUpPriority.CRITICAL


class TestPriority:
    def test_lens_field_transient_is_critical_regardless(self) -> None:
        # Even a boringly well-classified variable star escalates on a lens hit.
        result = BaselineClassifier().classify(
            make_gold(
                fink_class="Variable Star",
                is_likely_stellar=True,
                simbad_otype="RR*",
                lens_field_transient=True,
                lens_name="EUCL J175707.2+653936",
            )
        )
        assert result.follow_up_priority is FollowUpPriority.CRITICAL
        assert "lens_field_transient" in result.priority_reason

    def test_gw_counterpart_flag_is_critical_when_field_lands(self) -> None:
        # Phase 5 adds the field to GoldAlert; the classifier must pick it up
        # via duck typing the moment it exists.
        class GwGoldAlert(GoldAlert):
            gw_counterpart_candidate: bool = False

        alert = GwGoldAlert(
            **{**make_gold(fink_class="Kilonova candidate").model_dump()},
        )
        object.__setattr__(alert, "gw_counterpart_candidate", True)
        result = BaselineClassifier().classify(alert)
        assert result.follow_up_priority is FollowUpPriority.CRITICAL
        assert "gw_counterpart_candidate" in result.priority_reason

    def test_high_anomaly_score_is_high_and_enters_warm_path(self) -> None:
        result = BaselineClassifier().classify(
            make_gold(fink_class=None, drb_score=0.5, is_likely_stellar=None)
        )
        assert result.anomaly_score >= 0.7
        assert result.follow_up_priority is FollowUpPriority.HIGH
        assert "anomaly_score" in result.priority_reason
        assert "warm-path rigor check" in result.priority_reason

    def test_valuable_known_types_are_high(self) -> None:
        for cls in ("Kilonova candidate", "Early SN Ia candidate", "Microlensing candidate"):
            result = BaselineClassifier().classify(make_gold(fink_class=cls))
            assert result.follow_up_priority is FollowUpPriority.HIGH, cls

    def test_well_characterised_types_are_low(self) -> None:
        result = BaselineClassifier().classify(
            make_gold(fink_class="Variable Star", is_likely_stellar=True, simbad_otype="V*")
        )
        assert result.follow_up_priority is FollowUpPriority.LOW

    def test_default_is_medium(self) -> None:
        result = BaselineClassifier().classify(make_gold(simbad_otype="SN"))
        assert result.follow_up_priority is FollowUpPriority.MEDIUM

    def test_priority_ordering_helper(self) -> None:
        assert FollowUpPriority.CRITICAL.at_least(FollowUpPriority.HIGH)
        assert not FollowUpPriority.MEDIUM.at_least(FollowUpPriority.HIGH)


class TestBatchAndConfig:
    def test_batch_preserves_order(self) -> None:
        alerts = [make_gold(object_id=f"ZTF26batch{i:03d}") for i in range(5)]
        results = BaselineClassifier().classify_batch(alerts)
        assert [r.object_id for r in results] == [a.object_id for a in alerts]

    def test_config_driven_priority_lists(self) -> None:
        config = ClassificationSettings(high_priority_classes=["SN candidate"])
        result = BaselineClassifier(classification_settings=config).classify(make_gold())
        assert result.follow_up_priority is FollowUpPriority.HIGH

    def test_flat_dict_serialises_alternatives(self) -> None:
        result = BaselineClassifier().classify(
            make_gold(is_likely_stellar=True, stellar_evidence="parallax_snr=12")
        )
        flat = result.to_flat_dict()
        assert isinstance(flat["alternatives"], str)
        assert "Variable Star" in flat["alternatives"]

    def test_confidence_bounds_hold_under_extremes(self) -> None:
        worst = BaselineClassifier().classify(
            make_gold(
                fink_class=None,
                drb_score=0.0,
                rb_score=0.0,
                is_likely_stellar=True,
                stellar_evidence="pm",
                simbad_otype="QSO",
            )
        )
        best = BaselineClassifier().classify(
            make_gold(
                fink_class="Variable Star",
                drb_score=1.0,
                is_likely_stellar=True,
                simbad_otype="V*",
            )
        )
        assert 0.0 <= worst.confidence <= 1.0
        assert 0.0 <= best.confidence <= 1.0
        assert 0.0 <= worst.anomaly_score <= 1.0


@pytest.mark.parametrize("mpc_class", ["Solar System MPC", "Solar System candidate"])
def test_solar_system_classes_are_low_priority(mpc_class: str) -> None:
    result = BaselineClassifier().classify(make_gold(fink_class=mpc_class))
    assert result.follow_up_priority is FollowUpPriority.LOW
