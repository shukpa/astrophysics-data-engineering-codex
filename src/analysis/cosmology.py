"""Combined-probe cosmology: CPL dark energy, distances, growth (AGD Phase 3a).

Pure functions on top of :mod:`astropy.cosmology`. These power the combined-
probe verdict cell (notebook ``combined_probe_constraints.ipynb``): given the
DESI/Planck/SN/weak-lensing numbers in :mod:`src.analysis.constraints`, where
do (w0, wa, gamma, S8) land relative to GR+LCDM versus a braneworld/DGP
prediction?

Conventions
-----------
* CPL / w0waCDM: w(a) = w0 + wa (1 - a) = w0 + wa z/(1+z). LCDM is w0=-1, wa=0.
* Flat universe throughout (Omega_k = 0); Euclid-era combined fits assume it.
* Growth index: f(z) = Omega_m(z)^gamma (Linder 2005). GR+LCDM -> gamma ~ 0.55.
* S8 = sigma8 sqrt(Omega_m / 0.3).

Nothing here reads the pipeline; analysis depends on gold, never the reverse.
"""

from __future__ import annotations

import math

from astropy.cosmology import FlatLambdaCDM, Flatw0waCDM

from src.analysis.constraints import Measurement

#: A sensible fiducial background for lensing distances and quick checks.
#: Matches the Planck 2018 base-LCDM numbers transcribed in ``constraints``.
PLANCK18_H0 = 67.36
PLANCK18_OM0 = 0.3153


def cpl_w(z: float, w0: float, wa: float) -> float:
    """CPL dark-energy equation of state at redshift ``z``.

    w(z) = w0 + wa * z / (1 + z), equivalently w(a) = w0 + wa (1 - a).
    LCDM corresponds to (w0, wa) = (-1, 0).
    """
    return w0 + wa * z / (1.0 + z)


def build_cosmology(
    *,
    h0: float = PLANCK18_H0,
    omega_m: float = PLANCK18_OM0,
    w0: float = -1.0,
    wa: float = 0.0,
) -> FlatLambdaCDM | Flatw0waCDM:
    """Construct a flat cosmology, collapsing to LCDM when (w0, wa)=(-1, 0).

    Returning :class:`FlatLambdaCDM` for the LCDM case keeps the fiducial exact
    (no dark-energy integration) and gives a clean baseline to compare dynamical
    fits against.
    """
    if w0 == -1.0 and wa == 0.0:
        return FlatLambdaCDM(H0=h0, Om0=omega_m)
    return Flatw0waCDM(H0=h0, Om0=omega_m, w0=w0, wa=wa)


def omega_m_of_z(
    z: float, *, omega_m: float = PLANCK18_OM0, w0: float = -1.0, wa: float = 0.0
) -> float:
    """Matter density parameter at redshift ``z`` for a flat w0waCDM model."""
    cosmo = build_cosmology(omega_m=omega_m, w0=w0, wa=wa)
    return float(cosmo.Om(z))


def growth_rate(
    z: float,
    *,
    gamma: float = 0.55,
    omega_m: float = PLANCK18_OM0,
    w0: float = -1.0,
    wa: float = 0.0,
) -> float:
    """Linear growth rate f(z) = Omega_m(z)^gamma (Linder 2005 approximation).

    ``gamma`` is the growth index: GR+LCDM gives ~0.55, while self-accelerating
    DGP braneworlds predict ~0.68. Holding the expansion history fixed and
    varying ``gamma`` is the cleanest lever separating modified gravity from GR.
    """
    return omega_m_of_z(z, omega_m=omega_m, w0=w0, wa=wa) ** gamma


def s8(sigma8: float, omega_m: float) -> float:
    """Structure-growth amplitude S8 = sigma8 * sqrt(Omega_m / 0.3)."""
    return sigma8 * math.sqrt(omega_m / 0.3)


def sigma8_from_s8(s8_value: float, omega_m: float) -> float:
    """Invert :func:`s8` to recover sigma8 given S8 and Omega_m."""
    return s8_value / math.sqrt(omega_m / 0.3)


def tension_sigma(a: Measurement, b: Measurement) -> float:
    """Tension between two measurements in Gaussian sigma.

    Errors are combined in quadrature; for asymmetric bars each measurement
    contributes the error on the side facing the other's central value.
    """
    err_a = a.error_toward(b.value)
    err_b = b.error_toward(a.value)
    denom = math.hypot(err_a, err_b)
    if denom == 0:
        return math.inf if a.value != b.value else 0.0
    return abs(a.value - b.value) / denom


def distance_from_lcdm_percent(measured: Measurement, *, lcdm_value: float) -> float:
    """Fractional offset of a measured value from its LCDM expectation, in %.

    Convenience for verdict cells: e.g. how far a growth amplitude sits below
    the Planck-LCDM prediction.
    """
    if lcdm_value == 0:
        return math.inf
    return 100.0 * (measured.value - lcdm_value) / lcdm_value
