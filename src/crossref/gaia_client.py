"""Gaia DR3 cross-match client for the gold layer.

Runs ADQL cone searches against the ESA Gaia TAP service via astroquery.
Results are cached locally as Parquet (keyed on the query parameters)
because Gaia TAP is slow and rate-limited.

The astroquery call is isolated in ``_execute_adql`` so unit tests can
substitute canned results without any network access.
"""

from __future__ import annotations

from pathlib import Path

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
from src.crossref.utils import angular_separation_arcsec, none_if_nan, query_cache_key
from src.exceptions import GaiaError
from src.models.crossref import GaiaMatch
from src.utils.config import CrossmatchSettings, get_settings

logger = structlog.get_logger(__name__)

GAIA_COLUMNS = [
    "source_id",
    "ra",
    "dec",
    "phot_g_mean_mag",
    "parallax",
    "parallax_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
]


class GaiaClient:
    """Cone-search client for the Gaia DR3 source catalog.

    Example:
        >>> client = GaiaClient()
        >>> match = client.nearest(ra=269.4486, dec=4.7379)
        >>> if match:
        ...     print(match.source_id, match.separation_arcsec)
    """

    def __init__(
        self,
        crossmatch_settings: CrossmatchSettings | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._config = crossmatch_settings or settings.crossmatch
        if cache_dir is not None:
            self._cache_dir = cache_dir
        else:
            self._cache_dir = settings.storage.base_path / self._config.cache_path
        self._log = logger.bind(component="gaia_client")

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float | None = None,
    ) -> pd.DataFrame:
        """Search Gaia DR3 for sources within a cone, nearest first.

        Args:
            ra: Right ascension in degrees (ICRS).
            dec: Declination in degrees (ICRS).
            radius_arcsec: Search radius; defaults to the configured radius.

        Returns:
            DataFrame with GAIA_COLUMNS plus ``separation_arcsec``, sorted by
            separation ascending. Empty when nothing falls in the cone.

        Raises:
            GaiaError: If the query fails after retries.
        """
        radius = radius_arcsec if radius_arcsec is not None else self._config.radius_arcsec

        cached = self._cache_read(ra, dec, radius)
        if cached is not None:
            return cached

        query = self._build_query(ra, dec, radius)
        try:
            df = self._execute_adql(query)
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as exc:
            raise GaiaError(
                f"Gaia cone search failed after retries: {exc}",
                details={"ra": ra, "dec": dec, "radius_arcsec": radius},
            ) from exc
        except Exception as exc:
            raise GaiaError(
                f"Gaia cone search failed: {exc}",
                details={"ra": ra, "dec": dec, "radius_arcsec": radius},
            ) from exc

        df = self._normalise(df, ra, dec)
        self._cache_write(ra, dec, radius, df)
        self._log.info(
            "gaia_cone_search_completed",
            ra=ra,
            dec=dec,
            radius_arcsec=radius,
            matches=len(df),
        )
        return df

    def nearest(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float | None = None,
    ) -> GaiaMatch | None:
        """Return the nearest Gaia source in the cone, or None."""
        df = self.cone_search(ra=ra, dec=dec, radius_arcsec=radius_arcsec)
        if df.empty:
            return None

        row = df.iloc[0]
        return GaiaMatch(
            source_id=int(row["source_id"]),
            ra=float(row["ra"]),
            dec=float(row["dec"]),
            separation_arcsec=float(row["separation_arcsec"]),
            g_mag=none_if_nan(row.get("phot_g_mean_mag")),
            parallax=none_if_nan(row.get("parallax")),
            parallax_error=none_if_nan(row.get("parallax_error")),
            pmra=none_if_nan(row.get("pmra")),
            pmra_error=none_if_nan(row.get("pmra_error")),
            pmdec=none_if_nan(row.get("pmdec")),
            pmdec_error=none_if_nan(row.get("pmdec_error")),
        )

    def _build_query(self, ra: float, dec: float, radius_arcsec: float) -> str:
        radius_deg = radius_arcsec / 3600.0
        columns = ", ".join(GAIA_COLUMNS)
        # Select an aliased distance and ORDER BY it so TOP keeps the NEAREST
        # rows. Without this, in a crowded field (or wide radius) with more than
        # gaia_max_rows sources, an unordered TOP could truncate away the true
        # nearest counterpart, producing a wrong match + discriminator. (Gaia's
        # ADQL parser rejects a bare function in ORDER BY, hence the alias.)
        return (
            f"SELECT TOP {self._config.gaia_max_rows} {columns}, "
            f"DISTANCE(POINT('ICRS', ra, dec), "
            f"POINT('ICRS', {ra:.8f}, {dec:.8f})) AS dist "
            f"FROM {self._config.gaia_catalog} "
            f"WHERE 1 = CONTAINS("
            f"POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, {radius_deg:.10f})) "
            f"ORDER BY dist ASC"
        )

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=30),
    )
    def _execute_adql(self, query: str) -> pd.DataFrame:
        """Run an ADQL query against the Gaia TAP service.

        Isolated so tests can replace it with canned results. Imports
        astroquery lazily to keep module import light. When a TAP proxy is
        configured, the astroquery connection is tunnelled through it (a
        no-op otherwise), since astroquery's TAP layer ignores HTTPS_PROXY.
        """
        with tap_proxy_tunnel(self._config.tap_proxy_url, self._config.tap_ca_bundle):
            from astroquery.gaia import Gaia

            self._log.debug("gaia_adql_launch", query=query)
            job = Gaia.launch_job(query)
            table = job.get_results()
            return table.to_pandas()

    def _normalise(self, df: pd.DataFrame, ra: float, dec: float) -> pd.DataFrame:
        """Lower-case columns, compute separations, sort nearest first."""
        if df.empty:
            return pd.DataFrame(columns=[*GAIA_COLUMNS, "separation_arcsec"])

        df = df.rename(columns={col: col.lower() for col in df.columns})
        # Drop the server-side ORDER BY helper column; separation_arcsec below
        # (great-circle) is the authoritative distance carried downstream.
        df = df.drop(columns=[c for c in ("dist",) if c in df.columns])
        df["separation_arcsec"] = [
            angular_separation_arcsec(ra, dec, float(row_ra), float(row_dec))
            for row_ra, row_dec in zip(df["ra"], df["dec"], strict=True)
        ]
        return df.sort_values("separation_arcsec").reset_index(drop=True)

    def _cache_file(self, ra: float, dec: float, radius_arcsec: float) -> Path:
        key = query_cache_key(
            self._config.gaia_catalog, ra, dec, radius_arcsec, self._config.gaia_max_rows
        )
        return self._cache_dir / f"gaia_{key}.parquet"

    def _cache_read(self, ra: float, dec: float, radius_arcsec: float) -> pd.DataFrame | None:
        if not self._config.cache_enabled:
            return None
        cache_file = self._cache_file(ra, dec, radius_arcsec)
        if not cache_file.exists():
            return None
        try:
            df = pd.read_parquet(cache_file)
            self._log.debug("gaia_cache_hit", cache_file=str(cache_file))
            return df
        except Exception as exc:
            self._log.warning("gaia_cache_read_failed", error=str(exc))
            return None

    def _cache_write(self, ra: float, dec: float, radius_arcsec: float, df: pd.DataFrame) -> None:
        if not self._config.cache_enabled:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self._cache_file(ra, dec, radius_arcsec), index=False)
        except Exception as exc:
            # Cache failures must never break the pipeline.
            self._log.warning("gaia_cache_write_failed", error=str(exc))
