"""Одиниці вимірювання та фундаментальні співвідношення."""
import math

import pytest

from earthcharge.core import constants as C
from earthcharge.core import materials as M
from earthcharge.core.units import (format_duration, mah_from_wh, mg_corrosion_mm_per_year_from_ma_cm2,
                                    mg_grams_per_ah, mg_specific_capacity_mah_g, wh_from_j, wh_from_mah, j_from_wh,
                                    cm2_from_mm, cm3_from_mm)


def test_phone_battery_energy():
    assert wh_from_mah(5000, 3.85) == pytest.approx(19.25)
    assert mah_from_wh(19.25, 3.85) == pytest.approx(5000)


def test_energy_conversions_roundtrip():
    assert wh_from_j(3600.0) == pytest.approx(1.0)
    assert j_from_wh(wh_from_j(12345.6)) == pytest.approx(12345.6)


def test_geometry_units():
    assert cm2_from_mm(100, 60) == pytest.approx(60.0)
    assert cm3_from_mm(100, 60, 1.5) == pytest.approx(9.0)


def test_magnesium_faraday_constants():
    assert mg_specific_capacity_mah_g() == pytest.approx(2205.4, rel=1e-3)
    assert mg_grams_per_ah() == pytest.approx(0.4534, rel=1e-3)
    assert mg_corrosion_mm_per_year_from_ma_cm2(1.0) == pytest.approx(22.9, rel=1e-2)


def test_thermodynamics():
    assert C.E_REV_MG_AIR == pytest.approx(3.09, abs=0.01)
    assert C.E_TN_MG_AIR == pytest.approx(3.31, abs=0.01)
    assert C.E_TN_MG_AIR > C.E_REV_MG_AIR
    assert C.molar_gas_volume_l(25.0) == pytest.approx(24.465, rel=1e-3)
    assert C.o2_concentration_air_mol_m3(25.0) == pytest.approx(8.56, rel=1e-2)


def test_alloy_capacity_close_to_magnesium():
    pure = M.ANODES["mg_pure"].specific_capacity_mah_g()
    assert pure == pytest.approx(mg_specific_capacity_mah_g(), rel=1e-9)
    for a in M.ANODES.values():
        assert sum(a.composition_wt.values()) == pytest.approx(1.0, abs=1e-6)
        assert 1500 < a.specific_capacity_mah_g() < 2600


def test_o2_solubility_table():
    assert C.o2_solubility_water_mol_m3(25.0) == pytest.approx(8.26 / 31.998, rel=1e-6)
    assert C.o2_solubility_water_mol_m3(5.0) > C.o2_solubility_water_mol_m3(35.0)


def test_her_potential_nernst():
    assert C.e_her_vs_sce(7.0) == pytest.approx(-0.2415 - 0.05916 * 7, abs=1e-3)


def test_format_duration():
    assert format_duration(45) == "45 с"
    assert format_duration(6 * 3600 + 41 * 60) == "6 год 41 хв"
    assert format_duration(math.inf) == "—"


def test_every_parameter_has_status():
    for lib in (M.ANODES, M.CATHODES, M.ELECTROLYTES, M.SEPARATORS):
        for item in lib.values():
            for key, p in item.props.items():
                assert p.status is not None and p.label and p.unit is not None, key
