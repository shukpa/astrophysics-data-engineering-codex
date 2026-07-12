"""Tests for the Fink Silver smoke script."""

from __future__ import annotations

from pathlib import Path

from scripts.run_fink_silver_smoke import generate_databricks_sql, run_smoke
from tests.test_processing.test_silver_processor import create_batch, create_bronze_alert

from src.ingestion.fink_api_client import FinkAPIClient
from src.processing.silver_processor import SilverProcessor


def test_generate_databricks_sql() -> None:
    processor = SilverProcessor()
    silver = processor.process_batch(create_batch([create_bronze_alert(object_id="ZTF26sql")]))

    sql = generate_databricks_sql(silver)

    assert "SELECT * FROM VALUES" in sql
    assert "ZTF26sql" in sql
    assert "raw_payload_hash" in sql


def test_run_smoke_with_mocked_fink(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_latest_records(
        _self: FinkAPIClient,
        fink_class: str,
        n: int,
    ) -> list[dict]:
        return [
            {
                "objectId": "ZTF26mock",
                "candid": 1,
                "ra": 10.0,
                "dec": 20.0,
                "magpsf": 18.0,
                "sigmapsf": 0.1,
                "fid": 1,
                "jd": 2461151.0,
                "rb": 0.9,
                "drb": 0.95,
                "v:fink_class": fink_class,
            }
            for _ in range(n)
        ]

    monkeypatch.setattr(FinkAPIClient, "get_latest_alert_records", fake_latest_records)
    sql_output = tmp_path / "databricks.sql"

    summary = run_smoke(
        fink_class="SN candidate",
        limit=2,
        storage_base=tmp_path / "data",
        databricks_sql_output=sql_output,
    )

    assert summary["fetched"] == 2
    assert summary["bronze_count"] == 2
    assert summary["silver_count"] == 1
    assert summary["silver_duplicates"] == 1
    assert sql_output.exists()
