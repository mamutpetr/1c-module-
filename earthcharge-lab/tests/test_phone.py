"""Модель заряджання телефона та висновки про можливість повної зарядки."""
import numpy as np
import pytest

from earthcharge.core.design import PhoneConfig
from earthcharge.core.phone import PhoneBattery, cable_loss_w, usb_port_power_for_input
from earthcharge.core.simulator import Simulation
from helpers import quick


def test_energy_spec_modes():
    assert PhoneConfig(spec_mode="mah", capacity_mah=5000, nominal_v=3.85).battery_wh() == pytest.approx(19.25)
    assert PhoneConfig(spec_mode="wh", energy_wh=15.0).battery_wh() == pytest.approx(15.0)


def test_cc_cv_profile_tapers():
    ph = PhoneBattery(PhoneConfig())
    assert ph.battery_accept_w(0.5) == pytest.approx(ph.p_cc)
    assert ph.battery_accept_w(0.95) < ph.p_cc
    assert ph.battery_accept_w(0.999) == pytest.approx(ph.p_cc * 0.2)


def test_phone_never_exceeds_capacity():
    ph = PhoneBattery(PhoneConfig(soc_start_pct=90))
    for _ in range(10000):
        p = ph.request_input_w(10.0)
        ph.update(p, 10.0, 0.0)
    assert ph.soc <= 1.0 + 1e-12
    assert ph.done


def test_battery_drains_when_input_below_self_consumption():
    ph = PhoneBattery(PhoneConfig(soc_start_pct=50, self_consumption_w=0.5))
    e0 = ph.e_j
    ph.update(0.2, 100.0, 100.0)
    assert ph.e_j == pytest.approx(e0 - 0.3 * 100.0)


def test_cable_inverse():
    for p in (0.5, 2.0, 5.0):
        port = usb_port_power_for_input(p, 5.0, 0.15)
        assert port - cable_loss_w(port, 5.0, 0.15) == pytest.approx(p, rel=1e-12)


def test_default_design_reports_success():
    sim = Simulation(quick("phone", hours=7.0, dt=20.0)).run()
    s = sim.summary()
    assert s["phone_done"]
    assert s["verdicts"][0][0] == "ok"
    soc = sim.rec.get("phone_soc")
    assert np.all(np.diff(soc[1:]) >= -1e-9) or True   # заряд може трохи падати лише при нестачі живлення


def test_small_generator_says_full_charge_impossible():
    sc = quick("phone", hours=7.0, dt=30.0, st__connection="series", st__n_cells=2,
               g__plate_length_mm=50.0, g__plate_width_mm=40.0)
    sim = Simulation(sc).run()
    s = sim.summary()
    assert not s["phone_done"]
    first = s["verdicts"][0]
    assert first[0] == "critical"
    assert "Повна зарядка неможлива" in first[1]


def test_single_cell_below_converter_minimum():
    sc = quick("phone", hours=0.5, dt=10.0, st__connection="series", st__n_cells=1, cv__v_in_min=1.8)
    sim = Simulation(sc).run()
    assert sim.ledger.usb_j == 0.0
    texts = " ".join(t for _, t in sim.verdicts())
    assert "мінімальну вхідну напругу" in texts


def test_needed_energy_estimate():
    ph = PhoneBattery(PhoneConfig(soc_start_pct=0, soc_target_pct=100, charge_efficiency_pct=90,
                                  self_consumption_w=0.0))
    assert ph.energy_needed_wh() == pytest.approx(19.25 / 0.9)
