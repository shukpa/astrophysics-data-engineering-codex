"""Published cosmological constraints, transcribed from source (not memory).

Every value here is copied from the cited paper's tables/abstract, per the
AGD rule "best-fit values transcribed from arXiv, not memory" and "no
narrative without a number". The combined-probe verdict cell (notebook 3a)
reads these; unit tests assert the notebook's conclusions against them.

Provenance is attached to each record via ``source`` (human citation) and
``arxiv`` (identifier). When a paper reports asymmetric errors we keep them
asymmetric; symmetric errors set ``err_lo == err_hi``.

Sources
-------
* DESI DR2 BAO (w0waCDM): arXiv:2503.14738, Tables 5 and 6.
* Planck 2018 base-LCDM (TT,TE,EE+lowE+lensing): arXiv:1807.06209, Table 2.
* KiDS-1000 3x2pt: arXiv:2007.15632, abstract.
* DES Y3 3x2pt: arXiv:2105.13549, abstract.
* DES-SN5YR: arXiv:2401.02929.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Measurement:
    """A measured value with (possibly asymmetric) 68% uncertainties.

    ``err_hi`` and ``err_lo`` are stored as positive magnitudes of the upper
    and lower 1-sigma errors respectively.
    """

    value: float
    err_hi: float
    err_lo: float

    @classmethod
    def symmetric(cls, value: float, err: float) -> Measurement:
        """Build a measurement with a symmetric ``value ± err``."""
        return cls(value=value, err_hi=err, err_lo=err)

    @property
    def sigma(self) -> float:
        """Representative 1-sigma scale (mean of the two half-errors)."""
        return 0.5 * (self.err_hi + self.err_lo)

    def error_toward(self, other: float) -> float:
        """The 1-sigma error on the side facing ``other``.

        Using the error bar that points toward the comparison value is the
        correct choice for a one-sided tension estimate on an asymmetric
        posterior.
        """
        return self.err_lo if other < self.value else self.err_hi

    def __str__(self) -> str:  # pragma: no cover - display only
        if self.err_hi == self.err_lo:
            return f"{self.value:g} ± {self.err_hi:g}"
        return f"{self.value:g} (+{self.err_hi:g}/-{self.err_lo:g})"


@dataclass(frozen=True)
class W0WaConstraint:
    """A w0waCDM dark-energy constraint from a probe combination.

    Attributes:
        label: Dataset combination, e.g. "DESI+CMB+DESY5".
        w0: Present-day dark-energy equation of state.
        wa: CPL evolution parameter (w(a) = w0 + wa (1 - a)).
        omega_m: Matter density today.
        h0: Hubble constant [km/s/Mpc].
        sigma_vs_lcdm: Reported preference over the cosmological constant
            (w0=-1, wa=0), in Gaussian sigma, for this combination.
        source: Human-readable citation.
        arxiv: arXiv identifier.
    """

    label: str
    w0: Measurement
    wa: Measurement
    omega_m: Measurement
    h0: Measurement
    sigma_vs_lcdm: float
    source: str = "DESI DR2 BAO, Tables 5 and 6"
    arxiv: str = "2503.14738"


# --- DESI DR2 w0waCDM (arXiv:2503.14738, Tables 5 and 6) ----------------------
# The headline dynamical-dark-energy result. Favoured quadrant is w0 > -1,
# wa < 0. Preference over LCDM grows as SNe are added (2.8-4.2 sigma).
DESI_DR2_W0WA: dict[str, W0WaConstraint] = {
    "DESI+CMB": W0WaConstraint(
        label="DESI+CMB",
        w0=Measurement.symmetric(-0.43, 0.21),
        wa=Measurement.symmetric(-1.70, 0.60),
        omega_m=Measurement.symmetric(0.352, 0.021),
        h0=Measurement(63.7, 1.7, 2.1),
        sigma_vs_lcdm=3.1,
    ),
    "DESI+CMB+Pantheon+": W0WaConstraint(
        label="DESI+CMB+Pantheon+",
        w0=Measurement.symmetric(-0.853, 0.057),
        wa=Measurement.symmetric(-0.54, 0.22),
        omega_m=Measurement.symmetric(0.3117, 0.0056),
        h0=Measurement.symmetric(67.62, 0.60),
        sigma_vs_lcdm=2.8,
    ),
    "DESI+CMB+Union3": W0WaConstraint(
        label="DESI+CMB+Union3",
        w0=Measurement.symmetric(-0.678, 0.092),
        wa=Measurement(-1.03, 0.30, 0.29),
        omega_m=Measurement.symmetric(0.3273, 0.0086),
        h0=Measurement.symmetric(65.98, 0.86),
        sigma_vs_lcdm=3.8,
    ),
    "DESI+CMB+DESY5": W0WaConstraint(
        label="DESI+CMB+DESY5",
        w0=Measurement.symmetric(-0.752, 0.057),
        wa=Measurement(-0.86, 0.23, 0.20),
        omega_m=Measurement.symmetric(0.3191, 0.0056),
        h0=Measurement.symmetric(66.74, 0.56),
        sigma_vs_lcdm=4.2,
    ),
}


# --- Planck 2018 base-LCDM (arXiv:1807.06209, Table 2) ------------------------
# TT,TE,EE+lowE+lensing column. This paper predates arXiv HTML rendering, so
# these derived parameters are transcribed from Table 2 of the published PDF;
# the primary parameters (Omega_b h^2 = 0.0224, n_s = 0.965, Omega_c h^2 =
# 0.120) match the abstract exactly as a cross-check.
PLANCK18 = {
    "omega_m": Measurement.symmetric(0.3153, 0.0073),
    "h0": Measurement.symmetric(67.36, 0.54),
    "sigma8": Measurement.symmetric(0.8111, 0.0060),
    "s8": Measurement.symmetric(0.832, 0.013),
    "n_s": Measurement.symmetric(0.9649, 0.0042),
    "omega_b_h2": Measurement.symmetric(0.02237, 0.00015),
}
PLANCK18_SOURCE = "Planck 2018 VI, Table 2 (TT,TE,EE+lowE+lensing)"
PLANCK18_ARXIV = "1807.06209"


@dataclass(frozen=True)
class GrowthConstraint:
    """A structure-growth constraint (S8 = sigma8 sqrt(Omega_m / 0.3))."""

    label: str
    s8: Measurement
    omega_m: Measurement | None
    source: str
    arxiv: str


# --- Stage-III weak lensing (the growth axis, pre-Euclid-DR1) ------------------
# Marginal S8 offsets relative to Planck. Full-parameter-space consistency
# requires the corresponding covariance matrices or likelihoods.
STAGE3_GROWTH: dict[str, GrowthConstraint] = {
    "KiDS-1000": GrowthConstraint(
        label="KiDS-1000 3x2pt",
        s8=Measurement(0.766, 0.020, 0.014),
        omega_m=None,
        source="KiDS-1000 3x2pt (Heymans et al. 2021), abstract",
        arxiv="2007.15632",
    ),
    "DES-Y3": GrowthConstraint(
        label="DES Y3 3x2pt",
        s8=Measurement.symmetric(0.776, 0.017),
        omega_m=Measurement(0.339, 0.032, 0.031),
        source="DES Y3 3x2pt (DES Collaboration 2022), abstract",
        arxiv="2105.13549",
    ),
}


# --- Type Ia supernovae (third combined-probe leg) ----------------------------
# DES-SN5YR standalone flat-LCDM matter density; the sample also enters the
# DESI+CMB+DESY5 combination above.
DES_SN5YR_OMEGA_M = Measurement.symmetric(0.352, 0.017)
DES_SN5YR_SOURCE = "DES-SN5YR (DES Collaboration 2024)"
DES_SN5YR_ARXIV = "2401.02929"


# --- Theory reference points (growth index gamma) -----------------------------
# GR+LCDM predicts gamma ~ 0.55; self-accelerating DGP braneworld predicts a
# markedly larger value. These are the "vs GR vs braneworld" goalposts the 3a
# verdict cell compares against — they are *model predictions*, not data.
GAMMA_GR = 0.55  # Linder 2005; Omega_m(z)^gamma growth-rate approximation.
GAMMA_DGP = 0.68  # Self-accelerating DGP reference; no gamma fit is performed here.
GAMMA_SOURCES = "Linder 2005 (astro-ph/0507263); Linder & Cahn 2007 for DGP"
