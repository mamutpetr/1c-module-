"""Електрохімічна модель магній-повітряної комірки та батареї комірок.

Напруга комірки при струмі I:

    V = (E_c,спок − E_a,НРК) − η_катод(i_c) − η_анод(i_a) − I·(R_ел + R_пас + R_кат + R_конт)

* η_катод — відновлення O₂ (Батлер–Фольмер + Кутецький–Левич з граничним струмом) і
  паралельне виділення H₂, коли кисню не вистачає;
* η_анод — розчинення Mg (симетричний Батлер–Фольмер);
* R_ел = d·N_M / (σ·A) — опір електроліту у зазорі (N_M — число Мак-Маллена сепаратора);
* R_пас — опір плівки Mg(OH)₂, що наростає з розчиненим зарядом.

Самокорозія (виділення H₂ на аноді) моделюється окремо:
    I_H = A·i_corr0·f(T)·k_ел + k_NDE·k_ел·I    (негативний різницевий ефект),
механічні втрати: I_chunk = k_chunk·I.
За законом Фарадея маса розчиненого сплаву: dm/dt = (I + I_H + I_chunk) / (F·z̄),
де z̄ — моль електронів на грам сплаву.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from . import constants as C
from . import materials as M
from .design import ConverterConfig, Design, DerivedGeometry
from .params import ParamSet

LN10 = math.log(10.0)


class CellModel:
    """Одна комірка: анод Mg | електроліт (+сепаратор) | катод."""

    def __init__(self, design: Design, ps: ParamSet, geo: DerivedGeometry):
        self.ps = ps
        self.anode = M.ANODES[design.anode]
        self.cathode = M.CATHODES[design.cathode]
        self.category = self.cathode.category
        self.e_per_g = self.anode.electrons_per_gram()
        self.A_a0 = geo.anode_area_cm2
        self.A_c0 = geo.cathode_area_cm2
        self.n_cells = geo.n_cells
        self.gap_cm = design.geometry.gap_mm / 10.0
        self.r_contact = design.geometry.contact_resistance_mohm / 1000.0
        env = design.environment
        self.vents = env.air_access == "vents" and self.category == "air"
        self.vent_area_m2 = max(env.vent_area_cm2, 1e-6) * 1e-4
        self.vent_len_m = max(env.vent_length_mm, 0.01) * 1e-3
        self._table_key = None
        self.set_conditions(env.ambient_c)

    # ------------------------------------------------------------------ умови
    def set_conditions(self, t_c: float, q_pass_c_cm2: float = 0.0, sludge_fraction: float = 0.0,
                       area_factor: float = 1.0, age_h: float = 0.0) -> None:
        ps = self.ps
        self.t_c = t_c
        tk = C.kelvin(t_c)
        self.area_factor = area_factor
        self.A_a = self.A_a0 * area_factor
        self.A_c = self.A_c0 * area_factor

        # Електроліт
        sigma_ref = ps.v("electrolyte.sigma")
        sigma = sigma_ref * (1.0 + ps.v("electrolyte.alpha_sigma") * (t_c - ps.v("electrolyte.t_ref")))
        sigma = max(sigma, 0.05 * sigma_ref)
        # Шлам Mg(OH)₂ як непровідна фаза: співвідношення Бруггемана σ_еф = σ·(1 − φ)^1,5
        phi = min(0.9, max(0.0, sludge_fraction))
        self.sludge_phi = phi
        self.sludge_factor = (1.0 - phi) ** 1.5
        self.sigma_eff = sigma * self.sludge_factor                      # См/м
        a_el = min(self.A_a, self.A_c)
        self.r_el = self.gap_cm * ps.v("separator.macmullin") / (self.sigma_eff / 100.0 * a_el)

        # Анод
        self.e_ocp_a = ps.v("anode.ocp")
        self.b_a = ps.v("anode.tafel_b") / 1000.0 / LN10 * tk / C.T_REF_K
        f_t_anode = C.arrhenius_factor(ps.v("anode.ea") * 1e3, t_c)
        self.i0_a = ps.v("anode.i0") * 1e-3 * f_t_anode
        self.corr_factor = ps.v("electrolyte.corr_factor")
        self.i_corr0 = ps.v("anode.i_corr0") * 1e-3 * f_t_anode * self.corr_factor   # А/см²
        self.k_nde = ps.v("anode.k_nde") * self.corr_factor
        self.k_chunk = ps.v("anode.chunk")
        asr_max = ps.v("anode.pass_asr_max") * ps.v("electrolyte.pass_factor")
        self.asr_pass = asr_max * (1.0 - math.exp(-max(q_pass_c_cm2, 0.0) / ps.v("anode.pass_q_char")))
        self.r_pass = self.asr_pass / self.A_a

        # Катод
        self.e_rest = ps.v("cathode.e_rest")
        self.r_cath = ps.v("cathode.asr") / self.A_c
        self.r_series = self.r_el + self.r_pass + self.r_cath + self.r_contact
        self.ocv = self.e_rest - self.e_ocp_a

        deg = max(0.0, 1.0 - ps.v("cathode.degradation") / 100.0 * age_h)
        self.i_lim = self._limiting_current(t_c)
        key = (t_c, deg, self.i_lim)
        if self._table_key is None or not self._table_close(key):
            self._build_cathode_table(t_c, deg)
            self._table_key = key
        self._i_upper = None

    def _table_close(self, key) -> bool:
        t0, d0, l0 = self._table_key
        t1, d1, l1 = key
        return abs(t1 - t0) < 0.2 and abs(d1 - d0) < 0.005 and abs(l1 - l0) <= 0.005 * l0

    def _limiting_current(self, t_c: float) -> float:
        """Граничний струм відновлення O₂, А/см² катода."""
        ps = self.ps
        if self.category == "submerged":
            c_o2 = C.o2_solubility_water_mol_m3(t_c, ps.v("electrolyte.o2_factor"))
            delta = ps.v("cathode.diff_layer") * 1e-6
            i_lim = 4.0 * C.FARADAY * C.d_o2_water(t_c) * c_o2 / delta / 1e4
            self.i_lim_supply = math.inf
            return i_lim
        i_cat = ps.v("cathode.i_lim") * 1e-3
        if self.vents:
            n_dot = C.d_o2_air(t_c) * C.o2_concentration_air_mol_m3(t_c) * self.vent_area_m2 / self.vent_len_m
            i_sup = 4.0 * C.FARADAY * n_dot / (self.A_c * self.n_cells)
            self.i_lim_supply = i_sup
            return 1.0 / (1.0 / i_cat + 1.0 / i_sup)
        self.i_lim_supply = math.inf
        return i_cat

    def _build_cathode_table(self, t_c: float, deg: float) -> None:
        ps = self.ps
        tk = C.kelvin(t_c)
        b_c = ps.v("cathode.tafel_b") / 1000.0 / LN10 * tk / C.T_REF_K
        i0 = ps.v("cathode.i0") * 1e-3 * C.arrhenius_factor(ps.v("cathode.ea") * 1e3, t_c) * deg
        b_h = ps.v("cathode.tafel_her") / 1000.0 / LN10 * tk / C.T_REF_K
        i0_h = ps.v("cathode.i0_her") * 1e-3
        e_her = C.e_her_vs_sce(ps.v("cathode.ph_local"), t_c)
        eta = np.linspace(0.0, 4.0, 4001)
        e = self.e_rest - eta
        i_k = 2.0 * i0 * np.sinh(eta / b_c)
        i_orr = i_k * self.i_lim / (i_k + self.i_lim)
        i_her = i0_h * (np.exp(np.clip((e_her - e) / b_h, -700, 700)) - math.exp((e_her - self.e_rest) / b_h))
        i_tot = i_orr + i_her
        i_tot[0] = 0.0
        # монотонність гарантована фізично; захист від округлення
        i_tot = np.maximum.accumulate(i_tot + np.arange(i_tot.size) * 1e-18)
        self._tab_i = i_tot
        self._tab_e = e
        self._tab_her_frac = np.divide(i_her, i_tot, out=np.zeros_like(i_tot), where=i_tot > 0)
        self._li = i_tot.tolist()
        self._le = e.tolist()

    def _e_cathode_scalar(self, i_c: float) -> float:
        """Швидка скалярна лінійна інтерполяція E_c(i) (еквівалент np.interp)."""
        xs, ys = self._li, self._le
        if i_c <= xs[0]:
            return ys[0]
        k = bisect_right(xs, i_c)
        if k >= len(xs):
            return ys[-1]
        x0, x1 = xs[k - 1], xs[k]
        return ys[k - 1] + (ys[k] - ys[k - 1]) * (i_c - x0) / (x1 - x0)

    # ---------------------------------------------------------- характеристики
    def cathode_potential(self, i_c):
        return np.interp(i_c, self._tab_i, self._tab_e)

    def v_cell(self, current):
        """Напруга комірки, В, для струму комірки current, А (скаляр або масив)."""
        if isinstance(current, np.ndarray):
            i_a = current / self.A_a
            eta_a = self.b_a * np.arcsinh(i_a / (2.0 * self.i0_a))
            e_c = np.interp(current / self.A_c, self._tab_i, self._tab_e)
            return e_c - self.e_ocp_a - eta_a - current * self.r_series
        eta_a = self.b_a * math.asinh(current / self.A_a / (2.0 * self.i0_a))
        e_c = self._e_cathode_scalar(current / self.A_c)
        return e_c - self.e_ocp_a - eta_a - current * self.r_series

    def components(self, current: float) -> dict:
        """Складові напруги та струмів для енергетичного балансу (одна комірка)."""
        i_a = current / self.A_a
        i_c = current / self.A_c
        eta_a = self.b_a * math.asinh(i_a / (2.0 * self.i0_a))
        e_c = self._e_cathode_scalar(i_c)
        eta_c = self.e_rest - e_c
        her_frac = float(np.interp(i_c, self._tab_i, self._tab_her_frac))
        v = self.ocv - eta_c - eta_a - current * self.r_series
        return {
            "v": v, "eta_a": eta_a, "eta_c": eta_c,
            "ohm_el": current * self.r_el, "ohm_pass": current * self.r_pass,
            "ohm_cath": current * self.r_cath, "ohm_contact": current * self.r_contact,
            "i_her_c": current * her_frac,
        }

    def corrosion_current(self, current: float) -> float:
        """Еквівалентний струм самокорозії анода (виділення H₂), А на комірку."""
        return self.A_a0 * self.i_corr0 + self.k_nde * current

    def chunk_current(self, current: float) -> float:
        return self.k_chunk * current

    def anode_efficiency(self, current: float) -> float:
        total = current + self.corrosion_current(current) + self.chunk_current(current)
        return current / total if total > 0 else 0.0

    def current_upper(self) -> float:
        """Струм комірки, при якому напруга падає до нуля (коротке замикання), А."""
        if self._i_upper is None:
            self._i_upper = self._find_upper()
        return self._i_upper

    def _find_upper(self) -> float:
        hint = getattr(self, "_upper_hint", None)
        if hint:
            a, b = hint * 0.97, hint * 1.03
            if self.v_cell(a) > 0.0 >= self.v_cell(b):
                self._upper_hint = brentq(self.v_cell, a, b, xtol=1e-12, rtol=1e-10)
                return self._upper_hint
        self._upper_hint = self._find_upper_full()
        return self._upper_hint

    def _find_upper_full(self) -> float:
        grid = self.A_c * np.logspace(-7, 1, 81)
        v = self.v_cell(grid)
        idx = np.nonzero(v <= 0.0)[0]
        if idx.size == 0:
            return float(grid[-1])
        k = int(idx[0])
        if k == 0:
            return float(grid[0])
        return float(brentq(self.v_cell, grid[k - 1], grid[k], xtol=1e-12, rtol=1e-10))


@dataclass
class OpPoint:
    i_cell: float = 0.0      # струм однієї комірки (рядка), А
    i_ext: float = 0.0       # струм на виводах батареї комірок, А
    v_term: float = 0.0      # напруга на виводах, В
    v_cell: float = 0.0
    v_int: float = 0.0       # внутрішня напруга батареї комірок до опору з'єднань
    i_shunt: float = 0.0
    p_term: float = 0.0
    p_conv_in: float = 0.0
    p_conv_out: float = 0.0
    conv_on: bool = False


@dataclass
class Capability:
    p_max: float             # максимальна потужність на виході перетворювача, Вт
    i_at_max: float          # струм комірки в цій точці
    i_open: float
    limited_by: str          # "mpp" | "v_in_min" | "i_in_max" | "rating" | "ocv_low"


class StackModel:
    """S×P комірок + опір з'єднань + (за потреби) шунтувальний струм + DC/DC перетворювач."""

    def __init__(self, cell: CellModel, design: Design, geo: DerivedGeometry, ps: ParamSet):
        self.cell = cell
        self.S = geo.n_series
        self.P = geo.n_parallel
        self.r_wire = design.stack.wiring_resistance_mohm / 1000.0
        st = design.stack
        self.has_shunt = st.shared_electrolyte and self.S > 1
        self._shunt_geom = (st.shunt_path_mm / 10.0, max(st.shunt_cross_section_cm2, 1e-6))
        self.conv: ConverterConfig = design.converter
        self.eta = design.converter.efficiency_pct / 100.0
        self.p_q = design.converter.quiescent_mw / 1000.0
        self.r_in = design.converter.input_resistance_mohm / 1000.0

    @property
    def r_shunt(self) -> float:
        if not self.has_shunt:
            return math.inf
        length_cm, area_cm2 = self._shunt_geom
        return length_cm / (self.cell.sigma_eff / 100.0 * area_cm2)

    # ----------------------------------------------------------- виводи
    def terminal(self, i_cell):
        if not isinstance(i_cell, np.ndarray):
            v_cell = self.cell.v_cell(i_cell)
            v_int = self.S * v_cell
            i_sh = max(v_int, 0.0) / self.r_shunt if self.has_shunt else 0.0
            i_ext = self.P * i_cell - i_sh
            return v_int - i_ext * self.r_wire, i_ext, v_cell, v_int, i_sh
        v_cell = self.cell.v_cell(i_cell)
        v_int = self.S * v_cell
        if self.has_shunt:
            i_sh = np.maximum(v_int, 0.0) / self.r_shunt
        else:
            i_sh = 0.0 * v_int
        i_ext = self.P * i_cell - i_sh
        v_term = v_int - i_ext * self.r_wire
        return v_term, i_ext, v_cell, v_int, i_sh

    def conv_output(self, v_term, i_ext):
        return self.eta * (v_term * i_ext - i_ext * i_ext * self.r_in) - self.p_q

    def _p_out(self, i_cell: float) -> float:
        v_term, i_ext, *_ = self.terminal(i_cell)
        return self.eta * (v_term * i_ext - i_ext * i_ext * self.r_in) - self.p_q

    def i_open(self) -> float:
        if not self.has_shunt:
            return 0.0
        hi = self.cell.current_upper()
        f = lambda x: float(self.terminal(x)[1])
        if f(0.0) >= 0:
            return 0.0
        return brentq(f, 0.0, hi, xtol=1e-12)

    def point(self, i_cell: float, conv_on: bool = False) -> OpPoint:
        v_term, i_ext, v_cell, v_int, i_sh = (float(x) for x in self.terminal(i_cell))
        p_term = v_term * i_ext
        if conv_on:
            p_in = p_term
            p_out = float(self.conv_output(v_term, i_ext))
        else:
            p_in = p_out = 0.0
        return OpPoint(i_cell, i_ext, v_term, v_cell, v_int, i_sh, p_term, p_in, p_out, conv_on)

    def open_point(self) -> OpPoint:
        return self.point(self.i_open(), conv_on=False)

    def solve_resistor(self, r_ohm: float) -> OpPoint:
        lo, hi = self.i_open(), self.cell.current_upper()
        f = lambda x: float(self.terminal(x)[0] - self.terminal(x)[1] * r_ohm)
        if f(lo) <= 0:
            return self.point(lo)
        return self.point(brentq(f, lo, hi, xtol=1e-12, rtol=1e-10))

    def solve_current(self, i_set: float) -> tuple[OpPoint, bool]:
        """Повертає (робоча точка, чи досягнуто заданого струму)."""
        lo, hi = self.i_open(), self.cell.current_upper()
        f = lambda x: float(self.terminal(x)[1] - i_set)
        if i_set <= 0:
            return self.point(lo), True
        if f(hi) < 0:
            return self.point(hi), False
        return self.point(brentq(f, lo, hi, xtol=1e-12, rtol=1e-10)), True

    def capability(self) -> Capability:
        """Максимальна потужність, яку може видати перетворювач за поточних умов."""
        lo, hi = self.i_open(), self.cell.current_upper()
        v_lo = float(self.terminal(lo)[0])
        if v_lo < self.conv.v_in_min:
            return Capability(0.0, lo, lo, "ocv_low")
        fv = lambda x: float(self.terminal(x)[0]) - self.conv.v_in_min
        i_v = brentq(fv, lo, hi, xtol=1e-12, rtol=1e-10)
        bound, limited = i_v, "v_in_min"
        fi = lambda x: float(self.terminal(x)[1]) - self.conv.i_in_max_a
        if fi(i_v) > 0:
            bound, limited = brentq(fi, lo, i_v, xtol=1e-12, rtol=1e-10), "i_in_max"
        grid = np.linspace(lo, bound, 41)
        v_term, i_ext, *_ = self.terminal(grid)
        p = self.conv_output(v_term, i_ext)
        k = int(np.argmax(p))
        if 0 < k < grid.size - 1:
            # параболічне уточнення максимуму за трьома вузлами сітки
            y0, y1, y2 = p[k - 1], p[k], p[k + 1]
            h = grid[1] - grid[0]
            denom = y0 - 2.0 * y1 + y2
            shift = 0.5 * (y0 - y2) / denom if denom < 0 else 0.0
            i_best = float(grid[k] + max(-1.0, min(1.0, shift)) * h)
            p_best = self._p_out(i_best)
            if p_best < y1:
                i_best, p_best = float(grid[k]), float(y1)
            limited = "mpp"
        else:
            i_best, p_best = float(grid[k]), float(p[k])
        if p_best <= 0:
            return Capability(0.0, lo, lo, "ocv_low")
        if p_best > self.conv.p_out_max_w:
            i_best = brentq(lambda x: self._p_out(x) - self.conv.p_out_max_w, lo, i_best, xtol=1e-12)
            p_best, limited = self.conv.p_out_max_w, "rating"
        return Capability(p_best, i_best, lo, limited)

    def solve_output(self, p_target: float, cap: Capability) -> OpPoint:
        """Робоча точка, за якої вихід перетворювача дорівнює p_target (Вт), p_target ≤ cap.p_max."""
        if p_target >= cap.p_max:
            return self.point(cap.i_at_max, conv_on=True)
        f = lambda x: self._p_out(x) - p_target
        lo = cap.i_open
        if f(lo) >= 0:
            return self.point(lo, conv_on=True)
        return self.point(brentq(f, lo, cap.i_at_max, xtol=1e-12, rtol=1e-11), conv_on=True)


def polarization_curve(cell: CellModel, n: int = 120) -> dict:
    """Вольт-амперна характеристика однієї комірки від НРК до короткого замикання."""
    i_max = cell.current_upper()
    i = np.linspace(0.0, i_max, n)
    v = cell.v_cell(i)
    return {"i_a": i, "i_ma_cm2": i / cell.A_a * 1000.0, "v": v, "p_w": v * i,
            "p_mw_cm2": v * i / cell.A_a * 1000.0}
