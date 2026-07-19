"""Fink REST API client for retrieving astronomical transient alerts.

This module provides a robust client for the Fink broker REST API,
which serves processed ZTF (and soon Rubin/LSST) alert data.

API Documentation: https://fink-broker.readthedocs.io
API Base URL: https://api.ztf.fink-portal.org

No authentication is required for the REST API.
"""

from __future__ import annotations

import io
import logging
from enum import StrEnum
from typing import Any, Literal

import pandas as pd
import requests
from pydantic import BaseModel, Field
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.exceptions import FinkAPIError
from src.utils.config import get_settings

logger = logging.getLogger(__name__)


FINK_TO_CANONICAL_FIELDS = {
    "i:objectId": "objectId",
    "i:candid": "candid",
    "i:ra": "ra",
    "i:dec": "dec",
    "i:magpsf": "magpsf",
    "i:sigmapsf": "sigmapsf",
    "i:fid": "fid",
    "i:jd": "jd",
    "i:diffmaglim": "diffmaglim",
    "i:rb": "rb",
    "i:drb": "drb",
    "i:prv_candidates": "prv_candidates",
}


def canonicalize_fink_alert_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a Fink REST alert record into the canonical ZTF alert shape.

    Fink's live API exposes ZTF packet fields with prefixes such as ``i:`` for
    instrument data and ``v:`` for value-added broker fields. The pipeline's
    Bronze model intentionally uses unprefixed canonical names.
    """
    canonical = dict(record)

    for fink_field, canonical_field in FINK_TO_CANONICAL_FIELDS.items():
        if canonical_field not in canonical and fink_field in record:
            canonical[canonical_field] = record[fink_field]

    if "v:fink_class" not in canonical:
        classification = record.get("v:classification")
        if classification is not None:
            canonical["v:fink_class"] = classification

    if "d:cdsxmatch" in record:
        canonical["d:cdsxmatch"] = record["d:cdsxmatch"]

    canonical["_fink_raw_payload"] = dict(record)
    return canonical


class FinkClass(StrEnum):
    """Fink transient classification labels."""

    SN_CANDIDATE = "SN candidate"
    EARLY_SN_IA = "Early SN Ia candidate"
    KILONOVA = "Kilonova candidate"
    MICROLENSING = "Microlensing candidate"
    AGN = "AGN"
    QSO = "QSO"
    VARIABLE_STAR = "Variable Star"
    CATACLYSMIC_VARIABLE = "Cataclysmic Variable"
    YSO = "YSO"
    SOLAR_SYSTEM_MPC = "Solar System MPC"
    SOLAR_SYSTEM_CANDIDATE = "Solar System candidate"
    UNKNOWN = "Unknown"


class FinkAPIConfig(BaseModel):
    """Configuration for the Fink API client."""

    base_url: str = "https://api.ztf.fink-portal.org"
    api_version: str = "v1"
    output_format: Literal["json"] = "json"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_factor: float = Field(default=2.0, ge=0, le=30)


def _is_retryable_error(exc: BaseException) -> bool:
    """Return whether a Fink request failure is transient."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


class FinkAPIClient:
    """Client for the Fink broker REST API.

    Provides methods to query ZTF transient alerts through Fink's
    public REST API. Includes retry logic, timeout handling, and
    response validation.

    Example:
        >>> client = FinkAPIClient()
        >>> alerts = client.get_object("ZTF21aaxtctv")
        >>> latest = client.get_latest_alerts(FinkClass.EARLY_SN_IA, n=10)
    """

    def __init__(self, config: FinkAPIConfig | None = None) -> None:
        if config is None:
            settings = get_settings().fink
            config = FinkAPIConfig(
                base_url=settings.base_url,
                output_format=settings.default_output_format,
                timeout_seconds=settings.timeout_seconds,
                max_retries=settings.max_retries,
                retry_backoff_factor=settings.retry_backoff_base,
            )
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        logger.info(
            "FinkAPIClient initialized",
            extra={"base_url": self.config.base_url},
        )

    def _endpoint(self, path: str) -> str:
        """Construct full API endpoint URL."""
        return f"{self.config.base_url}/api/{self.config.api_version}/{path}"

    def _post(self, endpoint: str, payload: dict[str, Any]) -> requests.Response:
        """Make a POST request with retry logic.

        Args:
            endpoint: API endpoint path.
            payload: JSON payload for the request.

        Returns:
            Response object from the API.

        Raises:
            requests.HTTPError: If the API returns an error status code.
            requests.Timeout: If the request times out after retries.
        """
        url = self._endpoint(endpoint)
        logger.debug("POST %s", url, extra={"payload_keys": list(payload.keys())})

        retrying = Retrying(
            retry=retry_if_exception(_is_retryable_error),
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(
                multiplier=self.config.retry_backoff_factor,
                min=0,
                max=30,
            ),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                return response
        raise FinkAPIError("Fink request did not produce a response", endpoint=url)

    def _response_to_dataframe(self, response: requests.Response) -> pd.DataFrame:
        """Convert API response to a pandas DataFrame.

        Args:
            response: HTTP response from Fink API.

        Returns:
            DataFrame containing the alert data.
        """
        if not response.content:
            logger.warning("Empty response from Fink API")
            return pd.DataFrame()

        try:
            df = pd.read_json(io.BytesIO(response.content))
            logger.info("Retrieved %d alerts from Fink", len(df))
            return df
        except ValueError as exc:
            logger.error("Failed to parse Fink response: %s", exc)
            raise FinkAPIError(
                "Malformed JSON response from Fink API",
                endpoint=response.url,
                details={"output_format": self.config.output_format},
            ) from exc

    def get_object(self, object_id: str, columns: list[str] | None = None) -> pd.DataFrame:
        """Retrieve all alerts for a specific ZTF object.

        Args:
            object_id: ZTF object identifier (e.g., "ZTF21aaxtctv").
            columns: Optional list of specific columns to retrieve.

        Returns:
            DataFrame where each row is an alert for this object,
            ordered chronologically.

        Example:
            >>> client = FinkAPIClient()
            >>> alerts = client.get_object("ZTF21aaxtctv")
            >>> print(f"Object has {len(alerts)} alerts")
        """
        payload: dict[str, Any] = {
            "objectId": object_id,
            "output-format": self.config.output_format,
        }
        if columns:
            payload["columns"] = ",".join(columns)

        logger.info("Fetching object %s", object_id)
        response = self._post("objects", payload)
        return self._response_to_dataframe(response)

    def get_latest_alerts(
        self,
        fink_class: FinkClass | str,
        n: int = 10,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Retrieve the N most recent alerts for a given classification.

        Args:
            fink_class: Fink classification label to filter by.
            n: Number of recent alerts to retrieve (default: 10).
            columns: Optional list of specific columns to retrieve.

        Returns:
            DataFrame containing the most recent alerts of the given class.

        Example:
            >>> client = FinkAPIClient()
            >>> sne = client.get_latest_alerts(FinkClass.EARLY_SN_IA, n=20)
        """
        class_str = fink_class.value if isinstance(fink_class, FinkClass) else fink_class
        payload: dict[str, Any] = {
            "class": class_str,
            "n": str(n),
            "output-format": self.config.output_format,
        }
        if columns:
            payload["columns"] = ",".join(columns)

        logger.info("Fetching %d latest '%s' alerts", n, class_str)
        response = self._post("latests", payload)
        return self._response_to_dataframe(response)

    def get_latest_alert_records(
        self,
        fink_class: FinkClass | str,
        n: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve latest alerts as canonical dictionaries for Bronze processing.

        Column filtering is intentionally not used here because the live Fink
        ``latests`` endpoint currently returns HTTP 500 for the prefixed column
        subset needed by AGD.
        """
        df = self.get_latest_alerts(fink_class=fink_class, n=n, columns=None)
        return [canonicalize_fink_alert_record(record) for record in df.to_dict(orient="records")]

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float = 5.0,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Search for alerts within a cone around sky coordinates.

        Args:
            ra: Right ascension in degrees (0-360).
            dec: Declination in degrees (-90 to +90).
            radius_arcsec: Search radius in arcseconds (default: 5).
            columns: Optional list of specific columns to retrieve.

        Returns:
            DataFrame containing all alerts within the search cone.

        Example:
            >>> client = FinkAPIClient()
            >>> nearby = client.cone_search(ra=193.822, dec=2.896, radius_arcsec=10)
        """
        payload: dict[str, Any] = {
            "ra": str(ra),
            "dec": str(dec),
            "radius": str(radius_arcsec),
            "output-format": self.config.output_format,
        }
        if columns:
            payload["columns"] = ",".join(columns)

        logger.info(
            "Cone search at RA=%.4f, Dec=%.4f, radius=%.1f arcsec",
            ra,
            dec,
            radius_arcsec,
        )
        response = self._post("conesearch", payload)
        return self._response_to_dataframe(response)

    def get_alerts_by_date(
        self,
        start_date: str,
        n: int = 100,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Retrieve alerts from a specific date.

        Args:
            start_date: Date string in YYYY-MM-DD format.
            n: Maximum number of alerts to retrieve.
            columns: Optional list of specific columns to retrieve.

        Returns:
            DataFrame containing alerts from the specified date.
        """
        payload: dict[str, Any] = {
            "startdate": start_date,
            "n": str(n),
            "output-format": self.config.output_format,
        }
        if columns:
            payload["columns"] = ",".join(columns)

        logger.info("Fetching alerts from %s (max %d)", start_date, n)
        response = self._post("latests", payload)
        return self._response_to_dataframe(response)

    def get_object_count(self) -> dict[str, int]:
        """Get counts of objects by Fink classification.

        Returns:
            Dictionary mapping classification labels to object counts.
        """
        response = self._post("statistics", {"output-format": "json"})
        if response.content:
            return response.json()
        return {}

    def health_check(self) -> bool:
        """Verify connectivity to the Fink API.

        Returns:
            True if the API is reachable and responding.
        """
        try:
            # Try to fetch a single known object as a health check
            response = self._session.get(
                self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
            is_healthy = response.status_code == 200
            logger.info("Fink API health check: %s", "OK" if is_healthy else "FAILED")
            return is_healthy
        except requests.RequestException as e:
            logger.error("Fink API health check failed: %s", e)
            return False
