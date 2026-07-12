"""Tests for the SIMBAD cross-match client (mocked astroquery calls)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.crossref.simbad_client import SimbadClient
from src.exceptions import SIMBADError
from src.utils.config import CrossmatchSettings

QUERY_RA = 10.6847
QUERY_DEC = 41.2690


def make_client(tmp_path: Path, **settings_overrides) -> SimbadClient:
    settings = CrossmatchSettings(**settings_overrides)
    return SimbadClient(crossmatch_settings=settings, cache_dir=tmp_path / "cache")


def simbad_raw_result() -> pd.DataFrame:
    """Modern astroquery-style result (lowercase columns, degrees)."""
    return pd.DataFrame(
        {
            "main_id": ["M  31", "NAME Andromeda Field Star"],
            "ra": [QUERY_RA + 0.0001, QUERY_RA + 0.0010],
            "dec": [QUERY_DEC, QUERY_DEC],
            "otype": ["G", "*"],
        }
    )


class TestSimbadClientUnit:
    def test_nearest_returns_closest_object(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=simbad_raw_result()):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.main_id == "M  31"
        assert match.otype == "G"
        assert match.separation_arcsec == pytest.approx(0.27, abs=0.05)

    def test_uppercase_legacy_columns_are_normalised(self, tmp_path: Path) -> None:
        raw = simbad_raw_result().rename(
            columns={"main_id": "MAIN_ID", "ra": "RA", "dec": "DEC", "otype": "OTYPE"}
        )
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=raw):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.main_id == "M  31"

    def test_bytes_identifiers_are_decoded(self, tmp_path: Path) -> None:
        raw = simbad_raw_result()
        raw["main_id"] = [b"M  31", b"Other"]
        raw["otype"] = [b"G", b"*"]
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=raw):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.main_id == "M  31"
        assert match.otype == "G"

    def test_missing_otype_becomes_none(self, tmp_path: Path) -> None:
        raw = simbad_raw_result()
        raw["otype"] = [np.nan, np.nan]
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=raw):
            match = client.nearest(ra=QUERY_RA, dec=QUERY_DEC)

        assert match is not None
        assert match.otype is None

    def test_nearest_returns_none_on_empty_result(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=pd.DataFrame()):
            assert client.nearest(ra=QUERY_RA, dec=QUERY_DEC) is None

    def test_cache_avoids_second_query(self, tmp_path: Path) -> None:
        client = make_client(tmp_path, cache_enabled=True)
        with patch.object(
            SimbadClient, "_query_region", return_value=simbad_raw_result()
        ) as mock_query:
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)
        assert mock_query.call_count == 1

    def test_legacy_sexagesimal_schema_does_not_crash(self, tmp_path: Path) -> None:
        # Older astroquery (still pip-allowed) returned uppercase columns with
        # sexagesimal string coordinates. This must degrade to a usable match
        # (with computed separation), never raise and abort the gold batch.
        legacy = pd.DataFrame(
            {
                "MAIN_ID": ["3C 273"],
                "RA": ["12 29 06.6997"],  # hours
                "DEC": ["+02 03 08.598"],  # degrees
                "OTYPE": ["QSO"],
            }
        )
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=legacy):
            match = client.nearest(ra=187.27792, dec=2.05239)

        assert match is not None
        assert match.main_id == "3C 273"
        assert match.otype == "QSO"
        assert match.ra == pytest.approx(187.278, abs=1e-2)
        assert match.separation_arcsec < 5.0

    def test_unparseable_coordinates_yield_no_match(self, tmp_path: Path) -> None:
        garbage = pd.DataFrame({"main_id": ["X"], "ra": ["???"], "dec": ["???"], "otype": ["*"]})
        client = make_client(tmp_path)
        with patch.object(SimbadClient, "_query_region", return_value=garbage):
            # No usable position -> graceful None, not a crash / validation error.
            assert client.nearest(ra=187.27792, dec=2.05239) is None

    def test_query_failure_raises_simbad_error(self, tmp_path: Path) -> None:
        client = make_client(tmp_path)
        with (
            patch.object(SimbadClient, "_query_region", side_effect=RuntimeError("SIMBAD down")),
            pytest.raises(SIMBADError) as exc_info,
        ):
            client.cone_search(ra=QUERY_RA, dec=QUERY_DEC)

        assert exc_info.value.details["ra"] == QUERY_RA
