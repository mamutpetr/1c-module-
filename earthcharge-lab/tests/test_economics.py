"""Бізнес-калькулятор картриджів (відокремлений від фізики)."""
import pytest

from earthcharge.core.economics import PhysicsInputs, Prices, cartridge_cost, compare_cartridges, physics_from_simulation
from earthcharge.core.simulator import Simulation
from helpers import quick


def test_margin_definition():
    c = cartridge_cost(PhysicsInputs(), Prices(target_margin_pct=40.0), 1)
    assert c.gross_margin_pct == pytest.approx(40.0)
    assert c.price_net == pytest.approx(c.cogs / 0.6)
    assert c.price_retail == pytest.approx(c.price_net * 1.2)
    assert c.cogs == pytest.approx(sum(c.lines.values()))


def test_mg_mass_scales_with_charges():
    phys = PhysicsInputs(mg_per_charge_g=10.0, max_utilization=0.8)
    p = Prices(reserve_pct=0.0, electrolyte_drained=True)
    one, three, five = compare_cartridges(phys, p)
    assert one.mg_mass_g == pytest.approx(12.5)
    assert three.mg_mass_g == pytest.approx(37.5)
    assert five.mg_mass_g == pytest.approx(62.5)
    assert five.cost_per_charge_customer < one.cost_per_charge_customer


def test_idle_corrosion_when_electrolyte_kept():
    phys = PhysicsInputs(mg_per_charge_g=10.0, idle_corrosion_g_per_h=0.1, max_utilization=1.0)
    kept = cartridge_cost(phys, Prices(reserve_pct=0, electrolyte_drained=False, hours_between_charges=24), 3)
    drained = cartridge_cost(phys, Prices(reserve_pct=0, electrolyte_drained=True), 3)
    assert kept.mg_mass_g == pytest.approx(30.0 + 0.1 * 48)
    assert drained.mg_mass_g == pytest.approx(30.0)


def test_cathode_in_device_amortized():
    phys = PhysicsInputs(cathode_area_total_cm2=100.0)
    dev = cartridge_cost(phys, Prices(cathode_location="device", cathode_life_charges=50, cathode_price_per_cm2=1.0), 1)
    car = cartridge_cost(phys, Prices(cathode_location="cartridge", cathode_price_per_cm2=1.0), 1)
    assert dev.lines["cathode"] == pytest.approx(2.0)
    assert car.lines["cathode"] == pytest.approx(100.0)


def test_mg_price_changes_only_mg_line():
    phys = PhysicsInputs()
    a = cartridge_cost(phys, Prices(mg_price_per_kg=100.0), 3)
    b = cartridge_cost(phys, Prices(mg_price_per_kg=200.0), 3)
    assert b.lines["mg"] == pytest.approx(2 * a.lines["mg"])
    assert b.lines["housing"] == a.lines["housing"]


def test_invalid_charges():
    with pytest.raises(ValueError):
        cartridge_cost(PhysicsInputs(), Prices(), 0)


def test_physics_adapter_uses_simulation():
    sim = Simulation(quick("phone", hours=7.0, dt=30.0)).run()
    phys = physics_from_simulation(sim)
    assert phys.mg_per_charge_g > 0
    assert phys.mg_per_charge_g <= sim.summary()["mg_consumed_g"] + 1e-9
    assert phys.usb_wh_per_charge > 15
    assert phys.idle_corrosion_g_per_h > 0
