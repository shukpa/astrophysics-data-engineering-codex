"""Tests for the bronze processor module."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.exceptions import BronzeProcessingError, SchemaValidationError
from src.models.alerts import AlertBatch, BronzeAlert, ZTFAlert
from src.processing.bronze_processor import BronzeProcessor, create_bronze_processor
from src.utils.config import ProcessingSettings, Settings, StorageSettings


def create_sample_alert(
    object_id: str = "ZTF21aaxtctv",
    ra: float = 193.822,
    dec: float = 2.896,
    magpsf: float = 18.5,
    jd: float = 2460000.5,
    fid: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a sample alert dictionary for testing.

    Args:
        object_id: ZTF object identifier.
        ra: Right ascension in degrees.
        dec: Declination in degrees.
        magpsf: PSF magnitude.
        jd: Julian date.
        fid: Filter ID.
        **kwargs: Additional fields to include.

    Returns:
        Dictionary representing a raw alert.
    """
    alert = {
        "objectId": object_id,
        "candid": 1234567890,
        "ra": ra,
        "dec": dec,
        "magpsf": magpsf,
        "sigmapsf": 0.05,
        "fid": fid,
        "jd": jd,
        "diffmaglim": 20.5,
        "rb": 0.95,
        "drb": 0.98,
        "v:fink_class": "SN candidate",
        "d:cdsxmatch": "Unknown",
        **kwargs,
    }
    return alert


class TestZTFAlert:
    """Tests for ZTFAlert model."""

    def test_valid_alert_parsing(self) -> None:
        """Test parsing a valid alert."""
        raw = create_sample_alert()
        alert = ZTFAlert(**raw)

        assert alert.objectId == "ZTF21aaxtctv"
        assert alert.ra == 193.822
        assert alert.dec == 2.896
        assert alert.magpsf == 18.5

    def test_mjd_conversion(self) -> None:
        """Test Julian Date to Modified Julian Date conversion."""
        raw = create_sample_alert(jd=2460000.5)
        alert = ZTFAlert(**raw)

        # MJD = JD - 2400000.5
        assert alert.mjd == 60000.0

    def test_filter_name(self) -> None:
        """Test filter name property."""
        for fid, expected in [(1, "g"), (2, "r"), (3, "i")]:
            raw = create_sample_alert(fid=fid)
            alert = ZTFAlert(**raw)
            assert alert.filter_name == expected

    def test_invalid_ra_raises_error(self) -> None:
        """Test that invalid RA values raise validation error."""
        raw = create_sample_alert(ra=400.0)  # RA must be < 360
        with pytest.raises(ValueError):
            ZTFAlert(**raw)

    def test_invalid_dec_raises_error(self) -> None:
        """Test that invalid Dec values raise validation error."""
        raw = create_sample_alert(dec=100.0)  # Dec must be <= 90
        with pytest.raises(ValueError):
            ZTFAlert(**raw)

    def test_extra_fields_allowed(self) -> None:
        """Test that extra fields are preserved."""
        raw = create_sample_alert(custom_field="custom_value")
        alert = ZTFAlert(**raw)
        assert alert.model_extra.get("custom_field") == "custom_value"


class TestBronzeAlert:
    """Tests for BronzeAlert model."""

    def test_bronze_alert_creation(self) -> None:
        """Test creating a BronzeAlert from ZTFAlert."""
        raw = create_sample_alert()
        ztf_alert = ZTFAlert(**raw)
        bronze = BronzeAlert(
            alert=ztf_alert,
            source="fink_api",
            raw_payload=raw,
        )

        assert bronze.object_id == "ZTF21aaxtctv"
        assert bronze.source == "fink_api"
        assert bronze.raw_payload == raw

    def test_observation_date_computed(self) -> None:
        """Test that observation_date is computed from JD."""
        raw = create_sample_alert(jd=2460000.5)  # Feb 25, 2023
        ztf_alert = ZTFAlert(**raw)
        bronze = BronzeAlert(alert=ztf_alert)

        assert bronze.observation_date is not None
        # Should be a valid date string
        assert len(bronze.observation_date) == 10  # YYYY-MM-DD format

    def test_to_flat_dict(self) -> None:
        """Test flattening BronzeAlert for storage."""
        raw = create_sample_alert()
        ztf_alert = ZTFAlert(**raw)
        bronze = BronzeAlert(
            alert=ztf_alert,
            source="fink_api",
            raw_payload=raw,
            processing_id="test_batch",
        )

        flat = bronze.to_flat_dict()

        assert flat["object_id"] == "ZTF21aaxtctv"
        assert flat["ra"] == 193.822
        assert flat["dec"] == 2.896
        assert flat["magpsf"] == 18.5
        assert flat["filter_id"] == 1
        assert flat["filter_name"] == "g"
        assert flat["source"] == "fink_api"
        assert flat["processing_id"] == "test_batch"
        assert flat["fink_class"] == "SN candidate"
        assert "raw_payload_json" in flat


class TestAlertBatch:
    """Tests for AlertBatch model."""

    def test_batch_creation(self) -> None:
        """Test creating an AlertBatch."""
        alerts = [
            BronzeAlert(alert=ZTFAlert(**create_sample_alert(object_id=f"ZTF{i}")))
            for i in range(5)
        ]
        batch = AlertBatch(alerts=alerts, batch_id="test_batch_001")

        assert batch.count == 5
        assert batch.batch_id == "test_batch_001"
        assert len(batch.object_ids) == 5

    def test_empty_batch(self) -> None:
        """Test creating an empty AlertBatch."""
        batch = AlertBatch(alerts=[], batch_id="empty_batch")
        assert batch.count == 0
        assert batch.object_ids == []


class TestBronzeProcessor:
    """Tests for BronzeProcessor."""

    @pytest.fixture
    def processor(self, tmp_path: Path) -> BronzeProcessor:
        """Create a processor with temporary storage."""
        storage = StorageSettings(base_path=tmp_path, file_format="parquet")
        processing = ProcessingSettings(schema_validation_mode="strict")
        return BronzeProcessor(
            storage_settings=storage,
            processing_settings=processing,
        )

    @pytest.fixture
    def sample_alerts(self) -> list[dict[str, Any]]:
        """Create sample alerts for testing."""
        return [
            create_sample_alert(object_id="ZTF21aaa", ra=100.0, dec=30.0),
            create_sample_alert(object_id="ZTF21bbb", ra=150.0, dec=-20.0),
            create_sample_alert(object_id="ZTF21ccc", ra=200.0, dec=50.0),
        ]

    def test_process_alerts_success(
        self, processor: BronzeProcessor, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test successful processing of valid alerts."""
        batch = processor.process_alerts(sample_alerts)

        assert batch.count == 3
        assert "ZTF21aaa" in batch.object_ids
        assert "ZTF21bbb" in batch.object_ids
        assert "ZTF21ccc" in batch.object_ids

    def test_process_alerts_with_custom_batch_id(
        self, processor: BronzeProcessor, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test processing with custom batch ID."""
        batch = processor.process_alerts(sample_alerts, batch_id="custom_123")
        assert batch.batch_id == "custom_123"

    def test_process_alerts_validation_failure_strict(
        self, processor: BronzeProcessor
    ) -> None:
        """Test that invalid alerts cause failure in strict mode."""
        invalid_alerts = [
            {"objectId": "ZTF21xxx"},  # Missing required fields
        ]

        batch = processor.process_alerts(invalid_alerts)
        # In strict mode, batch should be empty but not raise
        # (only raises if ALL alerts fail and batch is empty)
        assert batch.count == 0

    def test_process_alerts_validation_failure_all_invalid_raises(
        self, tmp_path: Path
    ) -> None:
        """Test that all-invalid batch raises error in strict mode."""
        storage = StorageSettings(base_path=tmp_path)
        processing = ProcessingSettings(schema_validation_mode="strict")
        processor = BronzeProcessor(
            storage_settings=storage,
            processing_settings=processing,
        )

        invalid_alerts = [
            {"objectId": "ZTF21xxx"},  # Missing required fields
            {"objectId": "ZTF21yyy"},  # Missing required fields
        ]

        with pytest.raises(BronzeProcessingError):
            processor.process_alerts(invalid_alerts)

    def test_process_alerts_validation_warn_mode(self, tmp_path: Path) -> None:
        """Test that warn mode doesn't raise but logs."""
        storage = StorageSettings(base_path=tmp_path)
        processing = ProcessingSettings(schema_validation_mode="warn")
        processor = BronzeProcessor(
            storage_settings=storage,
            processing_settings=processing,
        )

        alerts = [
            create_sample_alert(object_id="ZTF21valid"),
            {"objectId": "ZTF21invalid"},  # Missing fields
        ]

        batch = processor.process_alerts(alerts)
        assert batch.count == 1  # Only valid alert processed

    def test_write_batch_parquet(
        self, processor: BronzeProcessor, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test writing batch to Parquet format."""
        batch = processor.process_alerts(sample_alerts)
        output_path = processor.write_batch(batch)

        assert output_path.exists()
        # Read back and verify
        df = pd.read_parquet(processor.output_path)
        assert len(df) == 3

    def test_write_batch_empty(self, processor: BronzeProcessor) -> None:
        """Test writing empty batch doesn't fail."""
        batch = AlertBatch(alerts=[], batch_id="empty")
        output_path = processor.write_batch(batch)
        assert output_path == processor.output_path

    def test_write_batch_json(
        self, tmp_path: Path, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test writing batch to JSON format."""
        storage = StorageSettings(base_path=tmp_path, file_format="json")
        processor = BronzeProcessor(storage_settings=storage)

        batch = processor.process_alerts(sample_alerts)
        output_path = processor.write_batch(batch)

        assert output_path.suffix == ".json"
        assert output_path.exists()

    def test_read_bronze_data(
        self, processor: BronzeProcessor, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test reading data back from bronze layer."""
        batch = processor.process_alerts(sample_alerts)
        processor.write_batch(batch)

        df = processor.read_bronze_data()
        assert len(df) == 3
        assert "object_id" in df.columns
        assert "ra" in df.columns
        assert "dec" in df.columns

    def test_read_bronze_data_empty(self, processor: BronzeProcessor) -> None:
        """Test reading from empty bronze layer."""
        df = processor.read_bronze_data()
        assert df.empty

    def test_get_statistics(
        self, processor: BronzeProcessor, sample_alerts: list[dict[str, Any]]
    ) -> None:
        """Test getting statistics from bronze layer."""
        batch = processor.process_alerts(sample_alerts)
        processor.write_batch(batch)

        stats = processor.get_statistics()

        assert stats["total_records"] == 3
        assert stats["unique_objects"] == 3
        assert "date_range" in stats

    def test_get_statistics_empty(self, processor: BronzeProcessor) -> None:
        """Test statistics for empty bronze layer."""
        stats = processor.get_statistics()

        assert stats["total_records"] == 0
        assert stats["unique_objects"] == 0


class TestCreateBronzeProcessor:
    """Tests for the factory function."""

    def test_creates_processor(self) -> None:
        """Test factory function creates BronzeProcessor."""
        processor = create_bronze_processor()
        assert isinstance(processor, BronzeProcessor)

    def test_accepts_custom_settings(self, tmp_path: Path) -> None:
        """Test factory accepts custom settings."""
        storage = StorageSettings(base_path=tmp_path)
        settings = Settings(storage=storage)

        processor = create_bronze_processor(settings=settings)
        assert processor.output_path == tmp_path / "bronze/alerts"
