"""Збереження енергії в усьому ланцюгу: хімія -> комірки -> DC/DC -> шина -> USB -> телефон."""
import pytest

from earthcharge.core import constants as C
from earthcharge.core.simulator import Simulation
from helpers import quick

CASES = {
    "phone": dict(load="phone", hours=2.0),
    "usb_power": dict(load="usb_power", hours=1.0, sim__usb_power_w=2.0),
    "mppt": dict(load="mppt", hours=1.0),
    "resistor": dict(load="resistor", hours=1.0),
    "current": dict(load="current", hours=1.0, sim__current_a=0.8),
    "open": dict(load="open", hours=1.0, dt=30.0),
    "smartboost": dict(load="phone", hours=0.5, dt=1.0, sc__enabled=True, sc__start_delay_s=30.0),
    "shunt": dict(load="mppt", hours=1.0, st__shared_electrolyte=True, st__n_cells=4),
    "parallel": dict(load="phone", hours=1.0, st__connection="parallel", st__n_cells=2, cv__v_in_min=0.6),
    "mixed": dict(load="phone", hours=1.0, st__connection="mixed", st__n_series=2, st__n_parallel=2),
    "dips": dict(load="phone", hours=1.0, dt=2.0, dist__enabled=True, dist__mean_interval_s=120.0,
                 sc__enabled=True, sc__start_delay_s=0.0),
    "no_thermal": dict(load="phone", hours=1.0, env__thermal_model=False),
    "graphite": dict(load="resistor", hours=1.0, d__cathode="graphite", sim__resistor_ohm=50.0),
    "simple_converter_overload": dict(load="usb_power", hours=0.5, cv__control="simple", sim__usb_power_w=50.0),
}


@pytest.mark.parametrize("name", list(CASES))
def test_all_identities_close(name):
    kw = dict(CASES[name])
    sim = Simulation(quick(kw.pop("load"), hours=kw.pop("hours"), dt=kw.pop("dt", 10.0), **kw)).run()
    scale = max(sim.ledger.ideal_j, 1.0)
    for label, r in sim.residuals().items():
        tol = 1e-9 if "Фарадей" in label else 1e-7 * scale
        assert abs(r) <= tol, f"{name}: {label} = {r}"


@pytest.mark.parametrize("name", list(CASES))
def test_output_never_exceeds_chemistry(name):
    kw = dict(CASES[name])
    sim = Simulation(quick(kw.pop("load"), hours=kw.pop("hours"), dt=kw.pop("dt", 10.0), **kw)).run()
    lg = sim.ledger
    assert lg.cells_out_j <= lg.ideal_j + 1e-9
    assert lg.terminal_j <= lg.cells_out_j + 1e-9
    assert lg.bus_j <= lg.conv_in_j + 1e-9
    # електрична енергія не може перевищити енергію Гіббса розчиненого магнію
    z = C.FARADAY * sim.cell.e_per_g
    gibbs = sim.mg_consumed_cell_g() * sim.n * z * C.E_REV_MG_AIR
    assert lg.terminal_j <= gibbs + 1e-6


def test_breakdown_sums_to_ideal():
    sim = Simulation(quick("phone", hours=2.0)).run()
    total = sum(sim.ledger_breakdown().values())
    # стаття «залишок у конденсаторі» = 0 без конденсатора; сума статей = ідеальна енергія мінус енергія,
    # що залишилася в телефоні як "stored" (вона теж стаття) -> рівно ideal_j
    assert total == pytest.approx(sim.ledger.ideal_j, rel=1e-9)


def test_breakdown_sums_to_ideal_smartboost():
    sim = Simulation(quick("phone", hours=0.3, dt=1.0, sc__enabled=True)).run()
    total = sum(sim.ledger_breakdown().values())
    assert total == pytest.approx(sim.ledger.ideal_j, rel=1e-9)


def test_specific_energy_in_practical_range():
    """Практична питома енергія Mg-повітря в NaCl — близько 1–2 Вт·год/г Mg; теоретична 6,8."""
    sim = Simulation(quick("phone", hours=7.0, dt=20.0)).run()
    s = sim.summary()
    assert 0.5 < s["wh_per_g_term"] < 2.5
    assert s["wh_per_g_term"] < 6.8
