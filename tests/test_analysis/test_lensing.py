"""Tests for the strong-lens statistics harness (AGD Phase 3b).

The core checks are physics identities, not regressions: sigma_v <-> theta_E
round-trips, the theta_E ~ sigma_v^2 scaling, and agreement between two
*independent* projected-mass formulas (critical-density vs isothermal). A
coarse physical-range anchor guards against unit slips.
"""

from __future__ import annotations

import pytest

from src.analysis import lensing

Z_LENS = 0.3
Z_SOURCE = 1.5


class TestDistances:
    def test_requires_source_behind_lens(self) -> None:
        with pytest.raises(ValueError):
            lensing.angular_diameter_distances(1.0, 0.5)

    def test_distances_are_positive_mpc(self) -> None:
        d = lensing.angular_diameter_distances(Z_LENS, Z_SOURCE)
        assert d.d_lens > 0 and d.d_source > 0 and d.d_lens_source > 0
        # D_l to z=0.3 is ~900 Mpc in Planck18 (sanity band).
        assert 800 < d.d_lens < 1000


class TestSISRelations:
    def test_sigma_theta_round_trip(self) -> None:
        sigma_in = 250.0
        theta = lensing.einstein_radius_sis(sigma_in, Z_LENS, Z_SOURCE)
        sigma_out = lensing.velocity_dispersion_sis(theta, Z_LENS, Z_SOURCE)
        assert sigma_out == pytest.approx(sigma_in, rel=1e-9)

    def test_theta_scales_as_sigma_squared(self) -> None:
        t1 = lensing.einstein_radius_sis(200.0, Z_LENS, Z_SOURCE)
        t2 = lensing.einstein_radius_sis(400.0, Z_LENS, Z_SOURCE)
        assert t2 / t1 == pytest.approx(4.0, rel=1e-9)

    def test_einstein_radius_physical_band(self) -> None:
        # A 250 km/s early-type at these redshifts gives ~1 arcsec (sanity,
        # not a fit — this is the SLACS/SLDE ballpark).
        theta = lensing.einstein_radius_sis(250.0, Z_LENS, Z_SOURCE)
        assert 0.5 < theta < 2.5


class TestMass:
    def test_two_mass_formulas_agree_for_sis(self) -> None:
        sigma = 260.0
        theta = lensing.einstein_radius_sis(sigma, Z_LENS, Z_SOURCE)
        m_crit = lensing.einstein_mass(theta, Z_LENS, Z_SOURCE)
        m_sis = lensing.projected_mass_sis(sigma, theta, Z_LENS)
        assert m_crit == pytest.approx(m_sis, rel=1e-6)

    def test_einstein_mass_is_galaxy_scale(self) -> None:
        # theta_E ~ 1 arcsec lens -> M(<theta_E) ~ 10^11 Msun.
        theta = lensing.einstein_radius_sis(250.0, Z_LENS, Z_SOURCE)
        mass = lensing.einstein_mass(theta, Z_LENS, Z_SOURCE)
        assert 1e10 < mass < 1e12

    def test_mass_rejects_nonphysical_input(self) -> None:
        with pytest.raises(ValueError):
            lensing.einstein_mass(0.0, Z_LENS, Z_SOURCE)


class TestSensitivityFloor:
    def test_poisson_floor_shrinks_with_sample_size(self) -> None:
        assert lensing.poisson_fractional_floor(500) > lensing.poisson_fractional_floor(7000)

    def test_q1_vs_dr1f_detectable_fractions(self) -> None:
        # 3-sigma detectable abundance deviation: Q1 ~13%, DR1F ~3.6%.
        q1 = lensing.detectable_fraction(500, n_sigma=3.0)
        dr1f = lensing.detectable_fraction(7000, n_sigma=3.0)
        assert q1 == pytest.approx(0.134, abs=0.005)
        assert dr1f == pytest.approx(0.036, abs=0.005)
        assert q1 > dr1f

    def test_floor_rejects_empty_sample(self) -> None:
        with pytest.raises(ValueError):
            lensing.poisson_fractional_floor(0)


def test_sie_note_explains_convention() -> None:
    note = lensing.sie_note()
    assert "enclosed mass" in note.lower()
