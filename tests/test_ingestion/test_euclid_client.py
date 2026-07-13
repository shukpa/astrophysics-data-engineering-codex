"""Tests for the Euclid archive TAP client.

Unit tests replace the isolated astroquery call (``_execute_adql``) with
canned results — no network access. Env-gated integration tests hit the
live ESA TAP service (schema discovery + a tiny MER cone).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.exceptions import EuclidAPIError, IngestionError
from src.ingestion.euclid_client import MER_COLUMNS, EuclidClient
from src.utils.config import EuclidSettings

EDF_F_RA = 52.93
EDF_F_DEC = -28.09


def make_client(tmp_path: Path, **settings_overrides) -> EuclidClient:
    settings = EuclidSettings(**settings_overrides)
    return EuclidClient(euclid_settings=settings, cache_dir=tmp_path / "cache")


def mer_raw_result() -> pd.DataFrame:
    """Raw astroquery-style MER rows (uppercase columns to exercise rename)."""
    return pd.DataFrame(
        {
            "OBJECT_ID": [27001, 27002],
            "RIGHT_ASCENSION": [EDF_F_RA + 0.001, EDF_F_RA - 0.002],
            "DECLINATION": [EDF_F_DEC, EDF_F_DEC + 0.001],
            "FLUX_VIS_PSF": [1.2, 3.4],
            "FLUX_Y_TEMPLFIT": [1.0, 2.0],
            "FLUX_J_TEMPLFIT": [1.1, 2.1],
            "FLUX_H_TEMPLFIT": [0.9, 1.9],
            "POINT_LIKE_PROB": [0.1, 0.9],
            "SPURIOUS_PROB": [0.02, 0.01],
        }
    )


class TestEuclidClientUnit:
    def test_build_mer_query_uses_config(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, mer_table="catalogue.mer_catalogue", max_rows=42)
        query = client._build_mer_query(EDF_F_RA, EDF_F_DEC, 0.1, MER_COLUMNS)
        assert "SELECT TOP 42" in query
        assert "FROM catalogue.mer_catalogue" in query
        assert "CONTAINS" in query and "CIRCLE" in query
        assert "right_ascension" in query and "declination" in query

    def test_cone_search_returns_rows_and_provenance(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, dr_tag="Q1")
        with patch.object(EuclidClient, "_execute_adql", return_value=mer_raw_result()):
            df, provenance = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.1)

        assert len(df) == 2
        assert list(df.columns) == [c.lower() for c in mer_raw_result().columns]
        assert provenance["source"] == "esa_euclid_tap"
        assert provenance["table"] == "catalogue.mer_catalogue"
        assert provenance["dr_tag"] == "Q1"
        assert provenance["row_count"] == 2
        assert provenance["cache_hit"] is False
        assert "SELECT TOP" in provenance["query"]
        assert provenance["retrieved_at"]  # ISO timestamp present

    def test_cache_serves_second_call_and_marks_provenance(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(
            EuclidClient, "_execute_adql", return_value=mer_raw_result()
        ) as mock_query:
            first, prov1 = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.1)
            second, prov2 = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.1)

        assert mock_query.call_count == 1
        pd.testing.assert_frame_equal(first, second)
        assert prov1["cache_hit"] is False
        assert prov2["cache_hit"] is True

    def test_dr_tag_flows_from_config(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, dr_tag="DR1F")
        with patch.object(EuclidClient, "_execute_adql", return_value=mer_raw_result()):
            _, provenance = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC)
        assert provenance["dr_tag"] == "DR1F"

    def test_cache_key_segregated_by_dr_tag(self, tmp_path: Path) -> None:
        # Same cone + same cache dir, different DR tags: the DR1F pull must NOT
        # reuse the Q1 parquet (which would stamp stale Q1 rows as DR1F).
        cache_dir = tmp_path / "shared_cache"
        q1 = EuclidClient(euclid_settings=EuclidSettings(dr_tag="Q1"), cache_dir=cache_dir)
        dr1f = EuclidClient(euclid_settings=EuclidSettings(dr_tag="DR1F"), cache_dir=cache_dir)

        query = q1._build_mer_query(EDF_F_RA, EDF_F_DEC, 0.1, MER_COLUMNS)
        assert q1._cache_file(query) != dr1f._cache_file(query)

        with patch.object(
            EuclidClient, "_execute_adql", return_value=mer_raw_result()
        ) as mock_query:
            _, prov_q1 = q1.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.1)
            _, prov_dr1f = dr1f.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.1)

        assert mock_query.call_count == 2  # no cross-release cache collision
        assert prov_q1["dr_tag"] == "Q1"
        assert prov_dr1f["dr_tag"] == "DR1F"
        assert prov_dr1f["cache_hit"] is False

    def test_execute_adql_applies_timeout_and_proxy(self, tmp_path: Path, monkeypatch) -> None:
        import contextlib
        import sys
        import types

        import astropy.table

        calls: dict[str, object] = {}

        @contextlib.contextmanager
        def spy_timeout(seconds):
            calls["timeout"] = seconds
            yield

        @contextlib.contextmanager
        def spy_tunnel(url, ca_bundle=None):
            calls["proxy"] = (url, ca_bundle)
            yield

        monkeypatch.setattr("src.ingestion.euclid_client.tap_socket_timeout", spy_timeout)
        monkeypatch.setattr("src.ingestion.euclid_client.tap_proxy_tunnel", spy_tunnel)

        class FakeJob:
            def get_results(self):
                return astropy.table.Table(
                    {
                        "object_id": [1],
                        "right_ascension": [EDF_F_RA],
                        "declination": [EDF_F_DEC],
                    }
                )

        fake = types.ModuleType("astroquery.esa.euclid")
        fake.Euclid = types.SimpleNamespace(launch_job=lambda _query: FakeJob())
        monkeypatch.setitem(sys.modules, "astroquery.esa.euclid", fake)

        client = make_client(
            tmp_path,
            timeout_seconds=123,
            tap_proxy_url="http://127.0.0.1:36389",
            tap_ca_bundle="/root/.ccr/ca.crt",
        )
        df, _ = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC)

        assert calls["timeout"] == 123
        assert calls["proxy"] == ("http://127.0.0.1:36389", "/root/.ccr/ca.crt")
        assert len(df) == 1

    def test_query_failure_raises_euclid_api_error(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with (
            patch.object(EuclidClient, "_execute_adql", side_effect=ValueError("TAP down")),
            pytest.raises(EuclidAPIError) as exc_info,
        ):
            client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC)

        assert isinstance(exc_info.value, IngestionError)
        assert exc_info.value.details["ra"] == EDF_F_RA

    def test_discover_tables_wraps_errors(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with (
            patch.object(EuclidClient, "_execute_adql", side_effect=RuntimeError("boom")),
            pytest.raises(EuclidAPIError),
        ):
            client.discover_tables("catalogue")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGD_RUN_INTEGRATION_TESTS") != "1",
    reason="Set AGD_RUN_INTEGRATION_TESTS=1 to run live Euclid TAP tests.",
)
class TestEuclidClientIntegration:
    """Live ESA Euclid TAP tests.

    Behind a CONNECT proxy also set EUCLID_TAP_PROXY_URL (and
    EUCLID_TAP_CA_BUNDLE if the proxy re-terminates TLS).
    """

    def test_live_schema_discovery_finds_mer_table(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        tables = client.discover_tables("catalogue")
        names = set(tables[tables.columns[0]].astype(str))
        assert "catalogue.mer_catalogue" in names

    def test_live_mer_cone_returns_rows(self, tmp_path: Path) -> None:
        # Tiny cone at the EDF-F centre: guaranteed on-footprint for Q1.
        client = make_client(tmp_path, max_rows=25)
        df, provenance = client.mer_cone_search(ra=EDF_F_RA, dec=EDF_F_DEC, radius_deg=0.02)
        assert len(df) > 0
        for column in MER_COLUMNS:
            assert column in df.columns
        assert provenance["row_count"] == len(df)
