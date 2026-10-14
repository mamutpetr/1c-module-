"""Бізнес-калькулятор картриджів EarthCharge.

Фінансова модель відокремлена від фізики: вона отримує лише підсумкові фізичні величини
(PhysicsInputs) — масу Mg на одне заряджання, площі, об'єм електроліту тощо. Усі ціни
редагуються; значення за замовчуванням — приклад для демонстрації, а не ринкові ціни.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Prices:
    currency: str = "грн"
    mg_price_per_kg: float = 800.0           # листовий сплав (приклад)
    cathode_price_per_cm2: float = 0.40
    cathode_location: str = "device"         # "cartridge" — катод у картриджі; "device" — багаторазовий у пристрої
    cathode_life_charges: float = 50.0
    separator_price_per_cm2: float = 0.02
    salt_price_per_kg: float = 20.0
    electrolyte_pack_per_activation: float = 2.0
    housing_base: float = 25.0
    housing_extra_per_charge: float = 4.0
    contacts_cost: float = 6.0
    assembly_cost: float = 20.0
    packaging_cost: float = 8.0
    overhead_pct: float = 15.0
    defect_pct: float = 3.0
    logistics_per_unit: float = 6.0
    target_margin_pct: float = 45.0
    vat_pct: float = 20.0
    reserve_pct: float = 15.0                # запас магнію понад розрахунок
    hours_between_charges: float = 24.0
    electrolyte_drained: bool = True         # електроліт зливають після кожного заряджання


@dataclass
class PhysicsInputs:
    mg_per_charge_g: float = 16.0            # витрата Mg на одне повне заряджання (корисне + корозія)
    usb_wh_per_charge: float = 18.0
    anode_area_total_cm2: float = 300.0
    cathode_area_total_cm2: float = 300.0
    electrolyte_ml_per_activation: float = 210.0
    salt_wt_pct: float = 3.5
    electrolyte_density: float = 1.023
    max_utilization: float = 0.85
    idle_corrosion_g_per_h: float = 0.1      # самокорозія без навантаження, якщо електроліт не злито
    source: str = "Ручне введення"


@dataclass
class CartridgeCost:
    charges: int
    mg_mass_g: float
    lines: dict = field(default_factory=dict)   # стаття -> вартість на картридж
    cogs: float = 0.0
    price_net: float = 0.0
    price_retail: float = 0.0
    gross_margin_pct: float = 0.0
    gross_profit: float = 0.0
    cost_per_charge_customer: float = 0.0
    cogs_per_charge: float = 0.0
    price_per_wh: float = 0.0


LINE_LABELS = {
    "mg": "Магній",
    "cathode": "Повітряний катод",
    "separator": "Сепаратор",
    "electrolyte": "Електроліт (сіль + пакування)",
    "housing": "Корпус картриджа",
    "contacts": "Контакти",
    "assembly": "Виробництво / складання",
    "packaging": "Упаковка",
    "overhead": "Накладні витрати",
    "defects": "Брак",
    "logistics": "Логістика",
}


def cartridge_mg_mass(phys: PhysicsInputs, prices: Prices, charges: int) -> float:
    idle_h = 0.0 if prices.electrolyte_drained else prices.hours_between_charges * max(charges - 1, 0)
    consumed = phys.mg_per_charge_g * charges + phys.idle_corrosion_g_per_h * idle_h
    return consumed * (1.0 + prices.reserve_pct / 100.0) / max(phys.max_utilization, 1e-6)


def cartridge_cost(phys: PhysicsInputs, prices: Prices, charges: int) -> CartridgeCost:
    if charges < 1:
        raise ValueError("Кількість заряджань має бути ≥ 1.")
    mg = cartridge_mg_mass(phys, prices, charges)
    lines = {}
    lines["mg"] = mg / 1000.0 * prices.mg_price_per_kg
    cath_full = phys.cathode_area_total_cm2 * prices.cathode_price_per_cm2
    if prices.cathode_location == "cartridge":
        lines["cathode"] = cath_full
    else:
        lines["cathode"] = cath_full * charges / max(prices.cathode_life_charges, 1e-6)
    lines["separator"] = phys.anode_area_total_cm2 * prices.separator_price_per_cm2
    salt_g = phys.electrolyte_ml_per_activation * phys.electrolyte_density * phys.salt_wt_pct / 100.0
    lines["electrolyte"] = charges * (salt_g / 1000.0 * prices.salt_price_per_kg + prices.electrolyte_pack_per_activation)
    lines["housing"] = prices.housing_base + prices.housing_extra_per_charge * (charges - 1)
    lines["contacts"] = prices.contacts_cost
    lines["assembly"] = prices.assembly_cost
    lines["packaging"] = prices.packaging_cost
    direct = sum(lines.values())
    lines["overhead"] = direct * prices.overhead_pct / 100.0
    with_overhead = direct + lines["overhead"]
    defect = min(max(prices.defect_pct, 0.0), 95.0) / 100.0
    lines["defects"] = with_overhead / (1.0 - defect) - with_overhead
    lines["logistics"] = prices.logistics_per_unit
    cogs = sum(lines.values())
    margin = min(max(prices.target_margin_pct, 0.0), 99.0) / 100.0
    price_net = cogs / (1.0 - margin)
    retail = price_net * (1.0 + prices.vat_pct / 100.0)
    wh = phys.usb_wh_per_charge * charges
    return CartridgeCost(
        charges=charges, mg_mass_g=mg, lines=lines, cogs=cogs, price_net=price_net, price_retail=retail,
        gross_margin_pct=100.0 * (price_net - cogs) / price_net if price_net > 0 else 0.0,
        gross_profit=price_net - cogs,
        cost_per_charge_customer=retail / charges, cogs_per_charge=cogs / charges,
        price_per_wh=retail / wh if wh > 0 else math.nan,
    )


def compare_cartridges(phys: PhysicsInputs, prices: Prices, options=(1, 3, 5)) -> list[CartridgeCost]:
    return [cartridge_cost(phys, prices, n) for n in options]


def physics_from_simulation(sim) -> PhysicsInputs:
    """Бере фізичні підсумки з виконаної симуляції заряджання телефона (без фінансів)."""
    s = sim.summary()
    geo = sim.geo
    cell = sim.cell
    ps = sim.ps
    if sim.phone and sim.phone.done and sim.phone.t_done_s:
        # витрата Mg саме до моменту завершення заряджання
        t_h = sim.rec.get("t_h")
        k = int(min(len(t_h) - 1, max(0, (t_h <= sim.phone.t_done_s / 3600.0 + 1e-9).sum() - 1)))
        mg = float(sim.rec.get("mg_useful_g")[k] + sim.rec.get("mg_corr_g")[k] + sim.rec.get("mg_chunk_g")[k])
        usb = float(sim.rec.get("e_usb_wh")[k])
        src = "Симуляція: повне заряджання телефона"
    else:
        mg = s["mg_consumed_g"]
        usb = s["e_usb_wh"]
        src = "Симуляція (телефон не заряджено повністю — оцінка за весь час)"
    from .constants import FARADAY
    idle = cell.A_a0 * cell.i_corr0 * geo.n_cells / (FARADAY * cell.e_per_g) * 3600.0
    return PhysicsInputs(
        mg_per_charge_g=mg, usb_wh_per_charge=usb,
        anode_area_total_cm2=geo.anode_area_cm2 * geo.n_cells,
        cathode_area_total_cm2=geo.cathode_area_cm2 * geo.n_cells,
        electrolyte_ml_per_activation=geo.electrolyte_total_ml,
        salt_wt_pct=ps.v("electrolyte.salt_pct"), electrolyte_density=ps.v("electrolyte.density"),
        max_utilization=sim.design.geometry.max_utilization,
        idle_corrosion_g_per_h=idle, source=src,
    )
