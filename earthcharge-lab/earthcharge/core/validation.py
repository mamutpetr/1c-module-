"""Самоперевірка моделі, яку можна запустити з інтерфейсу (дублює ключові автоматичні тести)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import constants as C
from .design import Scenario, clone
from .simulator import Simulation
from .units import mg_corrosion_mm_per_year_from_ma_cm2, mg_grams_per_ah, mg_specific_capacity_mah_g, wh_from_mah


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1e-12)


def run_model_checks(base: Scenario | None = None) -> list[Check]:
    out: list[Check] = []
    add = lambda n, ok, d: out.append(Check(n, bool(ok), d))

    # --- одиниці та константи
    cap = mg_specific_capacity_mah_g()
    add("Питома ємність Mg = 2205 мА·год/г", _close(cap, 2205.0, 2e-3), f"{cap:.1f} мА·год/г")
    g_ah = mg_grams_per_ah()
    add("Фарадей: 0,4534 г Mg на 1 А·год", _close(g_ah, 0.4534, 1e-3), f"{g_ah:.4f} г/(А·год)")
    add("Оборотна напруга Mg-повітря ≈ 3,09 В", _close(C.E_REV_MG_AIR, 3.09, 5e-3), f"{C.E_REV_MG_AIR:.3f} В")
    vm = C.molar_gas_volume_l(25.0)
    add("Молярний об'єм газу при 25 °C = 24,47 л", _close(vm, 24.465, 1e-3), f"{vm:.3f} л/моль")
    wh = wh_from_mah(5000, 3.85)
    add("5000 мА·год × 3,85 В = 19,25 Вт·год", _close(wh, 19.25, 1e-9), f"{wh:.3f} Вт·год")
    mmy = mg_corrosion_mm_per_year_from_ma_cm2(1.0)
    add("1 мА/см² корозії Mg ≈ 22,9 мм/рік", _close(mmy, 22.9, 1e-2), f"{mmy:.2f} мм/рік")

    # --- короткі симуляції: базова, SmartBoost, резистор, без навантаження
    base = clone(base) if base is not None else Scenario()
    cases = []
    sc = clone(base)
    sc.sim.dt_s = 10.0
    sc.phone.max_time_h = 1.0
    sc.sim.load_mode = "phone"
    cases.append(("Смартфон", sc))
    sb = clone(sc)
    sb.design.supercap.enabled = True
    sb.design.supercap.start_delay_s = 30.0
    sb.sim.dt_s = 1.0
    sb.phone.max_time_h = 0.25
    cases.append(("SmartBoost", sb))
    rs = clone(base)
    rs.sim.load_mode, rs.sim.duration_h, rs.sim.dt_s = "resistor", 1.0, 10.0
    cases.append(("Резистор", rs))
    op = clone(base)
    op.sim.load_mode, op.sim.duration_h, op.sim.dt_s = "open", 1.0, 30.0
    cases.append(("Без навантаження", op))

    for label, sc in cases:
        try:
            sim = Simulation(sc).run()
        except Exception as exc:  # noqa: BLE001
            add(f"{label}: симуляція", False, str(exc))
            continue
        scale = max(sim.ledger.ideal_j, 1.0)
        worst = max(abs(v) for v in sim.residuals().values())
        add(f"{label}: збереження енергії (усі тотожності)", worst <= 1e-6 * scale,
            f"найбільший залишок {worst:.2e} Дж при {scale:.0f} Дж")
        lg = sim.ledger
        add(f"{label}: вихід ≤ хімічної енергії Mg", lg.terminal_j <= lg.ideal_j + 1e-9,
            f"{lg.terminal_j / 3600:.3f} ≤ {lg.ideal_j / 3600:.3f} Вт·год")
        v = sim.rec.get("v_cell")
        add(f"{label}: напруга комірки ≤ НРК < 3,09 В",
            bool(np.all(v <= sim.cell.ocv + 1e-9)) and sim.cell.ocv < C.E_REV_MG_AIR,
            f"макс. {np.nanmax(v):.3f} В, НРК {sim.cell.ocv:.3f} В")
        eff = sim.rec.get("anode_eff")
        eff = eff[np.isfinite(eff)]
        add(f"{label}: ефективність анода в межах 0–100%", bool(np.all((eff >= -1e-9) & (eff <= 100 + 1e-9))),
            f"{eff.min() if eff.size else 0:.1f}…{eff.max() if eff.size else 0:.1f}%")
        st = sim.state
        h2_expected = (st.q_corr_c * sim.n / (2 * C.FARADAY)) * vm * 1000.0
        h2_cath = st.h2_ml - h2_expected
        add(f"{label}: водень відповідає корозійному заряду", h2_cath >= -1e-6 * max(st.h2_ml, 1),
            f"H₂ {st.h2_ml:.1f} мл, з корозії анода {h2_expected:.1f} мл")
        if label == "Без навантаження":
            add("Без навантаження: Mg витрачається лише на корозію",
                st.mg_useful_g == 0.0 and st.mg_corr_g > 0, f"корозія {st.mg_corr_g * sim.n:.3f} г за 1 год")
        if label == "SmartBoost" and sim.cap is not None:
            cl = sim.cap.ledger
            add("SmartBoost: конденсатор не створює енергії", cl.bus_out_j <= cl.bus_in_j + cl.initial_j + 1e-9,
                f"віддано {cl.bus_out_j:.1f} Дж ≤ отримано {cl.bus_in_j:.1f} Дж")
            first = sim.rec.get("t_h") * 3600.0 < sc.design.supercap.start_delay_s - 1e-9
            p_usb = sim.rec.get("p_usb")[first]
            add("SmartBoost: USB-C вимкнено до часу запуску", bool(np.all(p_usb == 0.0)),
                f"потужність USB у перші {sc.design.supercap.start_delay_s:.0f} с: {float(np.max(p_usb, initial=0)):.3f} Вт")
    return out
