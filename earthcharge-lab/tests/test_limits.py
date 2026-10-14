"""Граничні значення та перевірка введення."""
import pytest

from earthcharge.core.design import Design, validate_design, validate_phone, has_errors, PhoneConfig
from earthcharge.core.simulator import Simulation, SimulationError
from helpers import quick


def errors(d):
    return [i.message for i in validate_design(d) if i.level == "error"]


@pytest.mark.parametrize("attr,value", [
    ("plate_length_mm", 0.0), ("plate_width_mm", -5.0), ("plate_thickness_mm", 0.0),
    ("gap_mm", 0.0), ("electrolyte_volume_ml", 0.0), ("active_fraction", 1.5), ("max_utilization", 0.0),
])
def test_invalid_geometry_rejected(attr, value):
    d = Design()
    setattr(d.geometry, attr, value)
    assert errors(d)
    sc = quick()
    setattr(sc.design.geometry, attr, value)
    with pytest.raises(SimulationError):
        Simulation(sc)


def test_freezing_electrolyte_is_error():
    d = Design()
    d.environment.ambient_c = -10.0
    assert any("замерзання" in e for e in errors(d))


def test_brine_survives_light_frost():
    d = Design()
    d.electrolyte = "nacl_10"
    d.environment.ambient_c = -5.0
    assert not errors(d)


def test_smartboost_delay_limits():
    d = Design()
    d.supercap.enabled = True
    d.supercap.start_delay_s = 301
    assert errors(d)
    d.supercap.start_delay_s = 300
    assert not errors(d)


def test_phone_validation():
    assert has_errors(validate_phone(PhoneConfig(soc_start_pct=90, soc_target_pct=80)))
    assert has_errors(validate_phone(PhoneConfig(max_charge_power_w=0.1, self_consumption_w=0.2)))
    assert not has_errors(validate_phone(PhoneConfig()))


def test_mg_exhaustion_stops_simulation():
    sc = quick("mppt", hours=48.0, dt=60.0, g__plate_thickness_mm=0.2)
    sim = Simulation(sc).run()
    assert sim.finish_reason.startswith("Магній")
    assert sim.state.t < 48 * 3600
    assert sim.mg_consumed_cell_g() >= sim.mg_usable_cell_g * 0.999


def test_tiny_water_volume_dries_out():
    sc = quick("mppt", hours=24.0, dt=60.0, g__electrolyte_volume_ml=3.0)
    sim = Simulation(sc).run()
    assert "Електроліт" in sim.finish_reason or "Магній" in sim.finish_reason or "Перегрів" in sim.finish_reason


def test_zero_current_load():
    sim = Simulation(quick("current", hours=0.5, sim__current_a=0.0)).run()
    assert sim.ledger.terminal_j == pytest.approx(0.0, abs=1e-12)


def test_huge_current_request_is_capped_by_short_circuit():
    sim = Simulation(quick("current", hours=0.1, sim__current_a=1000.0)).run()
    assert sim.rec.get("i_ext").max() < 1000.0
    assert any("недосяжний" in e.text for e in sim.events)


def test_simple_converter_trips_on_overload():
    sim = Simulation(quick("usb_power", hours=0.2, cv__control="simple", sim__usb_power_w=50.0)).run()
    assert sim.state.converter_trips > 0
    assert sim.ledger.usb_j == 0.0


def test_mppt_converter_delivers_maximum_on_overload():
    sim = Simulation(quick("usb_power", hours=0.2, cv__control="mppt", sim__usb_power_w=50.0)).run()
    assert sim.ledger.usb_j > 0


def test_converter_disabled_blocks_usb():
    sim = Simulation(quick("phone", hours=0.2, cv__enabled=False)).run()
    assert sim.ledger.usb_j == 0.0


def test_heat_warning_and_temperature_bounded():
    sim = Simulation(quick("mppt", hours=3.0, dt=20.0, env__heat_area_override_cm2=20.0)).run()
    assert sim.state.peak_t_el <= 100.5


def test_disturbances_reduce_area_temporarily():
    sim = Simulation(quick("phone", hours=1.0, dt=2.0, dist__enabled=True, dist__mean_interval_s=200.0,
                           dist__duration_s=20.0, dist__depth_pct=60.0)).run()
    af = sim.rec.get("area_factor")
    assert af.min() == pytest.approx(40.0)
    assert af.max() == pytest.approx(100.0)
