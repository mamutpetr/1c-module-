"""Залежність напруги від струму, втрати, обмеження катода й електроліту."""
import numpy as np
import pytest

from earthcharge.core.analysis import analyze
from earthcharge.core.design import Design, derive_geometry
from earthcharge.core.electrochem import CellModel
from earthcharge.core.params import build_params, set_override


def make_cell(**kw) -> CellModel:
    d = Design()
    for k, v in kw.items():
        obj, attr = k.split("__")
        setattr({"g": d.geometry, "d": d, "env": d.environment}[obj], attr, v)
    ps = build_params(d)
    return CellModel(d, ps, derive_geometry(d, ps.v("anode.density")))


def test_voltage_decreases_with_current():
    cell = make_cell()
    i = np.linspace(0, cell.current_upper(), 200)
    v = cell.v_cell(i)
    assert v[0] == pytest.approx(cell.ocv)
    assert np.all(np.diff(v) < 0)


def test_ocv_in_reported_range():
    cell = make_cell()
    assert 1.4 < cell.ocv < 1.9


def test_scalar_and_vector_paths_agree():
    cell = make_cell()
    i = np.linspace(0, cell.current_upper(), 57)
    assert np.allclose(cell.v_cell(i), [cell.v_cell(float(x)) for x in i], atol=1e-12)


def test_electrolyte_resistance_formula():
    cell = make_cell(g__gap_mm=4.0)
    ps = cell.ps
    expected = 0.4 * ps.v("separator.macmullin") / (ps.v("electrolyte.sigma") / 100.0 * cell.A_a)
    assert cell.r_el == pytest.approx(expected, rel=1e-9)
    assert make_cell(g__gap_mm=8.0).r_el == pytest.approx(2 * cell.r_el, rel=1e-9)


def test_tap_water_much_weaker_than_salt():
    salt = analyze(Design())
    tap = Design()
    tap.electrolyte = "tap_water"
    tap_a = analyze(tap)
    assert tap_a.r_el_mohm > 50 * salt.r_el_mohm
    assert tap_a.p_max_term_w < 0.2 * salt.p_max_term_w


def test_current_limited_by_cathode_area():
    """Вище граничного струму катода напруга обвалюється (переходить на виділення H₂)."""
    cell = make_cell()
    i_lim = cell.i_lim * cell.A_c
    assert cell.v_cell(0.5 * i_lim) > 0.5
    assert cell.v_cell(1.02 * i_lim) < 0.3


def test_vents_limit_oxygen_supply():
    open_cell = make_cell()
    vent = make_cell(env__air_access="vents", env__vent_area_cm2=0.2, env__vent_length_mm=10.0)
    assert vent.i_lim < open_cell.i_lim
    assert vent.i_lim_supply < open_cell.i_lim * 2


def test_graphite_limited_by_dissolved_oxygen():
    cell = make_cell(d__cathode="graphite")
    # граничний струм за розчиненим O2 ~ 0,05–0,2 мА/см²
    assert 0.03e-3 < cell.i_lim < 0.3e-3
    air = make_cell()
    i = 1e-3 * cell.A_a
    assert cell.v_cell(i) < air.v_cell(i) - 0.5


def test_passivation_increases_resistance():
    cell = make_cell()
    v0 = cell.v_cell(1.0)
    cell.set_conditions(25.0, q_pass_c_cm2=200.0)
    assert cell.asr_pass > 0
    assert cell.v_cell(1.0) < v0


def test_sludge_reduces_conductivity():
    cell = make_cell()
    r0 = cell.r_el
    cell.set_conditions(25.0, sludge_fraction=0.3)
    assert cell.r_el == pytest.approx(r0 / (0.7 ** 1.5), rel=1e-9)


def test_temperature_raises_conductivity_and_corrosion():
    cold = make_cell(env__ambient_c=5.0)
    warm = make_cell(env__ambient_c=40.0)
    assert warm.r_el < cold.r_el
    assert warm.i_corr0 > cold.i_corr0


def test_anode_efficiency_rises_toward_nde_limit():
    cell = make_cell()
    low = cell.anode_efficiency(0.001 * cell.A_a)
    high = cell.anode_efficiency(0.02 * cell.A_a)
    assert low < high
    limit = 1.0 / (1.0 + cell.k_nde + cell.k_chunk)
    assert high < limit


def test_override_changes_model():
    d = Design()
    set_override(d, "anode.k_nde", 0.1)
    ps = build_params(d)
    cell = CellModel(d, ps, derive_geometry(d, ps.v("anode.density")))
    assert cell.k_nde == pytest.approx(0.1)
    assert ps.prop("anode.k_nde").status.value == "user"


def test_series_doubles_voltage_parallel_doubles_current():
    d1 = Design()
    d1.stack.connection, d1.stack.n_cells = "series", 1
    a1 = analyze(d1)
    d2 = Design()
    d2.stack.connection, d2.stack.n_cells = "series", 2
    d2.stack.wiring_resistance_mohm = d1.stack.wiring_resistance_mohm = 0.0
    a2 = analyze(d2)
    assert a2.ocv_stack == pytest.approx(2 * a1.ocv_stack, rel=1e-9)
    d3 = Design()
    d3.stack.connection, d3.stack.n_cells = "parallel", 2
    a3 = analyze(d3)
    assert a3.i_short_a == pytest.approx(2 * a1.i_short_a, rel=1e-6)
