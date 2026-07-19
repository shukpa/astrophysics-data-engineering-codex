"""Tests for the bounded Fink/ZTF calibration replay CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from scripts.run_fink_calibration_replay import load_manifest, run_replay

MANIFEST = Path("tests/fixtures/calibration/ztf_bts_replay_manifest.json")


class FakeFinkClient:
    def get_object(self, object_id: str) -> pd.DataFrame:
        year = 2020 if object_id.startswith("ZTF20") else 2021
        jd = 2459000.5 if year == 2020 else 2459400.5
        return pd.DataFrame(
            [
                {
                    "i:objectId": object_id,
                    "i:candid": sum(ord(char) for char in object_id),
                    "i:ra": 100.0,
                    "i:dec": 20.0,
                    "i:magpsf": 18.2,
                    "i:sigmapsf": 0.05,
                    "i:fid": 1,
                    "i:jd": jd,
                    "i:rb": 0.9,
                    "i:drb": 0.95,
                    "v:classification": "SN candidate",
                }
            ]
        )


class FakeHistoryFinkClient:
    def get_object(self, object_id: str) -> pd.DataFrame:
        base_jd = 2459000.5 if object_id.startswith("ZTF20") else 2459400.5
        candidate = sum(ord(char) for char in object_id) * 10
        return pd.DataFrame(
            [
                {
                    "i:objectId": object_id,
                    "i:candid": candidate + index,
                    "i:ra": 100.0,
                    "i:dec": 20.0,
                    "i:magpsf": 18.2 - 0.1 * index,
                    "i:sigmapsf": 0.05,
                    "i:fid": 1 if index % 2 == 0 else 2,
                    "i:jd": base_jd + index,
                    "i:rb": 0.9,
                    "i:drb": 0.95,
                    "v:classification": "SN candidate",
                }
                for index in range(4)
            ]
        )


class FakeCrossSplitFinkClient(FakeHistoryFinkClient):
    def get_object(self, object_id: str) -> pd.DataFrame:
        frame = super().get_object(object_id)
        if object_id == "ZTF17aaazdba":
            frame["i:jd"] = [2459200.5, 2459210.5, 2459220.5, 2459230.5]
        return frame


def test_manifest_contains_provenance_and_labels() -> None:
    manifest, objects = load_manifest(MANIFEST)
    assert "astro.caltech.edu/ztf/bts" in manifest["source_url"]
    assert len(objects) >= 5
    assert all(row["object_id"].startswith("ZTF") for row in objects)


def test_mocked_replay_writes_metrics_and_predictions(tmp_path: Path) -> None:
    summary = run_replay(
        MANIFEST,
        storage_base=tmp_path,
        split_date="2021-01-01",
        max_objects=4,
        max_alerts_per_object=5,
        client=FakeFinkClient(),
    )

    assert summary["objects_requested"] == 4
    assert summary["alerts_fetched"] == 4
    assert summary["bronze_count"] == 4
    assert summary["silver_count"] == 4
    assert summary["gold_count"] == 4
    assert Path(summary["predictions_output"]).exists()
    metrics = json.loads(Path(summary["metrics_output"]).read_text(encoding="utf-8"))
    assert "train" in metrics["metrics"]
    assert "validation" in metrics["metrics"]


def test_replay_hard_caps_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_objects"):
        run_replay(MANIFEST, storage_base=tmp_path, split_date="2021-01-01", max_objects=1001)
    with pytest.raises(ValueError, match="max_alerts must"):
        run_replay(MANIFEST, storage_base=tmp_path, split_date="2021-01-01", max_alerts=1001)
    with pytest.raises(ValueError, match="max_alerts_per_object"):
        run_replay(
            MANIFEST,
            storage_base=tmp_path,
            split_date="2021-01-01",
            max_alerts_per_object=1001,
        )


def test_replay_enforces_total_cap_and_builds_light_curve_history(tmp_path: Path) -> None:
    summary = run_replay(
        MANIFEST,
        storage_base=tmp_path,
        split_date="2021-01-01",
        max_objects=4,
        max_alerts=9,
        max_alerts_per_object=4,
        client=FakeHistoryFinkClient(),
    )

    assert summary["alerts_fetched"] == 9
    assert summary["gold_count"] == 9
    assert len(summary["fetched_by_object"]) == 4
    gold = pd.read_parquet(summary["gold_output"])
    features = [json.loads(value) for value in gold["lc_per_filter_json"]]
    assert any(band["n_detections"] > 1 for row in features for band in row.values())


def test_replay_reports_and_resolves_cross_split_objects(tmp_path: Path) -> None:
    summary = run_replay(
        MANIFEST,
        storage_base=tmp_path,
        split_date="2021-01-01",
        max_objects=2,
        max_alerts=8,
        max_alerts_per_object=4,
        client=FakeCrossSplitFinkClient(),
    )

    assert summary["cross_split_objects"] == ["ZTF17aaazdba"]
    assert summary["alerts_excluded_for_disjoint_split"] > 0
    assert summary["cross_split_policy"] == "validation_only"
    assert summary["metrics"]["validation"]["alerts"] > 0


def test_manifest_rejects_duplicate_object_ids(tmp_path: Path) -> None:
    manifest, objects = load_manifest(MANIFEST)
    duplicate = {**manifest, "objects": [objects[0], objects[0]]}
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(duplicate), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate object_id"):
        load_manifest(path)
