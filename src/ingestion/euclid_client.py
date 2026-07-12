"""Euclid archive TAP/ADQL client for batch catalogue ingestion.

Queries the ESA Euclid archive via ``astroquery.esa.euclid``. This is a new
data modality for AGD — batch catalogue pulls, not streaming alerts — but it
follows the same client pattern as the Fink/Gaia clients: retry/backoff,
timeout, structured logging, and a local Parquet cache keyed on the query.

Table and column names were verified live against ``tap_schema`` on
2026-07-12 (schema ``catalogue``, table ``catalogue.mer_catalogue``; all
MER_COLUMNS present). Re-verify with :meth:`EuclidClient.discover_tables`
after each data release — especially at the DR1-Foundation swap-in.

The astroquery call is isolated in ``_execute_adql`` so unit tests can
substitute canned results without any network access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.crossref.tap_proxy import tap_proxy_tunnel
from src.crossref.utils import query_cache_key
from src.exceptions import EuclidAPIError
from src.utils.config import EuclidSettings, get_settings

logger = structlog.get_logger(__name__)

#: MER final catalogue columns ingested by AGD (verified live 2026-07-12).
MER_COLUMNS = [
    "object_id",
    "right_ascension",
    "declination",
    "flux_vis_psf",
    "flux_y_templfit",
    "flux_j_templfit",
    "flux_h_templfit",
    "point_like_prob",
    "spurious_prob",
]


class EuclidClient:
    """TAP/ADQL client for the ESA Euclid archive.

    Example:
        >>> client = EuclidClient()
        >>> df, provenance = client.mer_cone_search(ra=52.93, dec=-28.09,
        ...                                         radius_deg=0.05)
    """

    def __init__(
        self,
        euclid_settings: EuclidSettings | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._config = euclid_settings or settings.euclid
        if cache_dir is not None:
            self._cache_dir = cache_dir
        else:
            self._cache_dir = settings.storage.base_path / self._config.cache_path
        self._log = logger.bind(component="euclid_client")

    def discover_tables(self, schema: str = "catalogue") -> pd.DataFrame:
        """List tables in an archive schema via ``tap_schema`` (live).

        Schema discovery is deliberately uncached: it exists to detect
        upstream schema changes between data releases.
        """
        query = "SELECT table_name FROM tap_schema.tables " f"WHERE schema_name = '{schema}'"
        try:
            return self._execute_adql(query)
        except Exception as exc:
            raise EuclidAPIError(
                f"Euclid schema discovery failed: {exc}",
                details={"schema": schema},
            ) from exc

    def mer_cone_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float = 0.1,
        columns: list[str] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Cone search on the MER final catalogue.

        Args:
            ra: Cone centre right ascension in degrees (ICRS).
            dec: Cone centre declination in degrees (ICRS).
            radius_deg: Cone radius in degrees (catalogue pulls work at
                field scale, unlike the arcsec-scale alert cross-matches).
            columns: Columns to select; defaults to MER_COLUMNS.

        Returns:
            (rows, provenance) — the result DataFrame plus a provenance
            dict (query, table, dr_tag, retrieval time, row count) to be
            preserved verbatim in the bronze layer.

        Raises:
            EuclidAPIError: If the query fails after retries.
        """
        selected = columns or MER_COLUMNS
        query = self._build_mer_query(ra, dec, radius_deg, selected)

        cached = self._cache_read(query)
        if cached is not None:
            return cached, self._provenance(query, cached, cache_hit=True)

        try:
            df = self._execute_adql(query)
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as exc:
            raise EuclidAPIError(
                f"Euclid MER cone search failed after retries: {exc}",
                details={"ra": ra, "dec": dec, "radius_deg": radius_deg},
            ) from exc
        except Exception as exc:
            raise EuclidAPIError(
                f"Euclid MER cone search failed: {exc}",
                details={"ra": ra, "dec": dec, "radius_deg": radius_deg},
            ) from exc

        df = df.rename(columns={col: col.lower() for col in df.columns})
        self._cache_write(query, df)
        self._log.info(
            "euclid_mer_cone_search_completed",
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            rows=len(df),
            dr_tag=self._config.dr_tag,
        )
        return df, self._provenance(query, df, cache_hit=False)

    def _build_mer_query(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        columns: list[str],
    ) -> str:
        column_sql = ", ".join(columns)
        return (
            f"SELECT TOP {self._config.max_rows} {column_sql} "
            f"FROM {self._config.mer_table} "
            f"WHERE 1 = CONTAINS("
            f"POINT('ICRS', right_ascension, declination), "
            f"CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, {radius_deg:.8f}))"
        )

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=30),
    )
    def _execute_adql(self, query: str) -> pd.DataFrame:
        """Run an ADQL query against the Euclid TAP service.

        Isolated so tests can replace it with canned results. Imports
        astroquery lazily; tunnels through the configured CONNECT proxy
        when set (astroquery's TAP layer ignores HTTPS_PROXY).
        """
        with tap_proxy_tunnel(self._config.tap_proxy_url, self._config.tap_ca_bundle):
            from astroquery.esa.euclid import Euclid

            self._log.debug("euclid_adql_launch", query=query)
            job = Euclid.launch_job(query)
            table = job.get_results()
            return table.to_pandas()

    def _provenance(
        self,
        query: str,
        df: pd.DataFrame,
        cache_hit: bool,
    ) -> dict[str, Any]:
        """Build the provenance record preserved alongside ingested rows."""
        return {
            "source": "esa_euclid_tap",
            "table": self._config.mer_table,
            "query": query,
            "dr_tag": self._config.dr_tag,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "row_count": len(df),
            "cache_hit": cache_hit,
        }

    def _cache_file(self, query: str) -> Path:
        return self._cache_dir / f"euclid_{query_cache_key(query)}.parquet"

    def _cache_read(self, query: str) -> pd.DataFrame | None:
        cache_file = self._cache_file(query)
        if not cache_file.exists():
            return None
        try:
            df = pd.read_parquet(cache_file)
            self._log.debug("euclid_cache_hit", cache_file=str(cache_file))
            return df
        except Exception as exc:
            self._log.warning("euclid_cache_read_failed", error=str(exc))
            return None

    def _cache_write(self, query: str, df: pd.DataFrame) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self._cache_file(query), index=False)
        except Exception as exc:
            # Cache failures must never break ingestion.
            self._log.warning("euclid_cache_write_failed", error=str(exc))
