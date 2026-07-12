"""Shared helpers for catalog cross-reference clients."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from astropy.coordinates import SkyCoord


def none_if_nan(value: Any) -> Any:
    """Convert pandas/NumPy NaN (or masked) values to None.

    Catalog query results frequently carry NaN for missing photometry or
    astrometry; Pydantic models expect None for absent optional fields.
    """
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        # NumPy scalars expose item(); masked values compare unequal to self.
        if value != value:  # noqa: PLR0124 - deliberate NaN check
            return None
    except (TypeError, ValueError):
        return value
    return value


def angular_separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation between two ICRS positions, in arcseconds."""
    c1 = SkyCoord(ra=ra1, dec=dec1, unit="deg", frame="icrs")
    c2 = SkyCoord(ra=ra2, dec=dec2, unit="deg", frame="icrs")
    return float(c1.separation(c2).arcsecond)


def query_cache_key(*parts: Any) -> str:
    """Build a deterministic cache key for a catalog query.

    Positions are rounded to 1e-6 deg (~4 mas) so float jitter does not
    defeat the cache while physically distinct positions never collide.
    """
    normalised = []
    for part in parts:
        if isinstance(part, float):
            normalised.append(f"{part:.6f}")
        else:
            normalised.append(str(part))
    joined = "|".join(normalised)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]
