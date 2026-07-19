"""Generate the AGD nightly report from a gold Parquet batch.

Phase 4 deliverable: classify every gold row (hot path, deterministic), run
the warm-path anomaly agent on the flagged subset, and emit a Markdown report
plus machine-readable outputs (JSON summary, classifications + assessments
Parquet). The report carries the system-metrics section required by
``SCIENCE_GOALS.md``: processing latency, classification counts and a
known-type agreement proxy, anomaly false-alarm tracking, and cross-match
completeness.

Usage (after a gold run, e.g. the smoke script):

    python scripts/nightly_report.py --gold-path data/smoke/gold/alerts
    python scripts/nightly_report.py --gold-path data/gold/alerts \
        --observation-date 2026-07-19 --top-n 10
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.agents.anomaly_agent import AnomalyAgent
from src.crossref.utils import none_if_nan
from src.models.alerts import GoldAlert
from src.models.classification import AnomalyAssessment, ClassifiedAlert, FollowUpPriority
from src.processing.classifier import BaselineClassifier, fink_category, simbad_category
from src.utils.config import (
    AnomalySettings,
    ClassificationSettings,
    ReportSettings,
    get_settings,
)


def load_gold_alerts(
    gold_path: Path,
    *,
    observation_date: str | None = None,
    gold_processing_id: str | None = None,
) -> list[GoldAlert]:
    """Load gold rows from a Parquet file or directory into typed models.

    Parquet round-trips absent optional values as NaN; those are cleaned to
    None before Pydantic validation (same convention as the lens reader).
    """
    if gold_path.is_dir() and not any(gold_path.rglob("*.parquet")):
        return []
    # Read the dataset root (file OR directory) in one call so pyarrow
    # reconstructs hive-partition columns (gold is partitioned on
    # observation_date — reading files individually would drop it).
    filters = []
    if observation_date is not None:
        filters.append(("observation_date", "=", observation_date))
    if gold_processing_id is not None:
        filters.append(("gold_processing_id", "=", gold_processing_id))
    df = pd.read_parquet(gold_path, filters=filters or None)

    if gold_path.is_dir() and not filters and "observation_date" in df.columns:
        observation_dates = set(df["observation_date"].dropna().astype(str))
        if len(observation_dates) > 1:
            raise ValueError(
                "Gold dataset spans multiple observation dates; pass observation_date "
                "or gold_processing_id to scope the nightly report."
            )
    alerts: list[GoldAlert] = []
    for record in df.to_dict("records"):
        cleaned = {key: none_if_nan(value) for key, value in record.items()}
        alerts.append(GoldAlert(**cleaned))
    return alerts


def _latency_seconds(alert: GoldAlert) -> float | None:
    """End-to-end pipeline latency: ingestion -> gold timestamp, seconds."""
    try:
        return (alert.gold_timestamp - alert.ingestion_timestamp).total_seconds()
    except TypeError:
        return None


def compute_metrics(
    alerts: list[GoldAlert],
    classifications: list[ClassifiedAlert],
    assessments: list[AnomalyAssessment],
) -> dict[str, Any]:
    """System metrics (SCIENCE_GOALS.md Metrics + plan Phase 4 item 4)."""
    total = len(alerts)

    latencies = [s for a in alerts if (s := _latency_seconds(a)) is not None and s >= 0]
    latency = {
        "mean_seconds": round(statistics.mean(latencies), 3) if latencies else None,
        "median_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "max_seconds": round(max(latencies), 3) if latencies else None,
    }

    by_class: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for c in classifications:
        by_class[c.primary_class] = by_class.get(c.primary_class, 0) + 1
        by_priority[c.follow_up_priority.value] = by_priority.get(c.follow_up_priority.value, 0) + 1

    # Known-type agreement proxy: where both the broker class and the SIMBAD
    # otype imply a coarse category, how often do they agree? An honest v0
    # accuracy stand-in — the classifier is a Fink passthrough baseline, so
    # self-agreement would be meaningless.
    comparable = 0
    agreeing = 0
    for a in alerts:
        f_cat = fink_category(a.fink_class)
        s_cat = simbad_category(a.simbad_otype)
        if f_cat is not None and s_cat is not None:
            comparable += 1
            if f_cat == s_cat:
                agreeing += 1
    agreement = round(agreeing / comparable, 3) if comparable else None

    mean_confidence = (
        round(statistics.mean(c.confidence for c in classifications), 3)
        if classifications
        else None
    )

    faps = [x.false_alarm_probability for x in assessments]
    anomaly_tracking = {
        "flagged_for_warm_path": len(assessments),
        "escalated": sum(1 for x in assessments if x.escalate),
        "blocked_by_systematics": sum(
            1 for x in assessments if not x.escalate and not x.all_systematics_excluded
        ),
        "median_fap": round(statistics.median(faps), 6) if faps else None,
        "min_fap": round(min(faps), 6) if faps else None,
    }

    crossmatch = {
        "gaia_matched_fraction": (
            round(sum(1 for a in alerts if a.gaia_source_id is not None) / total, 3)
            if total
            else None
        ),
        "simbad_matched_fraction": (
            round(sum(1 for a in alerts if a.simbad_main_id is not None) / total, 3)
            if total
            else None
        ),
        "lens_field_matches": sum(1 for a in alerts if a.lens_field_transient),
    }

    return {
        "alerts_processed": total,
        "latency": latency,
        "classification": {
            "counts_by_class": by_class,
            "counts_by_priority": by_priority,
            "mean_confidence": mean_confidence,
            "known_type_agreement": agreement,
            "known_type_agreement_n": comparable,
        },
        "anomaly_tracking": anomaly_tracking,
        "crossmatch_completeness": crossmatch,
    }


def render_markdown(
    *,
    report_date: str,
    gold_path: Path,
    classifications: list[ClassifiedAlert],
    assessments: list[AnomalyAssessment],
    metrics: dict[str, Any],
    top_n: int,
    minimum_priority: FollowUpPriority,
) -> str:
    """Render the nightly report as Markdown."""
    lines: list[str] = [
        f"# AGD Nightly Report — {report_date}",
        "",
        f"Source gold batch: `{gold_path}`  ",
        f"Alerts processed: **{metrics['alerts_processed']}**",
        "",
        "## Counts by class",
        "",
        "| Class | Count |",
        "|---|---|",
    ]
    for label, count in sorted(
        metrics["classification"]["counts_by_class"].items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"| {label} | {count} |")

    lines += ["", "## Follow-up priorities", "", "| Priority | Count |", "|---|---|"]
    for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        lines.append(f"| {name} | {metrics['classification']['counts_by_priority'].get(name, 0)} |")

    lens_hits = [c for c in classifications if "lens_field_transient" in c.priority_reason]
    lines += ["", "## Lens-field matches (time-delay cosmography channel)", ""]
    if lens_hits:
        for c in lens_hits:
            lines.append(f"- **{c.object_id}** — {c.priority_reason}")
    else:
        lines.append("None this batch.")

    lines += ["", f"## Top anomalies (top {top_n} by anomaly score)", ""]
    flagged = sorted(classifications, key=lambda c: c.anomaly_score, reverse=True)[:top_n]
    assessment_by_key = {(x.object_id, x.candidate_id): x for x in assessments}
    if flagged:
        for c in flagged:
            lines.append(
                f"### {c.object_id} — {c.primary_class} "
                f"(anomaly {c.anomaly_score:.2f}, {c.follow_up_priority.value})"
            )
            assessment = assessment_by_key.get((c.object_id, c.candidate_id))
            if assessment is not None:
                lines += [
                    f"- Baseline: {assessment.baseline_comparison}",
                    f"- Deviation: {assessment.deviation_sigma:.1f} sigma",
                    f"- False-alarm probability (trials-corrected, "
                    f"N={assessment.n_alerts_processed}): "
                    f"{assessment.false_alarm_probability:.2e}",
                    "- Systematics: "
                    + "; ".join(
                        f"{s.name}={'excluded' if s.excluded else 'NOT excluded'}"
                        for s in assessment.systematics
                    ),
                    f"- **Escalate: {assessment.escalate}** — {assessment.escalation_reason}",
                ]
            else:
                lines.append(
                    f"- Not handed to warm path (priority {c.follow_up_priority.value}, "
                    "below anomaly threshold)"
                )
            lines.append("")
    else:
        lines.append("No alerts in batch.")

    escalated = [
        x for x in assessments if x.escalate and x.follow_up_priority.at_least(minimum_priority)
    ]
    lines += ["", f"## Escalations to human review (priority >= {minimum_priority.value})", ""]
    if escalated:
        for x in escalated:
            lines.append(
                f"- **{x.object_id}** ({x.primary_class}, {x.follow_up_priority.value}): "
                f"{x.escalation_reason}"
            )
    else:
        lines.append("None.")

    m = metrics
    lines += [
        "",
        "## System metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Pipeline latency mean / median / max (s) | "
        f"{m['latency']['mean_seconds']} / {m['latency']['median_seconds']} / "
        f"{m['latency']['max_seconds']} |",
        f"| Mean classification confidence | {m['classification']['mean_confidence']} |",
        f"| Known-type agreement (Fink vs SIMBAD, n="
        f"{m['classification']['known_type_agreement_n']}) | "
        f"{m['classification']['known_type_agreement']} |",
        f"| Warm-path flagged / escalated / blocked-by-systematics | "
        f"{m['anomaly_tracking']['flagged_for_warm_path']} / "
        f"{m['anomaly_tracking']['escalated']} / "
        f"{m['anomaly_tracking']['blocked_by_systematics']} |",
        f"| Median / min false-alarm probability | {m['anomaly_tracking']['median_fap']} / "
        f"{m['anomaly_tracking']['min_fap']} |",
        f"| Gaia / SIMBAD matched fraction | "
        f"{m['crossmatch_completeness']['gaia_matched_fraction']} / "
        f"{m['crossmatch_completeness']['simbad_matched_fraction']} |",
        f"| Lens-field matches | {m['crossmatch_completeness']['lens_field_matches']} |",
        "",
        "---",
        "_Hot path is deterministic and LLM-free; warm-path assessments carry the four_",
        "_statistical-rigor fields (baseline, sigma, trials-corrected FAP, systematics)._",
        "",
    ]
    return "\n".join(lines)


def run_report(
    gold_path: Path,
    output_dir: Path,
    *,
    top_n: int | None = None,
    observation_date: str | None = None,
    gold_processing_id: str | None = None,
    classification_settings: ClassificationSettings | None = None,
    anomaly_settings: AnomalySettings | None = None,
    report_settings: ReportSettings | None = None,
) -> dict[str, Any]:
    """Build the nightly report for one gold batch. Returns a summary dict."""
    settings = get_settings()
    report_config = report_settings or settings.report
    classification_config = classification_settings or settings.classification
    top = top_n or report_config.include_top_n_events
    minimum_priority = FollowUpPriority(report_config.minimum_priority)

    alerts = load_gold_alerts(
        gold_path,
        observation_date=observation_date,
        gold_processing_id=gold_processing_id,
    )
    classifier = BaselineClassifier(classification_settings=classification_config)
    classifications = classifier.classify_batch(alerts)

    # Warm-path handoff: CRITICAL priority or anomaly score over threshold.
    agent = AnomalyAgent(anomaly_settings=anomaly_settings)
    flagged = [
        (a, c)
        for a, c in zip(alerts, classifications, strict=True)
        if c.follow_up_priority is FollowUpPriority.CRITICAL
        or c.anomaly_score >= classification_config.anomaly_score_threshold
    ]
    assessments = [agent.assess(a, c, n_alerts_processed=max(1, len(alerts))) for a, c in flagged]

    metrics = compute_metrics(alerts, classifications, assessments)
    report_date = observation_date or datetime.now(UTC).strftime("%Y-%m-%d")
    markdown = render_markdown(
        report_date=report_date,
        gold_path=gold_path,
        classifications=classifications,
        assessments=assessments,
        metrics=metrics,
        top_n=top,
        minimum_priority=minimum_priority,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"nightly_report_{report_date}.md"
    report_path.write_text(markdown, encoding="utf-8")
    json_path = output_dir / f"nightly_report_{report_date}.json"
    json_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    classifications_path: Path | None = None
    if classifications:
        classifications_path = output_dir / f"classifications_{report_date}.parquet"
        pd.DataFrame([c.to_flat_dict() for c in classifications]).to_parquet(
            classifications_path, index=False
        )
    assessments_path: Path | None = None
    if assessments:
        assessments_path = output_dir / f"assessments_{report_date}.parquet"
        pd.DataFrame([x.to_flat_dict() for x in assessments]).to_parquet(
            assessments_path, index=False
        )

    return {
        "report_date": report_date,
        "observation_date": observation_date,
        "gold_processing_id": gold_processing_id,
        "alerts_processed": len(alerts),
        "classified": len(classifications),
        "warm_path_assessed": len(assessments),
        "escalated": sum(1 for x in assessments if x.escalate),
        "critical": sum(
            1 for c in classifications if c.follow_up_priority is FollowUpPriority.CRITICAL
        ),
        "lens_field_matches": metrics["crossmatch_completeness"]["lens_field_matches"],
        "report_output": str(report_path),
        "json_output": str(json_path),
        "classifications_output": str(classifications_path) if classifications_path else None,
        "assessments_output": str(assessments_path) if assessments_path else None,
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold-path",
        type=Path,
        required=True,
        help="Gold Parquet file, or directory searched recursively for *.parquet.",
    )
    parser.add_argument(
        "--observation-date",
        default=None,
        help="Observation date (YYYY-MM-DD) used to scope a partitioned Gold root.",
    )
    parser.add_argument(
        "--gold-processing-id",
        default=None,
        help="Gold processing ID used to scope the report to one processing batch.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Report output directory (default: <storage base>/reports).",
    )
    parser.add_argument("--top-n", type=int, default=None, help="Top anomalies to include.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    output_dir = args.output_dir or (settings.storage.base_path / settings.report.output_path)
    summary = run_report(
        args.gold_path,
        output_dir,
        top_n=args.top_n,
        observation_date=args.observation_date,
        gold_processing_id=args.gold_processing_id,
    )
    for key, value in summary.items():
        if key == "metrics":
            continue
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
