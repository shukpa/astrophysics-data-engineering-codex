"""Tests for the Gaia DR3 cross-match client.

Unit tests replace the isolated astroquery call (``_execute_adql``) with
canned results, so no network access is required. One integration test
(marked, env-gated) hits the live Gaia TAP service with a tiny cone.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.crossref.gaia_client import GaiaClient
from src.crossref.utils import (
    angular_separation_arcsec,
    coord_to_degrees,
    none_if_nan,
    query_cache_key,
)
from src.exceptions import CrossReferenceError, GaiaError
from src.utils.config import CrossmatchSettings

QUERY_RA = 193.822
QUERY_DEC = 2.896


def make_client(tmp_path: Path, **settings_overrides) -> GaiaClient:
    settings = CrossmatchSettings(**settings_overrides)
    return GaiaClient(crossmatch_settings=settings, cache_dir=tmp_path / "cache")


def gaia_raw_result() -> pd.DataFrame:
    """Raw astroquery-style result: two sources, farther one listed first."""
    return pd.DataFrame(
        {
            "SOURCE_ID": [222, 111],
            "ra": [QUERY_RA + 0.0010, QUERY_RA + 0.0001],
            "dec": [QUERY_DEC, QUERY_DEC],
            "phot_g_mean_mag": [17.2, 15.5],
            "parallax": [np.nan, 12.0],
            "parallax_error": [np.nan, 0.5],
            "pmra": [np.nan, 80.0],
            "pmra_error": [np.nan, 1.0],
            "pmdec": [np.nan, -60.0],
            "pmdec_error": [np.nan, 1.0],
        }
    )


class TestGaiaClientUnit:
    """Unit tests with mocked TAP responses."""

    def test_cone_search_normalises_and_sorts_by_separation(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(GaiaClient, "_execute_adql", return_value=gaia_raw_result()):
            df = client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

        assert list(df["source_id"]) == [111, 222]  # nearest first
        assert "separation_arcsec" in df.columns
        assert df["separation_arcsec"].iloc[0] < df["separation_arcsec"].iloc[1]
        # ~0.0001 deg at this dec is ~0.36 arcsec
        assert df["separation_arcsec"].iloc[0] == pytest.approx(0.36, abs=0.05)

    def test_nearest_returns_match_with_nan_converted_to_none(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(GaiaClient, "_execute_adql", return_value=gaia_raw_result()):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.source_id == 111
        assert match.g_mag == pytest.approx(15.5)
        assert match.parallax == pytest.approx(12.0)
        assert match.parallax_snr == pytest.approx(24.0)
        assert match.pm_total == pytest.approx(100.0)

    def test_nearest_nan_astrometry_becomes_none(self, tmp_path: Path) -> None:
        raw = gaia_raw_result()
        raw = raw[raw["SOURCE_ID"] == 222].reset_index(drop=True)  # the NaN row
        client = make_client(tmp_path)
        with patch.object(GaiaClient, "_execute_adql", return_value=raw):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.parallax is None
        assert match.parallax_snr is None
        assert match.pm_total is None
        assert match.pm_snr is None

    def test_nearest_returns_none_on_empty_cone(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(GaiaClient, "_execute_adql", return_value=pd.DataFrame()):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)
        assert match is None

    def test_cache_avoids_second_query(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, cache_enabled=True)
        with patch.object(
            GaiaClient, "_execute_adql", return_value=gaia_raw_result()
        ) as mock_query:
            first = client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
            second = client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

        assert mock_query.call_count == 1
        pd.testing.assert_frame_equal(first, second)

    def test_cache_shared_across_client_instances(self, tmp_path: Path) -> None:
        first_client = make_client(tmp_path, cache_enabled=True)
        with patch.object(
            GaiaClient, "_execute_adql", return_value=gaia_raw_result()
        ) as mock_query:
            first_client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

            second_client = make_client(tmp_path, cache_enabled=True)
            second_client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

        assert mock_query.call_count == 1

    def test_empty_results_are_cached_too(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, cache_enabled=True)
        with patch.object(GaiaClient, "_execute_adql", return_value=pd.DataFrame()) as mock_query:
            assert client.nearest(ra=QUERY_RA, dec=QUERY_DEC) is None
            assert client.nearest(ra=QUERY_RA, dec=QUERY_DEC) is None
        assert mock_query.call_count == 1

    def test_cache_disabled_queries_every_time(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, cache_enabled=False)
        with patch.object(
            GaiaClient, "_execute_adql", return_value=gaia_raw_result()
        ) as mock_query:
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
        assert mock_query.call_count == 2

    def test_query_failure_raises_gaia_error_with_details(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with (
            patch.object(GaiaClient, "_execute_adql", side_effect=ValueError("TAP down")),
            pytest.raises(GaiaError) as exc_info,
        ):
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

        assert isinstance(exc_info.value, CrossReferenceError)
        assert exc_info.value.details["ra"] == QUERY_RA

    def test_build_query_uses_config(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, gaia_catalog="gaiadr3.gaia_source", gaia_max_rows=7)
        query = client._build_query(QUERY_RA, QUERY_DEC, 5.0)
        assert "SELECT TOP 7" in query
        assert "FROM gaiadr3.gaia_source" in query
        assert "CIRCLE" in query

    def test_build_query_orders_by_distance(self, tmp_path: Path) -> None:
        # TOP must select the NEAREST rows, so the query orders by an aliased
        # distance (a bare function in ORDER BY is rejected by Gaia's parser).
        client = make_client(tmp_path)
        query = client._build_query(QUERY_RA, QUERY_DEC, 5.0)
        assert "AS dist" in query
        assert "ORDER BY dist" in query
        assert query.index("ORDER BY") > query.index("WHERE")

    def test_normalise_drops_server_distance_column(self, tmp_path: Path) -> None:
        raw = gaia_raw_result()
        raw["dist"] = [0.002, 0.0005]  # server-side ORDER BY helper column
        client = make_client(tmp_path)
        with patch.object(GaiaClient, "_execute_adql", return_value=raw):
            df = client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
        assert "dist" not in df.columns
        assert "separation_arcsec" in df.columns

    def test_execute_adql_enters_proxy_tunnel_when_configured(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import contextlib
        import sys
        import types

        import astropy.table

        calls: dict[str, str | None] = {}

        @contextlib.contextmanager
        def spy_tunnel(url, ca_bundle=None):
            calls["url"] = url
            calls["ca"] = ca_bundle
            yield

        monkeypatch.setattr("src.crossref.gaia_client.tap_proxy_tunnel", spy_tunnel)

        class FakeJob:
            def get_results(self):
                return astropy.table.Table(
                    {
                        "source_id": [1],
                        "ra": [QUERY_RA],
                        "dec": [QUERY_DEC],
                        "phot_g_mean_mag": [15.0],
                        "parallax": [1.0],
                        "parallax_error": [0.1],
                        "pmra": [1.0],
                        "pmra_error": [0.1],
                        "pmdec": [1.0],
                        "pmdec_error": [0.1],
                    }
                )

        fake_gaia = types.ModuleType("astroquery.gaia")
        fake_gaia.Gaia = types.SimpleNamespace(launch_job=lambda _query: FakeJob())
        monkeypatch.setitem(sys.modules, "astroquery.gaia", fake_gaia)

        client = make_client(
            tmp_path, tap_proxy_url="http://127.0.0.1:36389", tap_ca_bundle="/root/.ccr/ca.crt"
        )
        match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert calls == {"url": "http://127.0.0.1:36389", "ca": "/root/.ccr/ca.crt"}
        assert match is not None and match.source_id == 1


class TestCrossrefUtils:
    """Tests for shared cross-reference helpers."""

    def test_none_if_nan(self) -> None:
        assert none_if_nan(float("nan")) is None
        assert none_if_nan(np.nan) is None
        assert none_if_nan(None) is None
        assert none_if_nan(1.5) == 1.5
        assert none_if_nan("QSO") == "QSO"

    def test_angular_separation_matches_known_value(self) -> None:
        # 0.001 deg offset in dec = 3.6 arcsec exactly.
        sep = angular_separation_arcsec(10.0, 20.0, 10.0, 20.001)
        assert sep == pytest.approx(3.6, abs=1e-6)

    def test_query_cache_key_is_stable_and_distinct(self) -> None:
        key1 = query_cache_key("gaia", 10.0, 20.0, 5.0)
        key2 = query_cache_key("gaia", 10.0, 20.0, 5.0)
        key3 = query_cache_key("gaia", 10.0, 20.1, 5.0)
        assert key1 == key2
        assert key1 != key3

    def test_coord_to_degrees_passthrough_and_none(self) -> None:
        assert coord_to_degrees(187.27792, is_ra=True) == pytest.approx(187.27792)
        assert coord_to_degrees(2.05239, is_ra=False) == pytest.approx(2.05239)
        assert coord_to_degrees(None, is_ra=True) is None
        assert coord_to_degrees(np.nan, is_ra=False) is None
        assert coord_to_degrees("not-a-coord", is_ra=True) is None

    def test_coord_to_degrees_parses_legacy_sexagesimal(self) -> None:
        # Legacy SIMBAD strings: RA in hours, Dec in degrees.
        # 12:29:06.7 h = 187.278 deg; +02:03:08.6 deg = 2.052 deg.
        assert coord_to_degrees("12 29 06.70", is_ra=True) == pytest.approx(187.278, abs=1e-2)
        assert coord_to_degrees("+02 03 08.6", is_ra=False) == pytest.approx(2.052, abs=1e-2)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGD_RUN_INTEGRATION_TESTS") != "1",
    reason="Set AGD_RUN_INTEGRATION_TESTS=1 to run live Gaia TAP tests.",
)
class TestGaiaClientIntegration:
    """Live Gaia TAP integration test with a tiny cone.

    Run with: AGD_RUN_INTEGRATION_TESTS=1 pytest -m integration

    In a CONNECT-proxy environment (astroquery ignores HTTPS_PROXY), also set
    CROSSMATCH_TAP_PROXY_URL (and CROSSMATCH_TAP_CA_BUNDLE if the proxy
    re-terminates TLS); make_client reads them from env via CrossmatchSettings.

    Target is 3C 273 — a quasar with no measurable proper motion, so its Gaia
    DR3 (epoch 2016) position coincides with its ICRS catalog position. High
    proper-motion stars are deliberately avoided: their epoch-2016 position can
    sit arcminutes from their J2000 coordinates, outside any small cone.
    """

    # 3C 273 (ICRS, J2000): bright quasar, motionless, always in the catalog.
    THREE_C_273_RA = 187.27792
    THREE_C_273_DEC = 2.05239

    def test_live_cone_search_quasar(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, radius_arcsec=5.0)
        match = client.nearest(ra=self.THREE_C_273_RA, dec=self.THREE_C_273_DEC)

        # Connectivity + real astrometry returned for a known source.
        assert match is not None
        assert match.source_id > 0
        assert match.separation_arcsec < 5.0
        assert match.g_mag is not None and 11.0 < match.g_mag < 14.0  # ~12.8

        # Physics: an extragalactic source shows no significant parallax, so it
        # must NOT read as stellar via the parallax channel.
        if match.parallax_snr is not None:
            assert not (
                match.parallax is not None and match.parallax > 0 and match.parallax_snr >= 5.0
            )
