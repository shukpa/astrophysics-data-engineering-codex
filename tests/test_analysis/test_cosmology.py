"""Tests for the combined-probe cosmology helpers (AGD Phase 3a).

Assertions are anchored to the published values transcribed in
``src.analysis.constraints`` — the S8 relation is validated by reproducing
Planck's own S8 from its sigma8 and Omega_m, and the S8-tension figure is
checked against the KiDS/Planck offset the papers report.
"""

from __future__ import annotations

import math

import pytest
from astropy.cosmology import FlatLambdaCDM, Flatw0waCDM

from src.analysis import constraints as C
from src.analysis import cosmology as cosmo


class TestCPL:
    def test_lcdm_is_minus_one_at_all_redshifts(self) -> None:
        for z in (0.0, 0.5, 2.0, 1000.0):
            assert cosmo.cpl_w(z, w0=-1.0, wa=0.0) == pytest.approx(-1.0)

    def test_w0_is_value_today(self) -> None:
        assert cosmo.cpl_w(0.0, w0=-0.75, wa=-0.9) == pytest.approx(-0.75)

    def test_high_z_limit_is_w0_plus_wa(self) -> None:
        # z -> infinity gives w0 + wa.
        assert cosmo.cpl_w(1e6, w0=-0.75, wa=-0.9) == pytest.approx(-1.65, abs=1e-3)


class TestBuildCosmology:
    def test_lcdm_case_returns_flat_lambda_cdm(self) -> None:
        model = cosmo.build_cosmology(w0=-1.0, wa=0.0)
        assert isinstance(model, FlatLambdaCDM)

    def test_dynamical_case_returns_w0wa(self) -> None:
        model = cosmo.build_cosmology(w0=-0.75, wa=-0.9)
        assert isinstance(model, Flatw0waCDM)

    def test_omega_m_of_z_increases_toward_high_z(self) -> None:
        # Matter dominates at early times: Omega_m(z) -> 1.
        assert cosmo.omega_m_of_z(0.0) < cosmo.omega_m_of_z(2.0) < cosmo.omega_m_of_z(10.0)
        assert cosmo.omega_m_of_z(0.0) == pytest.approx(cosmo.PLANCK18_OM0, abs=1e-6)


class TestGrowth:
    def test_growth_rate_gr_value_today(self) -> None:
        # f(0) = Omega_m^gamma with Omega_m = 0.3153, gamma = 0.55.
        expected = cosmo.PLANCK18_OM0**0.55
        assert cosmo.growth_rate(0.0, gamma=0.55) == pytest.approx(expected, rel=1e-6)
        assert cosmo.growth_rate(0.0, gamma=0.55) == pytest.approx(0.530, abs=0.01)

    def test_braneworld_gamma_lowers_growth_rate(self) -> None:
        # Larger gamma (DGP ~0.68) suppresses the growth rate at fixed history.
        gr = cosmo.growth_rate(0.0, gamma=C.GAMMA_GR)
        dgp = cosmo.growth_rate(0.0, gamma=C.GAMMA_DGP)
        assert dgp < gr


class TestS8:
    def test_s8_reproduces_planck_from_sigma8_and_omega_m(self) -> None:
        # Strong transcription check: Planck's own sigma8 & Omega_m must give
        # back its published S8 = 0.832.
        got = cosmo.s8(C.PLANCK18["sigma8"].value, C.PLANCK18["omega_m"].value)
        assert got == pytest.approx(C.PLANCK18["s8"].value, abs=0.002)

    def test_s8_sigma8_round_trip(self) -> None:
        sigma8 = cosmo.sigma8_from_s8(0.8, 0.31)
        assert cosmo.s8(sigma8, 0.31) == pytest.approx(0.8)


class TestTension:
    def test_identical_measurements_have_zero_tension(self) -> None:
        m = C.Measurement.symmetric(0.8, 0.02)
        assert cosmo.tension_sigma(m, m) == pytest.approx(0.0)

    def test_planck_kids_s8_tension_is_a_few_sigma(self) -> None:
        # KiDS-1000 sits low vs Planck; papers report a ~2-3 sigma offset.
        planck = C.PLANCK18["s8"]
        kids = C.STAGE3_GROWTH["KiDS-1000"].s8
        sig = cosmo.tension_sigma(planck, kids)
        assert 2.0 < sig < 3.5

    def test_asymmetric_errors_use_the_facing_bar(self) -> None:
        low = C.Measurement(0.70, err_hi=0.05, err_lo=0.01)
        high = C.Measurement(0.90, err_hi=0.01, err_lo=0.05)
        # Facing errors are the large ones (0.05 each) -> modest tension.
        expected = abs(0.90 - 0.70) / math.hypot(0.05, 0.05)
        assert cosmo.tension_sigma(low, high) == pytest.approx(expected)


class TestConstraintsData:
    def test_desi_headline_quadrant_and_significance(self) -> None:
        # The favoured solution is w0 > -1 and wa < 0, most significant with SNe.
        desy5 = C.DESI_DR2_W0WA["DESI+CMB+DESY5"]
        assert desy5.w0.value > -1.0
        assert desy5.wa.value < 0.0
        assert desy5.sigma_vs_lcdm == pytest.approx(4.2)

    def test_all_desi_combos_present_with_provenance(self) -> None:
        assert set(C.DESI_DR2_W0WA) == {
            "DESI+CMB",
            "DESI+CMB+Pantheon+",
            "DESI+CMB+Union3",
            "DESI+CMB+DESY5",
        }
        for rec in C.DESI_DR2_W0WA.values():
            assert rec.arxiv == "2503.14738"
            assert "Tables 5 and 6" in rec.source

    def test_desi_lcdm_offset_of_w0_from_minus_one(self) -> None:
        # w0 = -0.752 is ~4.3 sigma above -1 on its own error bar (sanity).
        desy5 = C.DESI_DR2_W0WA["DESI+CMB+DESY5"]
        n = (desy5.w0.value - (-1.0)) / desy5.w0.error_toward(-1.0)
        assert n > 3.0
