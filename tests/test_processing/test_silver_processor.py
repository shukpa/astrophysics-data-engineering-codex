"""Tests for the silver processor module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.models.alerts import AlertBatch, BronzeAlert, SilverBatch, ZTFAlert
from src.processing.silver_processor import SilverProcessor, create_silver_processor
from src.utils.config import ProcessingSettings, Settings, StorageSettings


def create_bronze_alert(
    object_id: str = "ZTF26abc",
    candid: int | None = 123,
    ra: float = 100.0,
    dec: float = 30.0,
    magpsf: float = 18.5,
    sigmapsf: float = 0.05,
    fid: int = 1,
    jd: float = 2461151.0,
    rb: float | None = 0.95,
    drb: float | None = 0.98,
    **kwargs: Any,
) -> BronzeAlert:
    raw = {
        "objectId": object_id,
        "candid": candid,
        "ra": ra,
        "dec": dec,
        "magpsf": magpsf,
        "sigmapsf": sigmapsf,
        "fid": fid,
        "jd": jd,
        "rb": rb,
        "drb": drb,
        "v:fink_class": "SN candidate",
        "d:cdsxmatch": "Unknown",
        **kwargs,
    }
    if candid is None:
        raw.pop("candid")
    return BronzeAlert(
        alert=ZTFAlert(**raw),
        source="fink_api",
        source_version="v1",
        raw_payload=raw,
        processing_id="bronze_test",
    )


@pytest.fixture
def processor(tmp_path: Path) -> SilverProcessor:
    storage = StorageSettings(base_path=tmp_path, file_format="parquet")
    processing = ProcessingSettings(schema_validation_mode="strict")
    return SilverProcessor(storage_settings=storage, processing_settings=processing)


def create_batch(alerts: list[BronzeAlert]) -> AlertBatch:
    return AlertBatch(alerts=alerts, batch_id="bronze_batch")


class TestSilverProcessor:
    def test_process_valid_rows(self, processor: SilverProcessor) -> None:
        batch = create_batch([create_bronze_alert(object_id="ZTF26a")])

        silver = processor.process_batch(batch, batch_id="silver_test")

        assert silver.count == 1
        assert silver.alerts[0].object_id == "ZTF26a"
        assert silver.alerts[0].fink_class == "SN candidate"
        assert silver.alerts[0].bronze_processing_id == "bronze_test"
        assert silver.alerts[0].silver_processing_id == "silver_test"
        assert silver.alerts[0].raw_payload_hash is not None
        assert silver.rejected_count == 0

    def test_rejects_quality_failures(self, processor: SilverProcessor) -> None:
        batch = create_batch(
            [
                create_bronze_alert(object_id="ZTF26good"),
                create_bronze_alert(object_id="ZTF26bad_sigma", sigmapsf=1.2),
                create_bronze_alert(object_id="ZTF26bad_rb", rb=0.1),
            ]
        )

        silver = processor.process_batch(batch)

        assert silver.count == 1
        assert silver.alerts[0].object_id == "ZTF26good"
        assert silver.rejected_count == 2

    def test_deduplicates_candidate_id_by_best_scores(self, processor: SilverProcessor) -> None:
        batch = create_batch(
            [
                create_bronze_alert(object_id="ZTF26low", candid=10, rb=0.9, drb=0.2),
                create_bronze_alert(object_id="ZTF26high", candid=10, rb=0.8, drb=0.95),
            ]
        )

        silver = processor.process_batch(batch)

        assert silver.count == 1
        assert silver.duplicate_count == 1
        assert silver.alerts[0].object_id == "ZTF26high"

    def test_deduplicates_missing_candidate_with_fallback_key(
        self, processor: SilverProcessor
    ) -> None:
        batch = create_batch(
            [
                create_bronze_alert(object_id="ZTF26same", candid=None, rb=0.8, drb=0.5),
                create_bronze_alert(object_id="ZTF26same", candid=None, rb=0.9, drb=0.5),
            ]
        )

        silver = processor.process_batch(batch)

        assert silver.count == 1
        assert silver.duplicate_count == 1
        assert silver.alerts[0].rb_score == 0.9

    def test_empty_input(self, processor: SilverProcessor) -> None:
        silver = processor.process_batch(create_batch([]))

        assert silver.count == 0
        assert silver.rejected_count == 0
        assert silver.duplicate_count == 0

    def test_write_and_read_parquet(self, processor: SilverProcessor) -> None:
        silver = processor.process_batch(
            create_batch([create_bronze_alert(object_id="ZTF26write")])
        )

        output_path = processor.write_batch(silver)
        df = processor.read_silver_data()

        assert output_path.exists()
        assert len(df) == 1
        assert df.iloc[0]["object_id"] == "ZTF26write"

    def test_replayed_candidate_is_idempotent_and_keeps_best_score(
        self, processor: SilverProcessor
    ) -> None:
        first = processor.process_batch(
            create_batch([create_bronze_alert(object_id="ZTF26first", candid=44, drb=0.5)]),
            batch_id="silver_first",
        )
        second = processor.process_batch(
            create_batch([create_bronze_alert(object_id="ZTF26best", candid=44, drb=0.99)]),
            batch_id="silver_second",
        )

        processor.write_batch(first)
        processor.write_batch(second)
        result = processor.read_silver_data()

        assert len(result) == 1
        assert result.iloc[0]["object_id"] == "ZTF26best"
        assert result.iloc[0]["drb_score"] == pytest.approx(0.99)

    def test_replayed_fallback_key_is_idempotent(self, processor: SilverProcessor) -> None:
        alert = create_bronze_alert(object_id="ZTF26fallback", candid=None)
        first = processor.process_batch(create_batch([alert]), batch_id="silver_first")
        second = processor.process_batch(create_batch([alert]), batch_id="silver_second")

        processor.write_batch(first)
        processor.write_batch(second)

        assert len(processor.read_silver_data()) == 1

    def test_replayed_candidate_is_idempotent_for_json(self, tmp_path: Path) -> None:
        processor = SilverProcessor(
            storage_settings=StorageSettings(base_path=tmp_path, file_format="json")
        )
        alert = create_bronze_alert(object_id="ZTF26json", candid=45)
        first = processor.process_batch(create_batch([alert]), batch_id="silver_first")
        second = processor.process_batch(create_batch([alert]), batch_id="silver_second")

        processor.write_batch(first)
        processor.write_batch(second)

        assert len(processor.read_silver_data()) == 1

    def test_previous_detection_count_excludes_upper_limits(
        self, processor: SilverProcessor
    ) -> None:
        alert = create_bronze_alert(
            prv_candidates=[
                {"jd": 2461150.0, "fid": 1, "magpsf": 19.0},
                {"jd": 2461149.0, "fid": 1, "magpsf": None},
                {"not": "a detection"},
            ]
        )

        silver = processor.process_batch(create_batch([alert]))

        assert silver.alerts[0].num_previous_detections == 1

    def test_get_statistics(self, processor: SilverProcessor) -> None:
        silver = processor.process_batch(
            create_batch(
                [
                    create_bronze_alert(object_id="ZTF26one"),
                    create_bronze_alert(object_id="ZTF26two", candid=456),
                ]
            )
        )
        processor.write_batch(silver)

        stats = processor.get_statistics()

        assert stats["total_records"] == 2
        assert stats["unique_objects"] == 2
        assert stats["classifications"]["SN candidate"] == 2


class TestCreateSilverProcessor:
    def test_creates_processor(self) -> None:
        processor = create_silver_processor()
        assert isinstance(processor, SilverProcessor)

    def test_accepts_custom_settings(self, tmp_path: Path) -> None:
        storage = StorageSettings(base_path=tmp_path)
        settings = Settings(storage=storage)

        processor = create_silver_processor(settings=settings)

        assert processor.output_path == tmp_path / "silver/alerts"


def test_silver_batch_object_ids() -> None:
    batch = SilverBatch(alerts=[], batch_id="empty")
    assert batch.object_ids == []


def test_read_empty_silver_path(processor: SilverProcessor) -> None:
    df = processor.read_silver_data()
    assert isinstance(df, pd.DataFrame)
    assert df.empty
