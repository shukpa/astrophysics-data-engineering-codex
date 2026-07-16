"""Tier-1 hot-path baseline classifier (Phase 4, `feat/anomaly-agent`).

Deterministic, LLM-free (architecture rule 1: no LLM calls in the hot path).
Fink's broker classes are the v0 baseline signal; an in-house light-curve
feature model is the documented upgrade path. What this adds over a raw Fink
passthrough is a **classification-confidence framework**: every event gets a
confidence built from evidence *agreement* (real/bogus quality, SIMBAD/CDS
cross-match consistency, the Gaia star/extragalactic discriminator), explicit
alternative classes when the evidence contradicts the label, an anomaly score
(fit quality of the best class), and a follow-up priority.

Escalation invariants (encoded here, consumed by the warm-path agent):
``lens_field_transient`` and ``gw_counterpart_candidate`` events are CRITICAL
regardless of any score.

All heuristic weights below are v0 constants, auditable in one place; they
gate *routing* (what the warm path looks at first), never science claims.
"""

from __future__ import annotations

import math

import structlog

from src.models.alerts import GoldAlert
from src.models.classification import ClassifiedAlert, ClassScore, FollowUpPriority
from src.utils.config import ClassificationSettings, get_settings

logger = structlog.get_logger(__name__)

CLASSIFIER_VERSION = "baseline-v0"


class ClassBaseline:
    """Expected light-curve behaviour for a class (v0 priors).

    ``rate`` and ``amplitude`` are (mean, sigma) priors on
    |mag rate per day| and light-curve amplitude in magnitudes. These are
    deliberately coarse, order-of-magnitude priors for *routing* — they gate
    what the warm path looks at, never science claims — and are the
    designated replacement point for fitted population statistics.
    """

    def __init__(
        self, description: str, rate: tuple[float, float], amplitude: tuple[float, float]
    ) -> None:
        self.description = description
        self.rate = rate
        self.amplitude = amplitude


#: v0 class baselines. Keys match Fink broker classes; DEFAULT covers the rest.
CLASS_BASELINES: dict[str, ClassBaseline] = {
    "SN candidate": ClassBaseline(
        "Supernovae typically evolve at ~0.03-0.3 mag/day with amplitudes of " "1-3 mag over weeks",
        rate=(0.1, 0.15),
        amplitude=(1.5, 1.0),
    ),
    "Early SN Ia candidate": ClassBaseline(
        "Early SNe Ia rise at ~0.1-0.5 mag/day toward peak over ~2-3 weeks",
        rate=(0.25, 0.2),
        amplitude=(1.5, 1.0),
    ),
    "Kilonova candidate": ClassBaseline(
        "Kilonovae decline fast, ~0.3-1 mag/day, fading within days",
        rate=(0.5, 0.3),
        amplitude=(2.0, 1.0),
    ),
    "AGN": ClassBaseline(
        "AGN vary stochastically and slowly, typically <0.1 mag/day with "
        "amplitudes under ~1 mag on month timescales",
        rate=(0.03, 0.07),
        amplitude=(0.5, 0.5),
    ),
    "QSO": ClassBaseline(
        "QSOs vary stochastically and slowly, typically <0.1 mag/day",
        rate=(0.03, 0.07),
        amplitude=(0.5, 0.5),
    ),
    "Variable Star": ClassBaseline(
        "Periodic/semi-regular variables span large rate ranges but repeat; "
        "amplitudes usually under ~2 mag",
        rate=(0.2, 0.4),
        amplitude=(0.8, 0.7),
    ),
    "Cataclysmic Variable": ClassBaseline(
        "CV outbursts brighten by 2-6 mag within ~a day, then decline over days",
        rate=(0.8, 0.6),
        amplitude=(3.0, 1.5),
    ),
    "Microlensing candidate": ClassBaseline(
        "Microlensing events are smooth, achromatic, single-peaked brightenings "
        "over days-months",
        rate=(0.15, 0.2),
        amplitude=(1.0, 0.8),
    ),
    "DEFAULT": ClassBaseline(
        "No class-specific baseline; generic transient prior",
        rate=(0.15, 0.3),
        amplitude=(1.0, 1.0),
    ),
}


def feature_deviation_sigma(alert: GoldAlert, baseline: ClassBaseline) -> tuple[float, list[str]]:
    """Largest z-score of available light-curve features vs a class baseline.

    Shared by the hot-path anomaly score and the warm-path agent's rigor
    field 2, so routing and assessment always agree on the deviation.
    """
    deviations: list[float] = []
    notes: list[str] = []

    if alert.lc_mag_rate_per_day is not None:
        mu, sigma = baseline.rate
        z = abs(abs(alert.lc_mag_rate_per_day) - mu) / sigma
        deviations.append(z)
        notes.append(f"|rate| {abs(alert.lc_mag_rate_per_day):.2f} mag/day ({z:.1f} sigma)")
    if alert.lc_amplitude is not None:
        mu, sigma = baseline.amplitude
        z = abs(alert.lc_amplitude - mu) / sigma
        deviations.append(z)
        notes.append(f"amplitude {alert.lc_amplitude:.2f} mag ({z:.1f} sigma)")

    return (max(deviations) if deviations else 0.0, notes)


#: Fink classes implying a Galactic/stellar origin (consistent with a
#: significant Gaia parallax or proper motion).
STELLAR_CLASSES = frozenset(
    {"Variable Star", "Cataclysmic Variable", "YSO", "Microlensing candidate"}
)

#: Fink classes implying an extragalactic origin (a significant Gaia parallax
#: or proper motion *contradicts* these).
EXTRAGALACTIC_CLASSES = frozenset(
    {"SN candidate", "Early SN Ia candidate", "SN Ia", "SN II", "Kilonova candidate", "AGN", "QSO"}
)

#: Solar-system classes: moving objects, astrometry checks do not apply.
SOLAR_SYSTEM_CLASSES = frozenset({"Solar System MPC", "Solar System candidate"})

#: Labels that mean "the broker has no opinion".
_UNKNOWN_LABELS = frozenset({"", "Unknown", "unknown", "null", "None"})


def simbad_category(otype: str | None) -> str | None:
    """Map a SIMBAD otype to a coarse category for consistency checks.

    Returns "stellar", "extragalactic", or None (no opinion). The mapping is
    deliberately coarse — it only feeds agreement/contradiction scoring,
    never a class label directly.
    """
    if not otype:
        return None
    o = otype.strip()
    extragalactic = {"G", "GiG", "GiC", "AGN", "QSO", "Sy1", "Sy2", "SyG", "BLL", "Bla", "SN"}
    if o in extragalactic or o.startswith(("SN", "QSO", "AGN", "G_")):
        return "extragalactic"
    # SIMBAD stellar otypes: "*" anywhere is star-ish ("V*", "RR*", "Ma*",
    # "CV*", "No*", "*iC" ...); plus a few common named ones.
    if "*" in o or o in {"YSO", "Mira", "Nova", "Star", "EB"}:
        return "stellar"
    return None


def fink_category(fink_class: str | None) -> str | None:
    """Coarse category of a Fink class ("stellar"/"extragalactic"/None)."""
    if fink_class in STELLAR_CLASSES:
        return "stellar"
    if fink_class in EXTRAGALACTIC_CLASSES:
        return "extragalactic"
    return None


class BaselineClassifier:
    """Hot-path classification-confidence framework over gold alerts.

    Pure function of the gold row + config — no network, no LLM, no state.

    Args:
        classification_settings: Thresholds and class-priority lists;
            defaults to the global settings.
    """

    def __init__(self, classification_settings: ClassificationSettings | None = None) -> None:
        self._config = classification_settings or get_settings().classification

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, alert: GoldAlert) -> ClassifiedAlert:
        """Classify one gold alert.

        Returns a :class:`ClassifiedAlert` with primary class, confidence,
        alternatives, anomaly score, and follow-up priority.
        """
        primary = self._primary_class(alert)
        confidence, alternatives = self._confidence_and_alternatives(alert, primary)
        anomaly_score = self._anomaly_score(alert, primary, confidence)
        priority, reason = self._priority(alert, primary, anomaly_score)

        return ClassifiedAlert(
            object_id=alert.object_id,
            candidate_id=alert.candidate_id,
            primary_class=primary,
            confidence=round(confidence, 3),
            alternatives=alternatives,
            anomaly_score=round(anomaly_score, 3),
            follow_up_priority=priority,
            priority_reason=reason,
            classifier_version=CLASSIFIER_VERSION,
            gold_processing_id=alert.gold_processing_id,
            raw_payload_hash=alert.raw_payload_hash,
        )

    def classify_batch(self, alerts: list[GoldAlert]) -> list[ClassifiedAlert]:
        """Classify a batch of gold alerts (order preserved)."""
        results = [self.classify(alert) for alert in alerts]
        counts: dict[str, int] = {}
        for r in results:
            counts[r.follow_up_priority.value] = counts.get(r.follow_up_priority.value, 0) + 1
        logger.info("classified_batch", total=len(results), by_priority=counts)
        return results

    # ------------------------------------------------------------------
    # Internals (v0 heuristics — auditable, deterministic)
    # ------------------------------------------------------------------

    def _primary_class(self, alert: GoldAlert) -> str:
        fink = (alert.fink_class or "").strip()
        if fink and fink not in _UNKNOWN_LABELS:
            return fink
        return "Unknown"

    def _confidence_and_alternatives(
        self, alert: GoldAlert, primary: str
    ) -> tuple[float, list[ClassScore]]:
        """Build confidence from evidence agreement; alternatives from conflict."""
        alternatives: dict[str, float] = {}
        confidence = 0.5 if primary != "Unknown" else 0.2

        # Detection quality (deep-learning real/bogus preferred).
        quality = alert.drb_score if alert.drb_score is not None else alert.rb_score
        if quality is not None:
            confidence += 0.15 * (quality - 0.5) * 2  # maps 0.5→0, 1.0→+0.15

        cat = fink_category(primary)

        # Gaia star/extragalactic discriminator vs the class.
        if alert.is_likely_stellar is True:
            if cat == "extragalactic":
                confidence -= 0.25
                alternatives["Variable Star"] = 0.4
            elif cat == "stellar":
                confidence += 0.10
            elif primary == "Unknown":
                alternatives["Variable Star"] = 0.35
        elif alert.is_likely_stellar is False and cat == "extragalactic":
            confidence += 0.05  # astrometry consistent with extragalactic

        # SIMBAD otype vs the class.
        simbad_cat = simbad_category(alert.simbad_otype)
        if simbad_cat is not None and cat is not None:
            if simbad_cat == cat:
                confidence += 0.15
            else:
                confidence -= 0.20
                if simbad_cat == "extragalactic" and primary not in ("AGN", "QSO"):
                    alternatives["AGN"] = max(alternatives.get("AGN", 0.0), 0.35)
                if simbad_cat == "stellar":
                    alternatives["Variable Star"] = max(alternatives.get("Variable Star", 0.0), 0.4)
        elif simbad_cat is not None and primary == "Unknown":
            proposal = "AGN" if simbad_cat == "extragalactic" else "Variable Star"
            alternatives[proposal] = max(alternatives.get(proposal, 0.0), 0.35)

        # Solar-system objects: astrometric checks do not apply, but the class
        # itself is usually secure (MPC = catalogued minor planet).
        if primary in SOLAR_SYSTEM_CLASSES:
            confidence += 0.15 if primary == "Solar System MPC" else 0.05

        confidence = max(0.05, min(0.99, confidence))
        ranked = sorted(alternatives.items(), key=lambda kv: kv[1], reverse=True)
        return confidence, [ClassScore(label=k, score=v) for k, v in ranked]

    def _anomaly_score(self, alert: GoldAlert, primary: str, confidence: float) -> float:
        """Fit quality of the best class: 0 = well explained, 1 = unexplained.

        Two components, whichever is worse: evidence disagreement
        (1 - confidence) and light-curve deviation from the class baseline,
        mapped through a saturating 1 - exp(-sigma/4) so ~4.8 sigma of
        feature deviation alone crosses the default warm-path threshold.
        Moving objects are exempt from the feature term (apparent rates are
        dominated by motion, not intrinsic behaviour).
        """
        evidence_component = 1.0 - confidence
        feature_component = 0.0
        if primary not in SOLAR_SYSTEM_CLASSES:
            baseline = CLASS_BASELINES.get(primary, CLASS_BASELINES["DEFAULT"])
            deviation, _ = feature_deviation_sigma(alert, baseline)
            feature_component = 1.0 - math.exp(-deviation / 4.0)
        return max(0.0, min(1.0, max(evidence_component, feature_component)))

    def _priority(
        self, alert: GoldAlert, primary: str, anomaly_score: float
    ) -> tuple[FollowUpPriority, str]:
        # Flag-driven CRITICAL, regardless of any ML score (plan rule).
        if alert.lens_field_transient:
            return (
                FollowUpPriority.CRITICAL,
                f"lens_field_transient: within lens field of {alert.lens_name or 'unknown lens'}"
                " (time-delay cosmography channel; always escalates)",
            )
        # Phase 5 adds the GW counterpart flag to GoldAlert; tolerate its
        # absence so this rule activates automatically when the field lands.
        if bool(getattr(alert, "gw_counterpart_candidate", False)):
            return (
                FollowUpPriority.CRITICAL,
                "gw_counterpart_candidate: possible GW optical counterpart"
                " (time-critical; always escalates)",
            )
        if anomaly_score >= self._config.anomaly_score_threshold:
            return (
                FollowUpPriority.CRITICAL,
                f"anomaly_score {anomaly_score:.2f} >= "
                f"{self._config.anomaly_score_threshold} (potentially new/anomalous)",
            )
        if primary in self._config.high_priority_classes:
            return (
                FollowUpPriority.HIGH,
                f"{primary}: scientifically valuable known type",
            )
        if primary in self._config.low_priority_classes:
            return (FollowUpPriority.LOW, f"{primary}: well-characterised known type")
        return (
            FollowUpPriority.MEDIUM,
            f"{primary}: interesting but not urgent; nightly review",
        )
