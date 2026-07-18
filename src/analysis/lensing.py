"""Strong-lens statistics harness: SIS/SIE relations (AGD Phase 3b).

Pure, unit-tested functions relating a strong lens's Einstein radius, the
lensing-galaxy velocity dispersion, and the projected mass within the Einstein
radius, plus the survey sensitivity floor that tells us which questions Q1 can
and cannot answer. These power ``notebooks/euclid_lens_statistics.ipynb``.

Physics (singular isothermal sphere; Narayan & Bartelmann 1996):

* Einstein radius:  theta_E = 4 pi (sigma_v / c)^2 * D_ls / D_s   [radians]
* Enclosed mass:    M(<theta_E) = (c^2 / 4G) theta_E^2 * D_l D_s / D_ls

Both the SIS relation and the general enclosed-mass expression are exact for
the mass-normalized singular isothermal ellipsoid (SIE), so the same functions
apply to the elliptical case SLDE catalogues actually report (see
:func:`sie_note`).

Distances are angular-diameter distances from an astropy cosmology (default:
Planck 2018). Analysis depends on gold; the pipeline never imports analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import astropy.units as u
from astropy.constants import G, c
from astropy.cosmology import FLRW, Planck18


@dataclass(frozen=True)
class LensDistances:
    """Angular-diameter distances for a lens/source pair, in Mpc.

    Attributes:
        d_lens: Observer -> lens (D_l).
        d_source: Observer -> source (D_s).
        d_lens_source: Lens -> source (D_ls).
    """

    d_lens: float
    d_source: float
    d_lens_source: float


def angular_diameter_distances(
    z_lens: float, z_source: float, *, cosmo: FLRW = Planck18
) -> LensDistances:
    """Compute (D_l, D_s, D_ls) in Mpc for a lens/source redshift pair.

    Raises:
        ValueError: If ``z_source <= z_lens`` (no lensing configuration).
    """
    if z_source <= z_lens:
        raise ValueError(f"z_source ({z_source}) must exceed z_lens ({z_lens})")
    d_l = cosmo.angular_diameter_distance(z_lens).to_value(u.Mpc)
    d_s = cosmo.angular_diameter_distance(z_source).to_value(u.Mpc)
    d_ls = cosmo.angular_diameter_distance_z1z2(z_lens, z_source).to_value(u.Mpc)
    return LensDistances(d_lens=d_l, d_source=d_s, d_lens_source=d_ls)


def einstein_radius_sis(
    sigma_v_kms: float, z_lens: float, z_source: float, *, cosmo: FLRW = Planck18
) -> float:
    """SIS Einstein radius in arcseconds from the velocity dispersion.

    theta_E = 4 pi (sigma_v / c)^2 * D_ls / D_s.
    """
    if sigma_v_kms <= 0:
        raise ValueError("sigma_v_kms must be positive")
    dist = angular_diameter_distances(z_lens, z_source, cosmo=cosmo)
    sigma = sigma_v_kms * u.km / u.s
    theta_rad = 4.0 * math.pi * (sigma / c).to_value(u.dimensionless_unscaled) ** 2
    theta_rad *= dist.d_lens_source / dist.d_source
    return float((theta_rad * u.rad).to_value(u.arcsec))


def velocity_dispersion_sis(
    theta_e_arcsec: float, z_lens: float, z_source: float, *, cosmo: FLRW = Planck18
) -> float:
    """Invert :func:`einstein_radius_sis`: sigma_v [km/s] from theta_E.

    sigma_v = c * sqrt( theta_E / (4 pi) * D_s / D_ls ).
    """
    if theta_e_arcsec <= 0:
        raise ValueError("theta_e_arcsec must be positive")
    dist = angular_diameter_distances(z_lens, z_source, cosmo=cosmo)
    theta_rad = (theta_e_arcsec * u.arcsec).to_value(u.rad)
    ratio = theta_rad / (4.0 * math.pi) * dist.d_source / dist.d_lens_source
    sigma = c * math.sqrt(ratio)
    return float(sigma.to_value(u.km / u.s))


def einstein_mass(
    theta_e_arcsec: float, z_lens: float, z_source: float, *, cosmo: FLRW = Planck18
) -> float:
    """Projected mass within the Einstein radius, in solar masses.

    M(<theta_E) = (c^2 / 4G) theta_E^2 * D_l D_s / D_ls. Exact for both the SIS
    and the mass-normalized SIE, so it applies to catalogue theta_E directly.
    """
    if theta_e_arcsec <= 0:
        raise ValueError("theta_e_arcsec must be positive")
    dist = angular_diameter_distances(z_lens, z_source, cosmo=cosmo)
    theta_rad = (theta_e_arcsec * u.arcsec).to_value(u.rad)
    d_l = dist.d_lens * u.Mpc
    d_s = dist.d_source * u.Mpc
    d_ls = dist.d_lens_source * u.Mpc
    mass = (c**2 / (4.0 * G)) * theta_rad**2 * (d_l * d_s / d_ls)
    return float(mass.to_value(u.Msun))


def projected_mass_sis(
    sigma_v_kms: float, theta_e_arcsec: float, z_lens: float, *, cosmo: FLRW = Planck18
) -> float:
    """SIS projected mass within theta_E via M = pi sigma_v^2 R_E / G.

    Independent of :func:`einstein_mass` (uses sigma_v and the physical Einstein
    radius R_E = theta_E * D_l rather than the critical surface density), so
    agreement between the two is a strong internal-consistency check.
    """
    if sigma_v_kms <= 0 or theta_e_arcsec <= 0:
        raise ValueError("sigma_v_kms and theta_e_arcsec must be positive")
    d_l = angular_diameter_distances(z_lens, z_lens + 1.0, cosmo=cosmo).d_lens * u.Mpc
    theta_rad = (theta_e_arcsec * u.arcsec).to_value(u.rad)
    r_e = theta_rad * d_l
    sigma = sigma_v_kms * u.km / u.s
    mass = math.pi * sigma**2 * r_e / G
    return float(mass.to_value(u.Msun))


def sie_note() -> str:
    """Explain why the SIS relations apply to the elliptical (SIE) case.

    A singular isothermal ellipsoid normalized to the same mass as an SIS has
    the same enclosed mass within the (mass-weighted) Einstein radius, so
    :func:`einstein_mass` and :func:`velocity_dispersion_sis` are exact for the
    theta_E that SLDE-style catalogues report. Ellipticity redistributes the
    critical curve into a diamond but does not change the enclosed mass at fixed
    theta_E; a circularized (equal-area) radius would differ from theta_E only
    by an axis-ratio factor of order sqrt(q).
    """
    return sie_note.__doc__ or ""


# --- Survey sensitivity floor (3b conclusions cell) ---------------------------


def poisson_fractional_floor(n_lenses: int) -> float:
    """Fractional statistical floor on a lens-abundance statistic: 1/sqrt(N).

    A sample of ``n_lenses`` constrains an abundance (or any counting statistic)
    to at best ~1/sqrt(N) fractionally, before systematics. This is the number
    that decides whether a given deviation is measurable.
    """
    if n_lenses <= 0:
        raise ValueError("n_lenses must be positive")
    return 1.0 / math.sqrt(n_lenses)


def detectable_fraction(n_lenses: int, *, n_sigma: float = 3.0) -> float:
    """Smallest fractional abundance deviation detectable at ``n_sigma``.

    detectable = n_sigma / sqrt(N). At Q1 (N ~ 500) this is ~13% at 3-sigma; at
    DR1-Foundation (N ~ 7000) it drops to ~3.6%. Braneworld-scale corrections to
    lensing observables are suppressed by ~(length/curvature)^2 and sit orders
    of magnitude below either floor — the 3b sensitivity conclusion in code.
    """
    if n_sigma <= 0:
        raise ValueError("n_sigma must be positive")
    return n_sigma * poisson_fractional_floor(n_lenses)
