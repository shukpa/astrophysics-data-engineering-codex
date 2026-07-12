"""SIMBAD cross-match client for the gold layer.

Runs cone searches against SIMBAD via astroquery to attach object types
(otype) and principal identifiers to transient positions. Results are
cached locally as Parquet, mirroring the Gaia client.

The astroquery call is isolated in ``_query_region`` so unit tests can
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

from src.crossref.utils import (
    angular_separation_arcsec,
    coord_to_degrees,
    none_if_nan,
    query_cache_key,
)
from src.exceptions import SIMBADError
from src.models.crossref import SimbadMatch
from src.utils.config import CrossmatchSettings, get_settings

logger = structlog.get_logger(__name__)

SIMBAD_COLUMNS = ["main_id", "ra", "dec", "otype"]


class SimbadClient:
    """Cone-search client for the SIMBAD astronomical database.

    Example:
        >>> client = SimbadClient()
        >>> match = client.nearest(ra=10.6847, dec=41.269)
        >>> if match:
        ...     print(match.main_id, match.otype)
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
        self._log = logger.bind(component="simbad_client")

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float | None = None,
    ) -> pd.DataFrame:
        """Search SIMBAD for objects within a cone, nearest first.

        Args:
            ra: Right ascension in degrees (ICRS).
            dec: Declination in degrees (ICRS).
            radius_arcsec: Search radius; defaults to the configured radius.

        Returns:
            DataFrame with SIMBAD_COLUMNS plus ``separation_arcsec``, sorted
            by separation ascending. Empty when nothing falls in the cone.

        Raises:
            SIMBADError: If the query fails after retries.
        """
        radius = radius_arcsec if radius_arcsec is not None else self._config.radius_arcsec

        cached = self._cache_read(ra, dec, radius)
        if cached is not None:
            return cached

        try:
            raw = self._query_region(ra, dec, radius)
            # Normalise inside the guard: a legacy/unexpected result schema must
            # degrade to a SIMBADError (null enrichment) rather than an
            # unwrapped exception that aborts the whole gold batch.
            df = self._normalise(raw, ra, dec)
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as exc:
            raise SIMBADError(
                f"SIMBAD cone search failed after retries: {exc}",
                details={"ra": ra, "dec": dec, "radius_arcsec": radius},
            ) from exc
        except Exception as exc:
            raise SIMBADError(
                f"SIMBAD cone search failed: {exc}",
                details={"ra": ra, "dec": dec, "radius_arcsec": radius},
            ) from exc
        self._cache_write(ra, dec, radius, df)
        self._log.info(
            "simbad_cone_search_completed",
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
    ) -> SimbadMatch | None:
        """Return the nearest SIMBAD object in the cone, or None."""
        df = self.cone_search(ra=ra, dec=dec, radius_arcsec=radius_arcsec)
        if df.empty:
            return None

        # Rows are sorted nearest-first with unparseable positions last, so the
        # first row has a usable separation unless every row lacked a position.
        row = df.iloc[0]
        separation = none_if_nan(row.get("separation_arcsec"))
        if separation is None:
            return None

        main_id = row.get("main_id")
        if main_id is None:
            return None
        if isinstance(main_id, bytes):
            main_id = main_id.decode("utf-8", errors="replace")

        otype = none_if_nan(row.get("otype"))
        if isinstance(otype, bytes):
            otype = otype.decode("utf-8", errors="replace")

        return SimbadMatch(
            main_id=str(main_id),
            otype=otype,
            ra=coord_to_degrees(row.get("ra"), is_ra=True),
            dec=coord_to_degrees(row.get("dec"), is_ra=False),
            separation_arcsec=float(separation),
        )

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=30),
    )
    def _query_region(self, ra: float, dec: float, radius_arcsec: float) -> pd.DataFrame:
        """Run the cone search via astroquery.

        Isolated so tests can replace it with canned results. Imports
        astroquery lazily to keep module import light.
        """
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astroquery.simbad import Simbad

        simbad = Simbad()
        simbad.TIMEOUT = self._config.simbad_timeout_seconds
        simbad.add_votable_fields("otype")

        coord = SkyCoord(ra=ra, dec=dec, unit="deg", frame="icrs")
        self._log.debug("simbad_query_region", ra=ra, dec=dec, radius_arcsec=radius_arcsec)
        table = simbad.query_region(coord, radius=radius_arcsec * u.arcsec)
        if table is None:
            return pd.DataFrame()
        return table.to_pandas()

    def _normalise(self, df: pd.DataFrame, ra: float, dec: float) -> pd.DataFrame:
        """Lower-case columns, compute separations, sort nearest first."""
        if df.empty:
            return pd.DataFrame(columns=[*SIMBAD_COLUMNS, "separation_arcsec"])

        df = df.rename(columns={col: col.lower() for col in df.columns})

        # ra/dec are decimal degrees in modern astroquery but sexagesimal
        # strings in older (still-allowed) versions; coord_to_degrees tolerates
        # both and yields None for anything unparseable. Rows without a usable
        # position are kept but sorted last.
        separations: list[float | None] = []
        for row_ra, row_dec in zip(df.get("ra"), df.get("dec"), strict=True):
            deg_ra = coord_to_degrees(row_ra, is_ra=True)
            deg_dec = coord_to_degrees(row_dec, is_ra=False)
            if deg_ra is None or deg_dec is None:
                separations.append(None)
                continue
            separations.append(angular_separation_arcsec(ra, dec, deg_ra, deg_dec))
        df["separation_arcsec"] = separations

        return df.sort_values("separation_arcsec", na_position="last").reset_index(drop=True)

    def _cache_file(self, ra: float, dec: float, radius_arcsec: float) -> Path:
        key = query_cache_key("simbad", ra, dec, radius_arcsec)
        return self._cache_dir / f"simbad_{key}.parquet"

    def _cache_read(self, ra: float, dec: float, radius_arcsec: float) -> pd.DataFrame | None:
        if not self._config.cache_enabled:
            return None
        cache_file = self._cache_file(ra, dec, radius_arcsec)
        if not cache_file.exists():
            return None
        try:
            df = pd.read_parquet(cache_file)
            self._log.debug("simbad_cache_hit", cache_file=str(cache_file))
            return df
        except Exception as exc:
            self._log.warning("simbad_cache_read_failed", error=str(exc))
            return None

    def _cache_write(self, ra: float, dec: float, radius_arcsec: float, df: pd.DataFrame) -> None:
        if not self._config.cache_enabled:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self._cache_file(ra, dec, radius_arcsec), index=False)
        except Exception as exc:
            # Cache failures must never break the pipeline.
            self._log.warning("simbad_cache_write_failed", error=str(exc))
