"""SmartBoost: суперконденсатор переносить енергію в часі, але не створює її."""
import numpy as np
import pytest

from earthcharge.core.design import SupercapConfig
from earthcharge.core.simulator import Simulation
from earthcharge.core.smartboost import Supercap
from helpers import quick


def test_charge_from_zero_voltage_and_balance():
    cap = Supercap(SupercapConfig(enabled=True, capacitance_f=10.0, v_max=5.0, v_initial=0.0))
    for _ in range(200):
        cap.charge(cap.charge_request_bus_w(1.0), 1.0)
    assert cap.v == pytest.approx(5.0, rel=1e-3)
    assert cap.e <= cap.e_max + 1e-9
    assert abs(cap.balance_residual_j()) < 1e-9


def test_discharge_never_below_min_voltage():
    cfg = SupercapConfig(enabled=True, capacitance_f=10.0, v_max=5.0, v_min=1.0, v_initial=5.0, leakage_ua=0.0)
    cap = Supercap(cfg)
    delivered = 0.0
    for _ in range(1000):
        delivered += cap.discharge(20.0, 0.5) * 0.5
    assert cap.v >= 1.0 - 1e-6
    usable = 0.5 * 10 * (25 - 1)
    assert delivered < usable          # втрати DC/DC і ESR
    assert delivered > 0.8 * usable
    assert abs(cap.balance_residual_j()) < 1e-9


def test_round_trip_loses_energy():
    cfg = SupercapConfig(enabled=True, capacitance_f=25.0, v_max=5.0, v_min=1.0, v_initial=0.0)
    cap = Supercap(cfg)
    e_in = 0.0
    for _ in range(2000):
        p = cap.charge_request_bus_w(1.0)
        cap.charge(p, 1.0)
        e_in += p
    assert cap.soc > 0.99
    e_out = 0.0
    for _ in range(2000):
        e_out += cap.discharge(5.0, 1.0)
    assert cap.soc < 0.01
    assert e_out < e_in
    assert e_out / e_in > 0.7


def test_usb_off_before_start_delay_and_energy_stored():
    sc = quick("phone", hours=0.2, dt=1.0, sc__enabled=True, sc__start_delay_s=60.0)
    sim = Simulation(sc).run()
    t = sim.rec.get("t_h") * 3600.0
    p_usb = sim.rec.get("p_usb")
    assert np.all(p_usb[t < 60 - 1e-9] == 0.0)
    cap_j = sim.rec.get("cap_j")
    k = int(np.searchsorted(t, 60 - 1e-9))
    assert cap_j[k] > 0
    # енергія в конденсаторі не більша за енергію рушія за ці 60 с
    gen_bus = sim.rec.get("p_gen_bus")[1:k + 1]
    assert cap_j[k] <= gen_bus.sum() * 1.0 + 1e-6


def test_boost_cannot_exceed_generator_plus_storage():
    sc = quick("phone", hours=0.5, dt=1.0, sc__enabled=True, sc__start_delay_s=120.0, ph__max_charge_power_w=10.0)
    sim = Simulation(sc).run()
    lg = sim.ledger
    cl = sim.cap.ledger
    assert lg.usb_j <= lg.bus_j + cl.initial_j + 1e-6
    assert cl.bus_out_j <= cl.bus_in_j + cl.initial_j


def test_reports_cannot_sustain_after_pulse():
    sc = quick("phone", hours=0.5, dt=1.0, sc__enabled=True, sc__start_delay_s=30.0,
               ph__max_charge_power_w=10.0, cv__p_out_max_w=10.0, st__n_cells=1, g__plate_length_mm=60.0)
    sim = Simulation(sc).run()
    texts = " ".join(t for _, t in sim.verdicts())
    assert "не створює енергії" in texts
    assert "конденсатор розрядився" in texts


@pytest.mark.parametrize("delay", [0.0, 30.0, 300.0])
def test_delay_range(delay):
    sim = Simulation(quick("phone", hours=0.1, dt=1.0, sc__enabled=True, sc__start_delay_s=delay)).run()
    assert abs(sim.cap.balance_residual_j()) < 1e-6
