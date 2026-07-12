"""Tests for the Fink REST API client.

Includes both unit tests (mocked HTTP) and integration tests (live API).
Integration tests are marked with @pytest.mark.integration and require
network access.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import pytest
import requests
import responses

from src.ingestion.fink_api_client import (
    FinkAPIClient,
    FinkAPIConfig,
    FinkClass,
    canonicalize_fink_alert_record,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client() -> FinkAPIClient:
    """Create a FinkAPIClient with default configuration."""
    return FinkAPIClient()


@pytest.fixture
def sample_alert_json() -> list[dict]:
    """Sample alert data mimicking Fink API response."""
    return [
        {
            "objectId": "ZTF21aaxtctv",
            "candid": 1549473362115015004,
            "ra": 193.822,
            "dec": 2.896,
            "magpsf": 18.5,
            "sigmapsf": 0.05,
            "fid": 1,
            "jd": 2459500.5,
            "v:classification": "SN candidate",
        },
        {
            "objectId": "ZTF21aaxtctv",
            "candid": 1549473362115015005,
            "ra": 193.822,
            "dec": 2.896,
            "magpsf": 18.3,
            "sigmapsf": 0.04,
            "fid": 2,
            "jd": 2459501.5,
            "v:classification": "SN candidate",
        },
    ]


# =============================================================================
# Unit Tests (mocked HTTP)
# =============================================================================


class TestFinkAPIClientUnit:
    """Unit tests with mocked HTTP responses."""

    def test_canonicalize_prefixed_fink_record(self) -> None:
        """Live Fink prefixed fields should map to canonical Bronze fields."""
        raw = {
            "i:objectId": "ZTF26abc",
            "i:candid": 3396516274715015009,
            "i:ra": 264.86,
            "i:dec": 5.01,
            "i:magpsf": 18.2,
            "i:sigmapsf": 0.08,
            "i:fid": 2,
            "i:jd": 2461151.01,
            "i:rb": 0.92,
            "i:drb": 0.99,
            "v:classification": "SN candidate",
            "d:cdsxmatch": "Unknown",
        }

        canonical = canonicalize_fink_alert_record(raw)

        assert canonical["objectId"] == "ZTF26abc"
        assert canonical["candid"] == 3396516274715015009
        assert canonical["ra"] == 264.86
        assert canonical["dec"] == 5.01
        assert canonical["magpsf"] == 18.2
        assert canonical["sigmapsf"] == 0.08
        assert canonical["fid"] == 2
        assert canonical["jd"] == 2461151.01
        assert canonical["rb"] == 0.92
        assert canonical["drb"] == 0.99
        assert canonical["v:fink_class"] == "SN candidate"
        assert canonical["_fink_raw_payload"] == raw

    def test_canonicalize_preserves_unprefixed_record(self) -> None:
        """Existing unprefixed test records should still pass through."""
        raw = {
            "objectId": "ZTF21aaxtctv",
            "candid": 123,
            "ra": 193.822,
            "dec": 2.896,
            "magpsf": 18.5,
            "sigmapsf": 0.05,
            "fid": 1,
            "jd": 2459500.5,
            "v:fink_class": "SN candidate",
        }

        canonical = canonicalize_fink_alert_record(raw)

        assert canonical["objectId"] == raw["objectId"]
        assert canonical["v:fink_class"] == "SN candidate"
        assert canonical["_fink_raw_payload"] == raw

    def test_config_defaults(self) -> None:
        """Default configuration should use Fink's public API."""
        config = FinkAPIConfig()
        assert config.base_url == "https://api.fink-portal.org"
        assert config.api_version == "v1"
        assert config.timeout_seconds == 30

    def test_config_custom(self) -> None:
        """Custom configuration should override defaults."""
        config = FinkAPIConfig(
            base_url="http://localhost:8080",
            timeout_seconds=60,
        )
        assert config.base_url == "http://localhost:8080"
        assert config.timeout_seconds == 60

    def test_endpoint_construction(self, client: FinkAPIClient) -> None:
        """Endpoint URL should be correctly constructed."""
        url = client._endpoint("objects")
        assert url == "https://api.fink-portal.org/api/v1/objects"

    @responses.activate
    def test_get_object_success(
        self,
        client: FinkAPIClient,
        sample_alert_json: list[dict],
    ) -> None:
        """Successfully retrieve alerts for a known object."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/objects",
            json=sample_alert_json,
            status=200,
        )

        df = client.get_object("ZTF21aaxtctv")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "objectId" in df.columns
        assert df.iloc[0]["objectId"] == "ZTF21aaxtctv"

    @responses.activate
    def test_get_object_empty_response(self, client: FinkAPIClient) -> None:
        """Empty response should return empty DataFrame."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/objects",
            body=b"",
            status=200,
        )

        df = client.get_object("ZTF_NONEXISTENT")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    @responses.activate
    def test_get_latest_alerts(
        self,
        client: FinkAPIClient,
        sample_alert_json: list[dict],
    ) -> None:
        """Retrieve latest alerts for a specific classification."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/latests",
            json=sample_alert_json,
            status=200,
        )

        df = client.get_latest_alerts(FinkClass.SN_CANDIDATE, n=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

    @responses.activate
    def test_get_latest_alert_records(self, client: FinkAPIClient) -> None:
        """Latest alert records should be canonicalized for Bronze."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/latests",
            json=[
                {
                    "i:objectId": "ZTF26abc",
                    "i:candid": 1,
                    "i:ra": 10.0,
                    "i:dec": 20.0,
                    "i:magpsf": 18.0,
                    "i:sigmapsf": 0.1,
                    "i:fid": 1,
                    "i:jd": 2461151.0,
                    "v:classification": "SN candidate",
                }
            ],
            status=200,
        )

        records = client.get_latest_alert_records(FinkClass.SN_CANDIDATE, n=1)

        assert records[0]["objectId"] == "ZTF26abc"
        assert records[0]["v:fink_class"] == "SN candidate"
        request_body = json.loads(responses.calls[0].request.body)
        assert "columns" not in request_body

    @responses.activate
    def test_cone_search(
        self,
        client: FinkAPIClient,
        sample_alert_json: list[dict],
    ) -> None:
        """Cone search should return alerts within radius."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/explorer",
            json=sample_alert_json,
            status=200,
        )

        df = client.cone_search(ra=193.822, dec=2.896, radius_arcsec=5.0)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

    @responses.activate
    def test_http_error_raises(self, client: FinkAPIClient) -> None:
        """HTTP errors should be raised after retries exhausted."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/objects",
            status=500,
        )

        with pytest.raises(requests.HTTPError):
            client.get_object("ZTF21aaxtctv")

    @responses.activate
    def test_column_filtering(
        self,
        client: FinkAPIClient,
        sample_alert_json: list[dict],
    ) -> None:
        """Column filtering should be passed in the request."""
        responses.add(
            responses.POST,
            "https://api.fink-portal.org/api/v1/objects",
            json=sample_alert_json,
            status=200,
        )

        df = client.get_object("ZTF21aaxtctv", columns=["objectId", "magpsf"])
        assert isinstance(df, pd.DataFrame)

        # Verify the request included the columns parameter
        request_body = json.loads(responses.calls[0].request.body)
        assert "columns" in request_body
        assert request_body["columns"] == "objectId,magpsf"

    def test_fink_class_enum(self) -> None:
        """FinkClass enum should have correct string values."""
        assert FinkClass.EARLY_SN_IA.value == "Early SN Ia candidate"
        assert FinkClass.KILONOVA.value == "Kilonova candidate"
        assert FinkClass.UNKNOWN.value == "Unknown"


# =============================================================================
# Integration Tests (live API)
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGD_RUN_INTEGRATION_TESTS") != "1",
    reason="Set AGD_RUN_INTEGRATION_TESTS=1 to run live Fink API tests.",
)
class TestFinkAPIClientIntegration:
    """Integration tests against the live Fink API.

    These tests require network access and hit the real Fink API.
    Run with: pytest -m integration
    """

    def test_health_check(self, client: FinkAPIClient) -> None:
        """Fink API should be reachable."""
        assert client.health_check() is True

    def test_get_known_object(self, client: FinkAPIClient) -> None:
        """Retrieve a well-known ZTF object."""
        df = client.get_object("ZTF21aaxtctv")
        assert len(df) > 0
        assert "objectId" in df.columns

    def test_get_latest_sn_candidates(self, client: FinkAPIClient) -> None:
        """Retrieve recent supernova candidates."""
        df = client.get_latest_alerts(FinkClass.SN_CANDIDATE, n=5)
        assert len(df) > 0

    def test_cone_search_known_location(self, client: FinkAPIClient) -> None:
        """Cone search at a known active sky location."""
        # M31 (Andromeda Galaxy) center — should have many detections
        df = client.cone_search(ra=10.6847, dec=41.2687, radius_arcsec=60)
        # Don't assert exact count — just that we get results
        assert isinstance(df, pd.DataFrame)
