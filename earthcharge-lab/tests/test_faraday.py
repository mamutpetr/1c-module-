"""Закон Фарадея: зв'язок струму, заряду, маси Mg і водню."""
import pytest

from earthcharge.core import constants as C
from earthcharge.core.simulator import Simulation
from helpers import quick


def test_mass_matches_charge_resistor_load():
    sim = Simulation(quick("resistor", hours=2.0, sim__resistor_ohm=2.0)).run()
    st = sim.state
    z = C.FARADAY * sim.cell.e_per_g
    assert st.mg_useful_g == pytest.approx(st.q_useful_c / z, rel=1e-12)
    assert st.mg_corr_g == pytest.approx(st.q_corr_c / z, rel=1e-12)
    # корисна маса через інтеграл струму з графіка (метод трапецій ≈ прямокутники Ейлера)
    t = sim.rec.get("t_h") * 3600.0
    i_cell = sim.rec.get("i_ext")[1:] / sim.geo.n_parallel
    q = float((i_cell * (t[1:] - t[:-1])).sum())
    assert st.q_useful_c == pytest.approx(q, rel=1e-9)


def test_pure_mg_grams_per_amp_hour():
    sc = quick("current", hours=1.0, d__anode="mg_pure", sim__current_a=1.0, st__connection="series", st__n_cells=1)
    sim = Simulation(sc).run()
    # 1 А протягом 1 год -> 0,4534 г корисного Mg
    assert sim.state.mg_useful_g == pytest.approx(0.4534, rel=2e-3)


def test_hydrogen_volume_from_corrosion():
    sim = Simulation(quick("open", hours=3.0, dt=30.0)).run()
    st = sim.state
    mol_mg = st.mg_corr_g * sim.n * sim.cell.e_per_g / 2.0   # моль-еквівалентів Mg2+
    h2_ml = mol_mg * C.molar_gas_volume_l(25.0) * 1000.0
    assert st.h2_ml == pytest.approx(h2_ml, rel=1e-9)
    assert st.mg_useful_g == 0.0


def test_anode_efficiency_formula():
    sim = Simulation(quick("current", hours=1.0, sim__current_a=1.0)).run()
    s = sim.summary()
    st = sim.state
    expected = 100.0 * st.q_useful_c / (st.q_useful_c + st.q_corr_c + st.q_chunk_c)
    assert s["anode_eff_pct"] == pytest.approx(expected)
    assert 0 < s["anode_eff_pct"] < 100


def test_mass_bookkeeping_totals():
    sim = Simulation(quick("phone", hours=2.0)).run()
    s = sim.summary()
    assert s["mg_consumed_g"] == pytest.approx(s["mg_useful_g"] + s["mg_corr_g"] + s["mg_chunk_g"])
    assert s["mg_remaining_g"] == pytest.approx(s["mg_initial_g"] - s["mg_consumed_g"])
