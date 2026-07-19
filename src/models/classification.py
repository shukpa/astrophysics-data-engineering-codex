"""Pydantic models for Tier-1 classification and warm-path anomaly assessment.

Phase 4 (`feat/anomaly-agent`) contracts:

* :class:`ClassifiedAlert` — output of the hot-path baseline classifier.
  Every classified event carries a primary class, a confidence in [0, 1],
  alternative classes with scores, an anomaly score (fit quality of the best
  class), and a follow-up priority.
* :class:`AnomalyAssessment` — output of the warm-path anomaly agent. Every
  flag carries the **four mandatory statistical-rigor fields** from
  ``SCIENCE_GOALS.md`` (Methodology): baseline comparison, deviation in sigma,
  trials-corrected false-alarm probability, and known-systematic exclusion.

Escalation rule (encoded in :class:`FollowUpPriority` and enforced by the
classifier): ``lens_field_transient`` and ``gw_counterpart_candidate`` events
are CRITICAL **regardless of any ML score**.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models.alerts import _utcnow


class FollowUpPriority(StrEnum):
    """Follow-up priority for a classified event.

    Taxonomy (from the Phase 4 planning config, now the code home):

    * CRITICAL — a flagged lens-field/GW counterpart event; requires
      immediate human review and always escalates.
    * HIGH — scientifically valuable known type or a high-anomaly-score
      event awaiting the warm-path rigor check; follow-up recommended.
    * MEDIUM — interesting but not urgent; queue for nightly review.
    * LOW — well-characterised known type; archive only.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def rank(self) -> int:
        """Numeric rank (higher = more urgent) for sorting and thresholds."""
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}[self.value]

    def at_least(self, other: FollowUpPriority) -> bool:
        """True when this priority is at or above ``other``."""
        return self.rank >= other.rank


class ClassScore(BaseModel):
    """A candidate class with its score."""

    model_config = ConfigDict(extra="forbid")

    label: str
    score: float = Field(..., ge=0.0, le=1.0)


class ClassifiedAlert(BaseModel):
    """Hot-path classification result for one gold alert.

    Deterministic and LLM-free (architecture rule 1). Provenance pointers
    trace back through gold to the source alert.

    Attributes:
        object_id: ZTF/source object identifier.
        candidate_id: Alert candidate identifier, when present.
        primary_class: Best class label (Fink broker class as v0 baseline).
        confidence: Confidence in the primary class, [0, 1].
        alternatives: Other plausible classes with scores, best first.
        anomaly_score: How poorly the best class explains the event, [0, 1]
            (0 = well explained, 1 = unexplained). Drives warm-path handoff.
        follow_up_priority: CRITICAL / HIGH / MEDIUM / LOW.
        priority_reason: Why that priority was assigned (auditable).
        classifier_version: Version tag of the classifier that produced this.
    """

    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(..., min_length=3)
    candidate_id: int | None = None
    primary_class: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    alternatives: list[ClassScore] = Field(default_factory=list)
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    follow_up_priority: FollowUpPriority
    priority_reason: str
    classifier_version: str
    classified_at: datetime = Field(default_factory=_utcnow)

    # Provenance pointers
    gold_processing_id: str | None = None
    raw_payload_hash: str | None = None

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary for Parquet-compatible storage."""
        flat = self.model_dump(mode="json", exclude={"alternatives"})
        flat["alternatives"] = "; ".join(f"{a.label}={a.score:.2f}" for a in self.alternatives)
        return flat


class SystematicCheck(BaseModel):
    """One known-systematic exclusion check.

    ``excluded=True`` means the systematic has been ruled out as the
    explanation; ``False`` means it remains a plausible cause (which blocks
    a genuine-anomaly escalation).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    excluded: bool
    note: str


class AnomalyAssessment(BaseModel):
    """Warm-path structured assessment of a flagged event.

    Carries the four mandatory statistical-rigor fields from
    ``SCIENCE_GOALS.md``. An event may only be escalated as a *genuine
    anomaly candidate* when the deviation is significant, the
    trials-corrected false-alarm probability is low, and every known
    systematic is excluded — with the single exception of CRITICAL-priority
    events (lens-field / GW counterpart hits), which always escalate to
    human review regardless of these statistics.

    Attributes:
        baseline_comparison: Expected behaviour of the most likely class,
            stated explicitly (rigor field 1).
        deviation_sigma: Largest deviation of the event's measured features
            from that baseline, in sigma (rigor field 2).
        false_alarm_probability: Probability of at least one such deviation
            arising by chance given ``n_alerts_processed`` trials
            (rigor field 3).
        systematics: Known-systematic exclusion checklist (rigor field 4).
        escalate: Whether this event goes to human review.
        escalation_reason: Auditable justification for the escalation state.
    """

    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(..., min_length=3)
    candidate_id: int | None = None
    primary_class: str
    follow_up_priority: FollowUpPriority

    # The four mandatory rigor fields (SCIENCE_GOALS.md, Methodology).
    baseline_comparison: str
    deviation_sigma: float = Field(..., ge=0.0)
    false_alarm_probability: float = Field(..., ge=0.0, le=1.0)
    systematics: list[SystematicCheck]

    n_alerts_processed: int = Field(..., ge=1)
    escalate: bool
    escalation_reason: str
    agent_version: str
    assessed_at: datetime = Field(default_factory=_utcnow)

    # Provenance pointers
    gold_processing_id: str | None = None
    raw_payload_hash: str | None = None

    @property
    def all_systematics_excluded(self) -> bool:
        """True when every known systematic has been ruled out."""
        return all(check.excluded for check in self.systematics)

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary for Parquet-compatible storage."""
        flat = self.model_dump(mode="json", exclude={"systematics"})
        flat["systematics"] = "; ".join(
            f"{c.name}={'excluded' if c.excluded else 'NOT-excluded'}" for c in self.systematics
        )
        flat["all_systematics_excluded"] = self.all_systematics_excluded
        return flat
