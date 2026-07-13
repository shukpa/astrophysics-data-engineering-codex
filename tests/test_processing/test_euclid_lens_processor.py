"""Tests for lens models and the SLDE bronze/silver processor."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.models.lenses import EuclidLensCandidate, EuclidLensCatalog
from src.processing.euclid_lens_processor import EuclidLensProcessor, load_lens_rows
from src.utils.config import EuclidSettings, StorageSettings

FIXTURE = Path("tests/fixtures/euclid/slde_q1_sample.json")


def make_processor(tmp_path: Path, **euclid_overrides) -> EuclidLensProcessor:
    return EuclidLensProcessor(
        storage_settings=StorageSettings(base_path=tmp_path),
        euclid_settings=EuclidSettings(**euclid_overrides),
    )


def sample_rows() -> list[dict]:
    return [
        {
            "name": "EUCL J0001",
            "ra": 52.9,
            "dec": -28.1,
            "grade": "A",
            "score": 0.97,
            "theta_e_arcsec": 1.4,
            "discovery_engine": "SLDE",
        },
        {"name": "EUCL J0002", "ra": 61.2, "dec": -48.4, "grade": "b", "score": 0.72},
        {"name": "EUCL J0003", "ra": 269.7, "dec": 66.0, "grade": "C", "score": 0.55},
    ]


class TestLensModels:
    def test_grade_normalised_and_validated(self) -> None:
        candidate = EuclidLensCandidate(name="EUCL Jx", ra=1.0, dec=2.0, grade="a")
        assert candidate.grade == "A"
        with pytest.raises(ValueError):
            EuclidLensCandidate(name="EUCL Jy", ra=1.0, dec=2.0, grade="Z")

    def test_optional_theta_e_and_score(self) -> None:
        candidate = EuclidLensCandidate(name="EUCL Jz", ra=1.0, dec=2.0, grade="B")
        assert candidate.theta_e_arcsec is None
        assert candidate.score is None

    def test_catalog_counts_by_grade(self) -> None:
        catalog = EuclidLensCatalog(
            candidates=[
                EuclidLensCandidate(name="EUCL J1", ra=1.0, dec=1.0, grade="A"),
                EuclidLensCandidate(name="EUCL J2", ra=2.0, dec=2.0, grade="A"),
                EuclidLensCandidate(name="EUCL J3", ra=3.0, dec=3.0, grade="B"),
            ],
            source="test",
        )
        assert catalog.count == 3
        assert catalog.by_grade() == {"A": 2, "B": 1}


class TestLoadLensRows:
    def test_load_json(self, tmp_path: Path) -> None:
        path = tmp_path / "lenses.json"
        path.write_text(json.dumps(sample_rows()))
        assert len(load_lens_rows(path)) == 3

    def test_load_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "lenses.csv"
        pd.DataFrame(sample_rows()).to_csv(path, index=False)
        rows = load_lens_rows(path)
        assert len(rows) == 3
        assert rows[0]["name"] == "EUCL J0001"

    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "lenses.votable"
        path.write_text("nope")
        with pytest.raises(ValueError):
            load_lens_rows(path)

    def test_bundled_fixture_loads(self) -> None:
        rows = load_lens_rows(FIXTURE)
        assert len(rows) == 20


class TestLensProcessing:
    def test_process_catalog_validates_filters_and_counts(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path)  # default allowed grades: A, B
        rows = [*sample_rows(), {"name": "bad", "ra": 999.0, "dec": 0.0, "grade": "A"}]
        catalog, counters = processor.process_catalog(rows, source="unit")

        assert counters == {
            "input": 4,
            "kept": 2,  # A + B
            "rejected_invalid": 1,  # ra=999 out of range
            "rejected_grade": 1,  # grade C dropped
        }
        assert {c.grade for c in catalog.candidates} == {"A", "B"}
        assert catalog.candidates[1].grade == "B"  # lower-case 'b' normalised

    def test_grade_filter_is_config_driven(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path, lens_allowed_grades=["A", "B", "C"])
        catalog, counters = processor.process_catalog(sample_rows(), source="unit")
        assert counters["kept"] == 3
        assert counters["rejected_grade"] == 0
        assert catalog.by_grade() == {"A": 1, "B": 1, "C": 1}

    def test_alias_columns_are_canonicalised(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path)
        rows = [
            {
                "designation": "EUCL Jalias",
                "right_ascension": 10.0,
                "declination": -5.0,
                "expert_grade": "A",
                "einstein_radius_arcsec": 2.2,
                "engine": "expert",
            }
        ]
        catalog, counters = processor.process_catalog(rows, source="unit")
        assert counters["kept"] == 1
        lens = catalog.candidates[0]
        assert lens.name == "EUCL Jalias"
        assert lens.theta_e_arcsec == pytest.approx(2.2)
        assert lens.discovery_engine == "expert"

    def test_dr_tag_stamped_from_config(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path, dr_tag="DR1F")
        catalog, _ = processor.process_catalog(sample_rows()[:1], source="unit")
        assert catalog.candidates[0].dr_tag == "DR1F"
        assert catalog.dr_tag == "DR1F"

    def test_bronze_preserves_raw_rows_with_provenance(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path)
        output = processor.write_bronze(sample_rows(), source="unit-source")

        df = pd.read_parquet(output)
        assert len(df) == 3
        # Raw values preserved exactly, provenance columns attached.
        assert set(df["name"]) == {"EUCL J0001", "EUCL J0002", "EUCL J0003"}
        assert df["grade"].tolist() == ["A", "b", "C"]  # NOT normalised in bronze
        assert (df["_ingest_source"] == "unit-source").all()
        assert (df["_ingest_dr_tag"] == "Q1").all()
        assert df["_ingest_retrieved_at"].notna().all()

    def test_silver_roundtrip(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path)
        catalog, _ = processor.process_catalog(sample_rows(), source="unit")
        output = processor.write_silver(catalog)
        assert output.exists()

        lenses = processor.read_silver_lenses()
        assert len(lenses) == 2
        assert all(isinstance(lens, EuclidLensCandidate) for lens in lenses)
        assert {lens.grade for lens in lenses} == {"A", "B"}

    def test_fixture_through_full_bronze_silver(self, tmp_path: Path) -> None:
        processor = make_processor(tmp_path)
        rows = load_lens_rows(FIXTURE)
        processor.write_bronze(rows, source=str(FIXTURE))
        catalog, counters = processor.process_catalog(rows, source=str(FIXTURE))
        processor.write_silver(catalog)

        # Fixture: 8 A + 8 B kept, 4 C grade-filtered by default.
        assert counters == {
            "input": 20,
            "kept": 16,
            "rejected_invalid": 0,
            "rejected_grade": 4,
        }
        assert len(processor.read_silver_lenses()) == 16
