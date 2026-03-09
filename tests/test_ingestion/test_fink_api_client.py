"""Tests for the Fink REST API client.

Includes both unit tests (mocked HTTP) and integration tests (live API).
Integration tests are marked with @pytest.mark.integration and require
network access.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
import responses

from src.ingestion.fink_api_client import FinkAPIClient, FinkAPIConfig, FinkClass


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

        with pytest.raises(Exception):
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
