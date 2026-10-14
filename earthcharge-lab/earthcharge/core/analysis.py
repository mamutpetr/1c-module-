"""Статичний аналіз конструкції без часової симуляції: ВАХ, потужність, похідні величини."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import constants as C
from . import materials as M
from .design import Design, derive_geometry
from .electrochem import CellModel, StackModel
from .params import build_params
from .units import mg_grams_per_ah


@dataclass
class DesignAnalysis:
    design: Design
    geo: object
    cell: CellModel
    stack: StackModel
    ocv_cell: float
    ocv_stack: float
    r_el_mohm: float
    r_cell_total_mohm: float
    i_lim_ma_cm2: float
    i_lim_supply_ma_cm2: float
    i_short_a: float
    p_max_term_w: float
    i_at_pmax_a: float
    v_at_pmax: float
    p_max_usb_w: float
    usb_limited_by: str
    capacity_theor_ah: float        # усього Mg (повне розчинення лише корисним струмом)
    energy_theor_wh: float          # при E_rev = 3,09 В
    capacity_usable_ah: float       # з урахуванням допустимого використання й ефективності анода
    anode_eff_at_10: float          # ефективність анода при 10 мА/см²
    curve_cell: dict
    curve_stack: dict

    def as_rows(self) -> list[tuple[str, str]]:
        g = self.geo
        f = lambda x, d=2: f"{x:.{d}f}".replace(".", ",")
        rows = [
            ("Комірок (послідовно × паралельно)", f"{g.n_series} × {g.n_parallel} = {g.n_cells}"),
            ("Активна площа анода на комірку", f"{f(g.anode_area_cm2, 1)} см²"),
            ("Активна площа катода на комірку", f"{f(g.cathode_area_cm2, 1)} см²"),
            ("Товщина пластини", f"{f(g.thickness_mm, 2)} мм"),
            ("Маса Mg: на комірку / усього", f"{f(g.mass_per_cell_g, 1)} г / {f(g.total_mass_g, 1)} г"),
            ("Об'єм електроліту, усього", f"{f(g.electrolyte_total_ml, 0)} мл"),
            ("НРК комірки / батареї комірок", f"{f(self.ocv_cell)} В / {f(self.ocv_stack)} В"),
            ("Опір електроліту в зазорі (комірка)", f"{f(self.r_el_mohm, 1)} мОм"),
            ("Повний омічний опір комірки", f"{f(self.r_cell_total_mohm, 1)} мОм"),
            ("Граничний струм катода", f"{f(self.i_lim_ma_cm2, 2)} мА/см²"),
            ("Струм короткого замикання", f"{f(self.i_short_a, 2)} А"),
            ("Максимальна потужність на виводах", f"{f(self.p_max_term_w)} Вт при {f(self.v_at_pmax)} В"),
            ("Максимальна потужність USB-C", f"{f(self.p_max_usb_w)} Вт ({LIMIT_LABELS.get(self.usb_limited_by, self.usb_limited_by)})"),
            ("Теоретична ємність Mg (закон Фарадея)", f"{f(self.capacity_theor_ah, 1)} А·год"),
            ("Теоретична енергія при 3,09 В", f"{f(self.energy_theor_wh, 0)} Вт·год"),
            ("Ефективність анода при 10 мА/см²", f"{f(self.anode_eff_at_10 * 100, 1)} %"),
            ("Корисна ємність (оцінка)", f"{f(self.capacity_usable_ah, 1)} А·год"),
        ]
        return rows


LIMIT_LABELS = {
    "mpp": "точка максимальної потужності",
    "v_in_min": "обмежено мінімальною вхідною напругою",
    "i_in_max": "обмежено вхідним струмом перетворювача",
    "rating": "обмежено номіналом перетворювача",
    "ocv_low": "напруга замала для перетворювача",
    "off": "перетворювач вимкнено",
}


def analyze(design: Design, t_c: float | None = None) -> DesignAnalysis:
    ps = build_params(design)
    an = M.ANODES[design.anode]
    geo = derive_geometry(design, ps.v("anode.density"))
    cell = CellModel(design, ps, geo)
    if t_c is not None:
        cell.set_conditions(t_c)
    stack = StackModel(cell, design, geo, ps)
    i_short = cell.current_upper()
    i = np.linspace(0.0, i_short, 160)
    v_cell = cell.v_cell(i)
    v_term, i_ext, *_ = stack.terminal(i)
    p_term = v_term * i_ext
    k = int(np.argmax(p_term))
    if design.converter.enabled:
        cap = stack.capability()
        p_usb, lim = cap.p_max, cap.limited_by
        p_conv = np.where((v_term >= design.converter.v_in_min) & (i_ext <= design.converter.i_in_max_a),
                          np.minimum(stack.conv_output(v_term, i_ext), design.converter.p_out_max_w), np.nan)
    else:
        p_usb, lim = 0.0, "off"
        p_conv = np.full_like(i, np.nan)
    e_per_g = an.electrons_per_gram()
    q_theor_ah = geo.total_mass_g * e_per_g * C.FARADAY / 3600.0
    i10 = 0.010 * cell.A_a
    eff10 = cell.anode_efficiency(i10)
    return DesignAnalysis(
        design=design, geo=geo, cell=cell, stack=stack,
        ocv_cell=cell.ocv, ocv_stack=float(v_term[0]),
        r_el_mohm=cell.r_el * 1000.0,
        r_cell_total_mohm=cell.r_series * 1000.0,
        i_lim_ma_cm2=cell.i_lim * 1000.0,
        i_lim_supply_ma_cm2=cell.i_lim_supply * 1000.0 if math.isfinite(cell.i_lim_supply) else math.inf,
        i_short_a=float(i_ext[-1]),
        p_max_term_w=float(p_term[k]), i_at_pmax_a=float(i_ext[k]), v_at_pmax=float(v_term[k]),
        p_max_usb_w=p_usb, usb_limited_by=lim,
        capacity_theor_ah=q_theor_ah,
        energy_theor_wh=q_theor_ah * C.E_REV_MG_AIR,
        capacity_usable_ah=q_theor_ah * design.geometry.max_utilization * eff10,
        anode_eff_at_10=eff10,
        curve_cell={"i_ma_cm2": i / cell.A_a * 1000.0, "v": v_cell, "p_mw_cm2": v_cell * i / cell.A_a * 1000.0,
                    "eff": np.array([cell.anode_efficiency(x) for x in i]) * 100.0},
        curve_stack={"i_a": i_ext, "v": v_term, "p_w": p_term, "p_usb_w": p_conv},
    )


def faraday_reference() -> dict:
    """Довідкові числа закону Фарадея для перевірки (чистий Mg)."""
    return {
        "mah_per_g": C.FARADAY * 2 / C.MOLAR_MASS["Mg"] / 3.6,
        "g_per_ah": mg_grams_per_ah(),
        "e_rev_v": C.E_REV_MG_AIR,
        "e_tn_v": C.E_TN_MG_AIR,
        "wh_per_g_theor": C.FARADAY * 2 / C.MOLAR_MASS["Mg"] / 3600.0 * C.E_REV_MG_AIR,
        "h2_ml_per_g": 1.0 / C.MOLAR_MASS["Mg"] * C.molar_gas_volume_l(25.0) * 1000.0,
    }
