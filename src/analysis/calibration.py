"""Temporal replay and calibration metrics for the deterministic classifier.

The metrics here are deliberately descriptive. They quantify routing behaviour
on labelled replay sets; they do not turn the current heuristic anomaly score
or Gaussian false-alarm calculation into a scientifically calibrated claim.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models.alerts import GoldAlert
from src.models.classification import FollowUpPriority
from src.processing.classifier import BaselineClassifier


class LabelledGoldAlert(BaseModel):
    """A gold alert paired with independently supplied replay labels."""

    model_config = ConfigDict(extra="forbid")

    alert: GoldAlert
    truth_class: str = Field(..., min_length=1)
    truth_is_rare: bool = False
    label_source: str = Field(..., min_length=1)
    tns_id: str | None = None


def coarse_class(label: str | None) -> str:
    """Map broker or spectroscopic labels to a comparable coarse family."""
    value = (label or "").strip().lower()
    if not value or value in {"unknown", "ambiguous"}:
        return "unknown"
    if "kilonova" in value or value in {"kn candidate", "kn"}:
        return "kilonova"
    if value.startswith("sn") or "supernova" in value or "slsn" in value:
        return "supernova"
    if "tde" in value:
        return "tde"
    if value in {"agn", "qso"}:
        return "active_galaxy"
    if any(term in value for term in ("variable", "cataclysmic", "yso", "lbv", "nova")):
        return "galactic_variable"
    if "solar system" in value or "asteroid" in value:
        return "solar_system"
    if "microlensing" in value:
        return "microlensing"
    return "other"


def select_object_disjoint_records(
    records: list[LabelledGoldAlert],
    *,
    split_date: str,
) -> tuple[list[LabelledGoldAlert], dict[str, Any]]:
    """Keep crossing objects only in the post-split evaluation cohort.

    Earlier photometry may still inform a later alert's features, as it would
    at inference time, but pre-split predictions for a crossing object are
    excluded so the object never appears in both reported cohorts.
    """
    cutoff = date.fromisoformat(split_date)
    splits: dict[str, set[str]] = {}
    for record in records:
        observed = date.fromisoformat(record.alert.observation_date)
        split = "train" if observed < cutoff else "validation"
        splits.setdefault(record.alert.object_id, set()).add(split)

    crossing = sorted(object_id for object_id, values in splits.items() if len(values) > 1)
    crossing_set = set(crossing)
    selected = [
        record
        for record in records
        if record.alert.object_id not in crossing_set
        or date.fromisoformat(record.alert.observation_date) >= cutoff
    ]
    return selected, {
        "cross_split_objects": crossing,
        "alerts_excluded_for_disjoint_split": len(records) - len(selected),
        "cross_split_policy": "validation_only",
    }


def evaluate_replay(
    records: list[LabelledGoldAlert],
    *,
    split_date: str,
    classifier: BaselineClassifier | None = None,
) -> dict[str, Any]:
    """Evaluate labelled alerts with an object-disjoint temporal split.

    Alerts before ``split_date`` are training-era diagnostics; alerts on or
    after it are holdout diagnostics. An object crossing the split is rejected
    to prevent light-curve history leaking into both sides.
    """
    cutoff = date.fromisoformat(split_date)
    object_splits: dict[str, str] = {}
    predictions: list[dict[str, Any]] = []
    active_classifier = classifier or BaselineClassifier()

    for record in records:
        observed = date.fromisoformat(record.alert.observation_date)
        split = "train" if observed < cutoff else "validation"
        previous = object_splits.setdefault(record.alert.object_id, split)
        if previous != split:
            raise ValueError(
                f"Object {record.alert.object_id} crosses temporal split {split_date}; "
                "use object-disjoint replay data."
            )

        classified = active_classifier.classify(record.alert)
        truth_family = coarse_class(record.truth_class)
        predicted_family = coarse_class(classified.primary_class)
        flagged = (
            classified.follow_up_priority is FollowUpPriority.CRITICAL
            or classified.anomaly_score >= active_classifier.anomaly_score_threshold
        )
        predictions.append(
            {
                "split": split,
                "object_id": record.alert.object_id,
                "candidate_id": record.alert.candidate_id,
                "observation_date": record.alert.observation_date,
                "tns_id": record.tns_id,
                "truth_class": record.truth_class,
                "truth_family": truth_family,
                "truth_is_rare": record.truth_is_rare,
                "label_source": record.label_source,
                "predicted_class": classified.primary_class,
                "predicted_family": predicted_family,
                "confidence": classified.confidence,
                "anomaly_score": classified.anomaly_score,
                "follow_up_priority": classified.follow_up_priority.value,
                "flagged_for_review": flagged,
                "gold_processing_id": record.alert.gold_processing_id,
                "raw_payload_hash": record.alert.raw_payload_hash,
            }
        )

    return {
        "split_date": split_date,
        "metrics": {
            split: _split_metrics([row for row in predictions if row["split"] == split])
            for split in ("train", "validation")
        },
        "predictions": predictions,
        "interpretation": (
            "Routing diagnostics only: truth_is_rare denotes an independently labelled "
            "review target, not a claim of physical anomaly or calibrated false-alarm probability."
        ),
    }


def _split_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [
        row
        for row in rows
        if row["truth_family"] != "unknown" and row["predicted_family"] != "unknown"
    ]
    correct = sum(row["truth_family"] == row["predicted_family"] for row in comparable)
    true_positive = sum(row["truth_is_rare"] and row["flagged_for_review"] for row in rows)
    false_positive = sum(not row["truth_is_rare"] and row["flagged_for_review"] for row in rows)
    false_negative = sum(row["truth_is_rare"] and not row["flagged_for_review"] for row in rows)
    true_negative = sum(not row["truth_is_rare"] and not row["flagged_for_review"] for row in rows)

    return {
        "alerts": len(rows),
        "objects": len({row["object_id"] for row in rows}),
        "classification_comparable": len(comparable),
        "classification_correct": correct,
        "classification_accuracy": correct / len(comparable) if comparable else None,
        "rare_review_targets": sum(row["truth_is_rare"] for row in rows),
        "flagged_for_review": sum(row["flagged_for_review"] for row in rows),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else None
        ),
        "recall": (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else None
        ),
        "false_positive_rate": (
            false_positive / (false_positive + true_negative)
            if false_positive + true_negative
            else None
        ),
    }
