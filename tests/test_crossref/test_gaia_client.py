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
from src.crossref.utils import angular_separation_arcsec, none_if_nan, query_cache_key
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


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGD_RUN_INTEGRATION_TESTS") != "1",
    reason="Set AGD_RUN_INTEGRATION_TESTS=1 to run live Gaia TAP tests.",
)
class TestGaiaClientIntegration:
    """Live Gaia TAP integration test with a tiny cone.

    Run with: AGD_RUN_INTEGRATION_TESTS=1 pytest -m integration
    """

    def test_live_cone_search_barnards_star(self, tmp_path: Path) -> None:
        # Barnard's Star: bright, isolated, huge parallax and proper motion.
        client = make_client(tmp_path, radius_arcsec=30.0)
        match = client.nearest(ra=269.45207, dec=4.69339, radius_arcsec=30.0)

        assert match is not None
        assert match.separation_arcsec < 30.0
        assert match.parallax is not None and match.parallax > 100  # ~547 mas
        assert match.pm_total is not None and match.pm_total > 1000  # ~10 arcsec/yr
