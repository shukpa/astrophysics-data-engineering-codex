"""Pydantic models for catalog cross-match results (gold layer).

These models represent nearest-neighbour matches returned by the Gaia and
SIMBAD clients. They are intentionally small: only the columns the gold layer
consumes, plus derived significance metrics used by the star/extragalactic
discriminator.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field


class GaiaMatch(BaseModel):
    """Nearest Gaia DR3 source to a transient position.

    Attributes:
        source_id: Gaia DR3 source identifier.
        ra: Match right ascension (degrees).
        dec: Match declination (degrees).
        separation_arcsec: Angular separation from the query position.
        g_mag: Gaia G-band mean magnitude.
        parallax: Parallax in milliarcseconds.
        parallax_error: Parallax uncertainty in milliarcseconds.
        pmra: Proper motion in RA*cos(dec), mas/yr.
        pmra_error: Uncertainty on pmra, mas/yr.
        pmdec: Proper motion in declination, mas/yr.
        pmdec_error: Uncertainty on pmdec, mas/yr.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: int
    ra: float
    dec: float
    separation_arcsec: float = Field(..., ge=0)
    g_mag: float | None = None
    parallax: float | None = None
    parallax_error: float | None = None
    pmra: float | None = None
    pmra_error: float | None = None
    pmdec: float | None = None
    pmdec_error: float | None = None

    @property
    def parallax_snr(self) -> float | None:
        """Parallax significance (parallax / parallax_error).

        Returns None when parallax or its uncertainty is unavailable or the
        uncertainty is non-positive. Negative parallaxes yield negative SNR,
        which never passes a positive significance threshold.
        """
        if self.parallax is None or self.parallax_error is None:
            return None
        if self.parallax_error <= 0:
            return None
        return self.parallax / self.parallax_error

    @property
    def pm_total(self) -> float | None:
        """Total proper motion magnitude in mas/yr."""
        if self.pmra is None or self.pmdec is None:
            return None
        return math.hypot(self.pmra, self.pmdec)

    @property
    def pm_snr(self) -> float | None:
        """Approximate total-proper-motion significance.

        Uses |pm| / hypot(pmra_error, pmdec_error). This treats the error
        ellipse as isotropic — adequate for a threshold discriminator, not
        for astrometric science.
        """
        total = self.pm_total
        if total is None or self.pmra_error is None or self.pmdec_error is None:
            return None
        error = math.hypot(self.pmra_error, self.pmdec_error)
        if error <= 0:
            return None
        return total / error


class SimbadMatch(BaseModel):
    """Nearest SIMBAD object to a transient position.

    Attributes:
        main_id: SIMBAD principal identifier.
        otype: SIMBAD object type code (e.g. "QSO", "V*", "G").
        ra: Match right ascension (degrees), when provided.
        dec: Match declination (degrees), when provided.
        separation_arcsec: Angular separation from the query position.
    """

    model_config = ConfigDict(extra="forbid")

    main_id: str
    otype: str | None = None
    ra: float | None = None
    dec: float | None = None
    separation_arcsec: float = Field(..., ge=0)
