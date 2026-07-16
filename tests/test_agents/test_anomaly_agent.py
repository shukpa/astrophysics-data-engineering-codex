"""Tests for the warm-path anomaly agent (deterministic, offline).

Focus: the four mandatory rigor fields, the trials-corrected FAP, and the
escalation rules (CRITICAL always escalates; statistics + systematics gate
everything else).
"""

from __future__ import annotations

import pytest

from src.agents.anomaly_agent import AGENT_VERSION, AnomalyAgent, trials_corrected_fap
from src.models.classification import FollowUpPriority
from src.processing.classifier import BaselineClassifier
from src.utils.config import AnomalySettings
from tests.test_processing.test_classifier import make_gold


def classify_and_assess(alert, *, n_alerts=100, anomaly_settings=None):
    classification = BaselineClassifier().classify(alert)
    agent = AnomalyAgent(anomaly_settings=anomaly_settings)
    return classification, agent.assess(alert, classification, n_alerts_processed=n_alerts)


class TestTrialsCorrectedFap:
    def test_single_trial_is_p(self) -> None:
        assert trials_corrected_fap(0.5, 1) == pytest.approx(0.5)

    def test_small_p_many_trials_is_approximately_p_times_n(self) -> None:
        assert trials_corrected_fap(1e-6, 1000) == pytest.approx(1e-3, rel=1e-2)

    def test_caps_at_one(self) -> None:
        assert trials_corrected_fap(0.01, 10_000_000) == 1.0
        assert trials_corrected_fap(1.0, 1) == 1.0


class TestRigorFields:
    def test_every_assessment_carries_all_four_fields(self) -> None:
        _, assessment = classify_and_assess(make_gold())
        assert assessment.baseline_comparison  # 1: baseline stated
        assert assessment.deviation_sigma >= 0.0  # 2: sigma
        assert 0.0 <= assessment.false_alarm_probability <= 1.0  # 3: FAP
        assert len(assessment.systematics) >= 5  # 4: checklist
        assert assessment.agent_version == AGENT_VERSION
        names = {c.name for c in assessment.systematics}
        assert {
            "bogus_detection",
            "moving_object",
            "stellar_variability",
            "insufficient_history",
            "bright_star_artifact",
        } <= names

    def test_baseline_mentions_class_behaviour_and_measurements(self) -> None:
        _, assessment = classify_and_assess(make_gold(lc_mag_rate_per_day=-0.2, lc_amplitude=1.4))
        assert "Supernovae" in assessment.baseline_comparison
        assert "sigma" in assessment.baseline_comparison

    def test_no_features_yields_zero_deviation(self) -> None:
        _, assessment = classify_and_assess(make_gold(lc_mag_rate_per_day=None, lc_amplitude=None))
        assert assessment.deviation_sigma == 0.0
        assert "no usable light-curve features" in assessment.baseline_comparison


class TestEscalation:
    def test_critical_lens_hit_always_escalates(self) -> None:
        # Deliberately dirty: 2 detections, mediocre real/bogus — the
        # statistics say no, the CRITICAL rule says yes.
        alert = make_gold(
            lens_field_transient=True,
            lens_name="EUCL J040318.5-484427",
            lc_n_detections=2,
            drb_score=0.6,
        )
        classification, assessment = classify_and_assess(alert)
        assert classification.follow_up_priority is FollowUpPriority.CRITICAL
        assert assessment.escalate is True
        assert "CRITICAL" in assessment.escalation_reason

    def test_genuine_anomaly_escalates_when_everything_passes(self) -> None:
        # An AGN evolving at 3 mag/day is wildly off-baseline (sigma >> 3).
        alert = make_gold(
            fink_class="AGN",
            simbad_otype="QSO",
            lc_mag_rate_per_day=3.0,
            lc_amplitude=None,
            lc_n_detections=12,
            drb_score=0.99,
        )
        classification, assessment = classify_and_assess(alert, n_alerts=100)
        assert assessment.deviation_sigma > 3.0
        assert assessment.all_systematics_excluded
        assert assessment.false_alarm_probability < 0.01
        assert assessment.escalate is True
        assert "genuine anomaly candidate" in assessment.escalation_reason

    def test_unexcluded_systematic_blocks_escalation(self) -> None:
        # Same wild deviation, but only 2 detections: insufficient history.
        alert = make_gold(
            fink_class="AGN",
            simbad_otype="QSO",
            lc_mag_rate_per_day=3.0,
            lc_n_detections=2,
            drb_score=0.99,
        )
        _, assessment = classify_and_assess(alert)
        assert assessment.deviation_sigma > 3.0
        assert not assessment.all_systematics_excluded
        assert assessment.escalate is False
        assert "insufficient_history" in assessment.escalation_reason

    def test_trials_correction_blocks_marginal_outliers_in_big_batches(self) -> None:
        # ~3.5 sigma is exciting in 100 alerts, expected in a million.
        alert = make_gold(
            fink_class="AGN",
            simbad_otype="QSO",
            lc_mag_rate_per_day=0.29,  # z ~= (0.29-0.03)/0.07 ~= 3.7
            lc_amplitude=None,
            lc_n_detections=12,
            drb_score=0.99,
        )
        _, small_batch = classify_and_assess(alert, n_alerts=10)
        _, huge_batch = classify_and_assess(alert, n_alerts=1_000_000)
        assert small_batch.escalate is True
        assert huge_batch.escalate is False
        assert "expected by chance" in huge_batch.escalation_reason

    def test_quiet_event_does_not_escalate(self) -> None:
        _, assessment = classify_and_assess(
            make_gold(lc_mag_rate_per_day=-0.1, lc_amplitude=1.5, simbad_otype="SN")
        )
        assert assessment.escalate is False
        assert "below outlier threshold" in assessment.escalation_reason


class TestSystematics:
    def test_stellar_masquerade_not_excluded_for_extragalactic_class(self) -> None:
        alert = make_gold(is_likely_stellar=True, stellar_evidence="parallax_snr=12")
        _, assessment = classify_and_assess(alert)
        check = next(c for c in assessment.systematics if c.name == "stellar_variability")
        assert check.excluded is False

    def test_bright_star_artifact_flagged(self) -> None:
        alert = make_gold(gaia_g_mag=11.5, gaia_separation_arcsec=1.0)
        _, assessment = classify_and_assess(alert)
        check = next(c for c in assessment.systematics if c.name == "bright_star_artifact")
        assert check.excluded is False
        assert "ghost/spike" in check.note

    def test_faint_or_distant_gaia_source_is_fine(self) -> None:
        alert = make_gold(gaia_g_mag=19.0, gaia_separation_arcsec=1.0)
        _, assessment = classify_and_assess(alert)
        check = next(c for c in assessment.systematics if c.name == "bright_star_artifact")
        assert check.excluded is True

    def test_moving_object_not_excluded_for_solar_system(self) -> None:
        alert = make_gold(fink_class="Solar System MPC")
        _, assessment = classify_and_assess(alert)
        check = next(c for c in assessment.systematics if c.name == "moving_object")
        assert check.excluded is False

    def test_flat_dict_reports_exclusion_summary(self) -> None:
        _, assessment = classify_and_assess(make_gold())
        flat = assessment.to_flat_dict()
        assert "bogus_detection=excluded" in flat["systematics"]
        assert flat["all_systematics_excluded"] == assessment.all_systematics_excluded


def test_config_thresholds_are_respected() -> None:
    # Lower the outlier bar and a mild deviation escalates.
    strict = AnomalySettings(outlier_sigma_threshold=10.0)
    lenient = AnomalySettings(outlier_sigma_threshold=1.0, max_false_alarm_probability=1.0)
    alert = make_gold(
        fink_class="AGN",
        simbad_otype="QSO",
        lc_mag_rate_per_day=0.2,
        lc_amplitude=None,
        lc_n_detections=12,
        drb_score=0.99,
    )
    _, strict_result = classify_and_assess(alert, anomaly_settings=strict)
    _, lenient_result = classify_and_assess(alert, anomaly_settings=lenient, n_alerts=1)
    assert strict_result.escalate is False
    assert lenient_result.escalate is True
