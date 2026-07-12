"""Tests for the gold layer processor.

Catalog clients are replaced with in-memory fakes — no network access.
Covers cross-match enrichment, the star/extragalactic discriminator,
light-curve features, provenance pointers, graceful degradation on
catalog failure, and Parquet round-trips.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.exceptions import GaiaError
from src.models.alerts import GoldBatch, SilverAlert, SilverBatch
from src.models.crossref import GaiaMatch, SimbadMatch
from src.processing.gold_processor import GoldProcessor, create_gold_processor
from src.utils.config import CrossmatchSettings, StorageSettings

# ---------------------------------------------------------------------------
# Fakes and builders
# ---------------------------------------------------------------------------


class FakeGaiaClient:
    def __init__(self, match: GaiaMatch | None = None, error: Exception | None = None) -> None:
        self.match = match
        self.error = error
        self.calls: list[tuple[float, float]] = []

    def nearest(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float | None = None,  # noqa: ARG002 - mirrors real interface
    ):
        self.calls.append((ra, dec))
        if self.error is not None:
            raise self.error
        return self.match


class FakeSimbadClient:
    def __init__(self, match: SimbadMatch | None = None, error: Exception | None = None) -> None:
        self.match = match
        self.error = error
        self.calls: list[tuple[float, float]] = []

    def nearest(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float | None = None,  # noqa: ARG002 - mirrors real interface
    ):
        self.calls.append((ra, dec))
        if self.error is not None:
            raise self.error
        return self.match


def stellar_gaia_match(**overrides) -> GaiaMatch:
    """A Gaia match with significant parallax AND proper motion."""
    fields = {
        "source_id": 4472832130942575872,
        "ra": 269.4521,
        "dec": 4.6934,
        "separation_arcsec": 0.4,
        "g_mag": 8.2,
        "parallax": 547.0,
        "parallax_error": 0.03,
        "pmra": -802.8,
        "pmra_error": 0.03,
        "pmdec": 10362.5,
        "pmdec_error": 0.04,
    }
    fields.update(overrides)
    return GaiaMatch(**fields)


def faint_background_gaia_match() -> GaiaMatch:
    """A Gaia match with insignificant astrometry (extragalactic-like)."""
    return stellar_gaia_match(
        parallax=0.1,
        parallax_error=0.5,
        pmra=0.2,
        pmra_error=0.4,
        pmdec=-0.1,
        pmdec_error=0.4,
        g_mag=20.5,
    )


def make_silver_alert(**overrides) -> SilverAlert:
    fields = {
        "object_id": "ZTF21aaxtctv",
        "candidate_id": 1234567890123,
        "ra": 193.822,
        "dec": 2.896,
        "magpsf": 18.5,
        "sigmapsf": 0.05,
        "filter_id": 1,
        "filter_name": "g",
        "jd": 2460000.5,
        "mjd": 60000.0,
        "observation_date": "2023-02-25",
        "fink_class": "SN candidate",
        "rb_score": 0.95,
        "drb_score": 0.98,
        "source": "fink_api",
        "source_version": "v1",
        "bronze_processing_id": "bronze_test_001",
        "silver_processing_id": "silver_test_001",
        "source_object_id": "ZTF21aaxtctv",
        "source_candidate_id": 1234567890123,
        "ingestion_timestamp": datetime(2023, 2, 25, 12, 0, 0, tzinfo=UTC),
        "silver_timestamp": datetime(2023, 2, 25, 12, 5, 0, tzinfo=UTC),
        "raw_payload_hash": "abc123",
        "raw_payload_json": json.dumps(
            {
                "objectId": "ZTF21aaxtctv",
                "prv_candidates": [
                    {"jd": 2459998.5, "fid": 2, "magpsf": 19.1, "sigmapsf": 0.07},
                    {"jd": 2459999.5, "fid": 1, "magpsf": 18.8, "sigmapsf": 0.06},
                    {"jd": 2459997.5, "fid": 1, "magpsf": None},  # non-detection
                ],
            }
        ),
    }
    fields.update(overrides)
    return SilverAlert(**fields)


def make_processor(
    tmp_path,
    gaia_client=None,
    simbad_client=None,
    enable_crossmatch: bool = True,
    **crossmatch_overrides,
) -> GoldProcessor:
    # Default BOTH clients to no-op fakes so unit tests never touch the network.
    # (A real client is only created when GoldProcessor is given None, which
    # would make "offline" tests issue live Gaia/SIMBAD queries.)
    return GoldProcessor(
        storage_settings=StorageSettings(base_path=tmp_path),
        crossmatch_settings=CrossmatchSettings(cache_enabled=False, **crossmatch_overrides),
        gaia_client=gaia_client if gaia_client is not None else FakeGaiaClient(None),
        simbad_client=simbad_client if simbad_client is not None else FakeSimbadClient(None),
        enable_crossmatch=enable_crossmatch,
    )


def make_batch(*alerts: SilverAlert) -> SilverBatch:
    return SilverBatch(alerts=list(alerts), batch_id="silver_test_001", source_count=len(alerts))


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


class TestGoldEnrichment:
    def test_gaia_and_simbad_columns_populated(self, tmp_path) -> None:
        gaia = FakeGaiaClient(match=stellar_gaia_match())
        simbad = FakeSimbadClient(
            match=SimbadMatch(main_id="V* Test", otype="V*", separation_arcsec=0.5)
        )
        processor = make_processor(tmp_path, gaia_client=gaia, simbad_client=simbad)

        batch = processor.process_batch(make_batch(make_silver_alert()))

        assert isinstance(batch, GoldBatch)
        assert batch.count == 1
        alert = batch.alerts[0]
        assert alert.gaia_source_id == 4472832130942575872
        assert alert.gaia_g_mag == pytest.approx(8.2)
        assert alert.gaia_parallax_snr == pytest.approx(547.0 / 0.03)
        assert alert.gaia_pm_total is not None and alert.gaia_pm_total > 10000
        assert alert.simbad_main_id == "V* Test"
        assert alert.simbad_otype == "V*"
        assert batch.matched_gaia_count == 1
        assert batch.matched_simbad_count == 1
        assert batch.crossmatch_failed_count == 0
        # Clients queried at the alert position
        assert gaia.calls == [(193.822, 2.896)]
        assert simbad.calls == [(193.822, 2.896)]

    def test_no_match_yields_null_columns(self, tmp_path) -> None:
        processor = make_processor(
            tmp_path, gaia_client=FakeGaiaClient(None), simbad_client=FakeSimbadClient(None)
        )
        batch = processor.process_batch(make_batch(make_silver_alert()))

        alert = batch.alerts[0]
        assert alert.gaia_source_id is None
        assert alert.simbad_main_id is None
        assert batch.matched_gaia_count == 0
        assert batch.matched_simbad_count == 0

    def test_catalog_failure_degrades_gracefully(self, tmp_path) -> None:
        gaia = FakeGaiaClient(error=GaiaError("TAP down"))
        simbad = FakeSimbadClient(
            match=SimbadMatch(main_id="M 31", otype="G", separation_arcsec=1.0)
        )
        processor = make_processor(tmp_path, gaia_client=gaia, simbad_client=simbad)

        batch = processor.process_batch(make_batch(make_silver_alert()))

        assert batch.count == 1  # batch survives
        alert = batch.alerts[0]
        assert alert.gaia_source_id is None  # failed side is null
        assert alert.simbad_main_id == "M 31"  # healthy side still enriched
        assert batch.crossmatch_failed_count == 1

    def test_crossmatch_disabled_never_calls_clients(self, tmp_path) -> None:
        gaia = FakeGaiaClient(match=stellar_gaia_match())
        simbad = FakeSimbadClient()
        processor = make_processor(
            tmp_path, gaia_client=gaia, simbad_client=simbad, enable_crossmatch=False
        )

        batch = processor.process_batch(make_batch(make_silver_alert()))

        assert gaia.calls == []
        assert simbad.calls == []
        assert batch.alerts[0].gaia_source_id is None


# ---------------------------------------------------------------------------
# Star/extragalactic discriminator
# ---------------------------------------------------------------------------


class TestDiscriminator:
    def test_parallax_and_pm_significant(self, tmp_path) -> None:
        processor = make_processor(tmp_path, gaia_client=FakeGaiaClient(stellar_gaia_match()))
        batch = processor.process_batch(make_batch(make_silver_alert()))
        alert = batch.alerts[0]
        assert alert.is_likely_stellar is True
        assert alert.stellar_evidence == "parallax+proper_motion"

    def test_parallax_only(self, tmp_path) -> None:
        match = stellar_gaia_match(pmra=0.1, pmra_error=1.0, pmdec=0.1, pmdec_error=1.0)
        processor = make_processor(tmp_path, gaia_client=FakeGaiaClient(match))
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is True
        assert alert.stellar_evidence == "parallax"

    def test_proper_motion_only(self, tmp_path) -> None:
        match = stellar_gaia_match(parallax=0.05, parallax_error=0.5)
        processor = make_processor(tmp_path, gaia_client=FakeGaiaClient(match))
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is True
        assert alert.stellar_evidence == "proper_motion"

    def test_insignificant_astrometry_is_not_stellar(self, tmp_path) -> None:
        processor = make_processor(
            tmp_path, gaia_client=FakeGaiaClient(faint_background_gaia_match())
        )
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is False
        assert alert.stellar_evidence is None

    def test_negative_parallax_never_counts(self, tmp_path) -> None:
        # Large |SNR| but unphysical sign: must not mark stellar via parallax.
        match = stellar_gaia_match(
            parallax=-10.0,
            parallax_error=0.1,
            pmra=0.1,
            pmra_error=1.0,
            pmdec=0.1,
            pmdec_error=1.0,
        )
        processor = make_processor(tmp_path, gaia_client=FakeGaiaClient(match))
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is False

    def test_no_gaia_match_gives_unknown(self, tmp_path) -> None:
        processor = make_processor(tmp_path, gaia_client=FakeGaiaClient(None))
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is None
        assert alert.stellar_evidence is None

    def test_thresholds_are_config_driven(self, tmp_path) -> None:
        # SNR ~2 astrometry becomes significant when thresholds drop to 1.
        match = faint_background_gaia_match()
        processor = make_processor(
            tmp_path,
            gaia_client=FakeGaiaClient(match),
            parallax_snr_threshold=0.1,
            pm_snr_threshold=0.1,
        )
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]
        assert alert.is_likely_stellar is True


# ---------------------------------------------------------------------------
# Light-curve features
# ---------------------------------------------------------------------------


class TestLightCurveFeatures:
    def test_features_from_prv_candidates(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        alert = processor.process_batch(make_batch(make_silver_alert())).alerts[0]

        # Current epoch (18.5 @ 2460000.5) + two detections; the magless
        # prv candidate is excluded.
        assert alert.lc_n_detections == 3
        assert alert.lc_time_span_days == pytest.approx(2.0)
        assert alert.lc_mag_brightest == pytest.approx(18.5)
        assert alert.lc_mag_faintest == pytest.approx(19.1)
        assert alert.lc_amplitude == pytest.approx(0.6)
        # Last two epochs: 18.8 -> 18.5 over 1 day = brightening at -0.3 mag/day
        assert alert.lc_mag_rate_per_day == pytest.approx(-0.3)

    def test_single_epoch_defaults(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        silver = make_silver_alert(raw_payload_json=None)
        alert = processor.process_batch(make_batch(silver)).alerts[0]

        assert alert.lc_n_detections == 1
        assert alert.lc_time_span_days == 0.0
        assert alert.lc_amplitude == pytest.approx(0.0)
        assert alert.lc_mag_std == pytest.approx(0.0)
        assert alert.lc_mag_rate_per_day is None

    def test_malformed_payload_is_tolerated(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        silver = make_silver_alert(raw_payload_json="not-json{{{")
        alert = processor.process_batch(make_batch(silver)).alerts[0]
        assert alert.lc_n_detections == 1

    def test_duplicate_epoch_rate_guard(self, tmp_path) -> None:
        payload = json.dumps(
            {"prv_candidates": [{"jd": 2460000.5, "magpsf": 19.0}]}  # same jd as current
        )
        processor = make_processor(tmp_path, enable_crossmatch=False)
        silver = make_silver_alert(raw_payload_json=payload)
        alert = processor.process_batch(make_batch(silver)).alerts[0]
        assert alert.lc_mag_rate_per_day is None  # zero dt guarded


# ---------------------------------------------------------------------------
# Provenance + storage
# ---------------------------------------------------------------------------


class TestProvenanceAndStorage:
    def test_provenance_pointers_carried_not_payload(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        batch = processor.process_batch(make_batch(make_silver_alert()))
        alert = batch.alerts[0]

        assert alert.bronze_processing_id == "bronze_test_001"
        assert alert.silver_processing_id == "silver_test_001"
        assert alert.gold_processing_id == batch.batch_id
        assert alert.raw_payload_hash == "abc123"

        flat = alert.to_flat_dict()
        assert "raw_payload_json" not in flat  # rule: no raw JSON in gold
        assert flat["raw_payload_hash"] == "abc123"

    def test_write_and_read_roundtrip(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        batch = processor.process_batch(
            make_batch(
                make_silver_alert(),
                make_silver_alert(object_id="ZTF21zzz999", candidate_id=999, ra=200.0),
            )
        )
        output = processor.write_batch(batch)
        assert output.exists()

        df = processor.read_gold_data()
        assert len(df) == 2
        assert set(df["object_id"]) == {"ZTF21aaxtctv", "ZTF21zzz999"}
        assert "gaia_source_id" in df.columns
        assert "is_likely_stellar" in df.columns
        assert "raw_payload_json" not in df.columns

    def test_empty_batch_write_is_noop(self, tmp_path) -> None:
        processor = make_processor(tmp_path, enable_crossmatch=False)
        batch = GoldBatch(alerts=[], batch_id="gold_empty")
        assert processor.write_batch(batch) == processor.output_path

    def test_statistics(self, tmp_path) -> None:
        gaia = FakeGaiaClient(match=stellar_gaia_match())
        processor = make_processor(tmp_path, gaia_client=gaia, simbad_client=FakeSimbadClient(None))
        batch = processor.process_batch(make_batch(make_silver_alert()))
        processor.write_batch(batch)

        stats = processor.get_statistics()
        assert stats["total_records"] == 1
        assert stats["gaia_matched"] == 1
        assert stats["simbad_matched"] == 0
        assert stats["likely_stellar"] == 1

    def test_factory(self) -> None:
        processor = create_gold_processor()
        assert isinstance(processor, GoldProcessor)
