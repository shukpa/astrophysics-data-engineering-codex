"""Warm-path anomaly agent (Phase 4, `feat/anomaly-agent`).

WARM PATH ONLY. The hot path (bronze → silver → gold → classifier) never
calls this module per alert-stream volume; the agent runs on the *flagged*
subset the classifier hands over (CRITICAL priority or anomaly score above
threshold). Architecture rule 1 is stricter still: **this v0 agent makes no
LLM calls at all** — it is a deterministic statistical assessor, and the repo
stays provider-neutral. If an operator later selects an LLM runtime, it slots
in *behind* this assessment as an additional narrative layer (see
``config/default.yaml`` → ``llm_runtime`` placeholders); the four rigor
fields below remain mandatory either way.

Every assessment carries the four statistical-rigor fields required by
``SCIENCE_GOALS.md`` (Methodology):

1. **Baseline comparison** — expected behaviour of the most likely class.
2. **Deviation in sigma** — measured features vs that baseline.
3. **False-alarm probability** — trials-corrected for the number of alerts
   processed (an outlier among a million alerts is expected, not exciting).
4. **Known-systematic exclusion** — explicit checklist; an unexcluded
   systematic blocks a genuine-anomaly escalation.

Escalation rule: CRITICAL-priority events (every ``lens_field_transient``
hit, every ``gw_counterpart_candidate``) always escalate to human review
regardless of these statistics. Single anomalous light curves are, with
overwhelming prior, instrumental → astrophysical → only then anything exotic
(the plan's convergence rule); the agent flags weirdness agnostically and
leaves hypothesis testing to the constraint notebooks.
"""

from __future__ import annotations

import math

import structlog

from src.models.alerts import GoldAlert
from src.models.classification import (
    AnomalyAssessment,
    ClassifiedAlert,
    FollowUpPriority,
    SystematicCheck,
)
from src.processing.classifier import (
    CLASS_BASELINES,
    SOLAR_SYSTEM_CLASSES,
    STELLAR_CLASSES,
    feature_deviation_sigma,
)
from src.utils.config import AnomalySettings, get_settings

logger = structlog.get_logger(__name__)

AGENT_VERSION = "deterministic-v0"


def _two_sided_p(z: float) -> float:
    """Two-sided Gaussian tail probability for a z-score."""
    return math.erfc(z / math.sqrt(2.0))


def trials_corrected_fap(p_single: float, n_trials: int) -> float:
    """FAP for >=1 chance occurrence among ``n_trials`` independent looks.

    1 - (1 - p)^N, computed stably for small p / large N.
    """
    p = min(max(p_single, 0.0), 1.0)
    if p >= 1.0:
        return 1.0
    return float(min(1.0, -math.expm1(n_trials * math.log1p(-p))))


class AnomalyAgent:
    """Deterministic warm-path assessor producing the four rigor fields."""

    def __init__(self, anomaly_settings: AnomalySettings | None = None) -> None:
        self._config = anomaly_settings or get_settings().anomaly

    def assess(
        self,
        alert: GoldAlert,
        classification: ClassifiedAlert,
        *,
        n_alerts_processed: int,
    ) -> AnomalyAssessment:
        """Assess one flagged event.

        Args:
            alert: The gold row for the event.
            classification: The hot-path classification result.
            n_alerts_processed: Number of alerts processed in the batch/night
                this event was flagged from — the trials term for the FAP.
        """
        baseline = CLASS_BASELINES.get(classification.primary_class, CLASS_BASELINES["DEFAULT"])
        deviation, feature_notes = feature_deviation_sigma(alert, baseline)
        p_single = _two_sided_p(deviation)
        fap = trials_corrected_fap(p_single, max(1, n_alerts_processed))
        systematics = self._systematics_checklist(alert, classification)
        all_excluded = all(c.excluded for c in systematics)

        measured = "; ".join(feature_notes) or "no usable light-curve features"
        baseline_comparison = f"{baseline.description}. Measured: {measured}."

        escalate, reason = self._escalation(
            alert, classification, deviation, fap, all_excluded, systematics
        )

        assessment = AnomalyAssessment(
            object_id=alert.object_id,
            candidate_id=alert.candidate_id,
            primary_class=classification.primary_class,
            follow_up_priority=classification.follow_up_priority,
            baseline_comparison=baseline_comparison,
            deviation_sigma=round(deviation, 2),
            false_alarm_probability=round(fap, 6),
            systematics=systematics,
            n_alerts_processed=max(1, n_alerts_processed),
            escalate=escalate,
            escalation_reason=reason,
            agent_version=AGENT_VERSION,
            gold_processing_id=alert.gold_processing_id,
            raw_payload_hash=alert.raw_payload_hash,
        )
        logger.info(
            "anomaly_assessed",
            object_id=alert.object_id,
            deviation_sigma=assessment.deviation_sigma,
            fap=assessment.false_alarm_probability,
            escalate=escalate,
        )
        return assessment

    # ------------------------------------------------------------------
    # Rigor fields
    # ------------------------------------------------------------------

    def _systematics_checklist(
        self, alert: GoldAlert, classification: ClassifiedAlert
    ) -> list[SystematicCheck]:
        """Explicit known-systematic exclusion checks (rigor field 4)."""
        checks: list[SystematicCheck] = []

        quality = alert.drb_score if alert.drb_score is not None else alert.rb_score
        checks.append(
            SystematicCheck(
                name="bogus_detection",
                excluded=quality is not None and quality >= 0.9,
                note=(
                    f"real/bogus score {quality:.2f}" if quality is not None else "no rb/drb score"
                ),
            )
        )

        is_moving = classification.primary_class in SOLAR_SYSTEM_CLASSES or (
            (alert.cds_xmatch or "").lower().startswith(("solar", "mpc"))
        )
        checks.append(
            SystematicCheck(
                name="moving_object",
                excluded=not is_moving,
                note=(
                    "classified/cross-matched as solar-system object"
                    if is_moving
                    else "no solar-system association"
                ),
            )
        )

        stellar_masquerade = (
            alert.is_likely_stellar is True and classification.primary_class not in STELLAR_CLASSES
        )
        checks.append(
            SystematicCheck(
                name="stellar_variability",
                excluded=not stellar_masquerade,
                note=(
                    f"Gaia astrometry says stellar ({alert.stellar_evidence})"
                    if stellar_masquerade
                    else "no stellar-origin contradiction"
                ),
            )
        )

        checks.append(
            SystematicCheck(
                name="insufficient_history",
                excluded=alert.lc_n_detections >= self._config.minimum_detections_for_analysis,
                note=(
                    f"{alert.lc_n_detections} detections "
                    f"(minimum {self._config.minimum_detections_for_analysis})"
                ),
            )
        )

        bright_neighbour = (
            alert.gaia_g_mag is not None
            and alert.gaia_g_mag <= 13.0
            and (alert.gaia_separation_arcsec or 0.0) <= 3.0
        )
        checks.append(
            SystematicCheck(
                name="bright_star_artifact",
                excluded=not bright_neighbour,
                note=(
                    f"Gaia G={alert.gaia_g_mag:.1f} source within "
                    f"{alert.gaia_separation_arcsec:.1f} arcsec (ghost/spike risk)"
                    if bright_neighbour
                    else "no bright Gaia source coincident"
                ),
            )
        )

        return checks

    def _escalation(
        self,
        alert: GoldAlert,
        classification: ClassifiedAlert,
        deviation: float,
        fap: float,
        all_excluded: bool,
        systematics: list[SystematicCheck],
    ) -> tuple[bool, str]:
        """Apply the escalation rule.

        The statistical verdict is evaluated first, so an event that earns
        escalation on its own merits carries the informative reason. The
        unconditional-escalation rule applies to *flag-driven* CRITICAL
        events (every ``lens_field_transient`` hit, every
        ``gw_counterpart_candidate``) — those are externally triggered and
        time-critical, and no ML score or statistic may veto them. A
        CRITICAL assigned purely for a high anomaly *score* is exactly the
        kind of ML verdict the rigor gate exists to check, so it does NOT
        bypass the statistics: with an unexcluded systematic or an
        uninteresting FAP it stays in the report, unescalated, with the
        blocking reason on record.
        """
        failed = [c.name for c in systematics if not c.excluded]
        if (
            deviation >= self._config.outlier_sigma_threshold
            and fap <= self._config.max_false_alarm_probability
            and all_excluded
        ):
            return (
                True,
                f"genuine anomaly candidate: {deviation:.1f} sigma deviation, "
                f"trials-corrected FAP {fap:.2e}, all known systematics excluded",
            )
        flag_driven = alert.lens_field_transient or bool(
            getattr(alert, "gw_counterpart_candidate", False)
        )
        if flag_driven and classification.follow_up_priority is FollowUpPriority.CRITICAL:
            return (
                True,
                f"CRITICAL priority always escalates to human review "
                f"({classification.priority_reason})",
            )
        if deviation >= self._config.outlier_sigma_threshold and not all_excluded:
            return (
                False,
                f"{deviation:.1f} sigma deviation but unexcluded systematics: "
                f"{', '.join(failed)} — instrumental/astrophysical explanations first",
            )
        if deviation >= self._config.outlier_sigma_threshold:
            return (
                False,
                f"{deviation:.1f} sigma deviation but trials-corrected FAP {fap:.2e} "
                f"exceeds {self._config.max_false_alarm_probability} "
                f"(expected by chance in this volume)",
            )
        return (
            False,
            f"deviation {deviation:.1f} sigma below outlier threshold "
            f"{self._config.outlier_sigma_threshold}",
        )
