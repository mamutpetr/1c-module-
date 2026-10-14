"""Підбір конструкції: скільки пластин, якої площі й маси потрібно, щоб зарядити телефон за заданий час.

Алгоритм:
1. Для кожної комбінації (послідовно S, паралельно P, площа пластини) задаємо «невичерпну»
   товщину і моделюємо заряджання телефона повною часовою симуляцією.
2. Якщо телефон заряджено вчасно, беремо фактично витрачену масу Mg (корисний струм +
   самокорозія + механічні втрати) до моменту завершення, ділимо на допустиме використання
   пластини, додаємо резерв і округлюємо товщину вгору до доступного листа.
3. Кандидатів сортуємо за загальною масою магнію.
4. Для найкращого кандидата перераховуємо результат при зміні ключових припущень
   (аналіз чутливості), щоб показати діапазон невизначеності.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .analysis import analyze
from .design import Scenario, clone, derive_geometry
from .params import build_params, set_override
from .provenance import Status
from .simulator import Simulation, SimulationError


@dataclass
class SizingConstraints:
    max_series: int = 5
    max_parallel: int = 3
    max_cells: int = 8
    plate_areas_cm2: tuple = (20.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0, 130.0, 170.0)
    thicknesses_mm: tuple = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)
    reserve_pct: float = 15.0
    max_total_mass_g: float = 0.0       # 0 — без обмеження
    dt_s: float = 30.0
    scale_electrolyte: bool = True


@dataclass
class Candidate:
    n_series: int
    n_parallel: int
    plate_length_mm: float
    plate_width_mm: float
    plate_area_cm2: float
    anode_area_cell_cm2: float
    thickness_mm: float
    mass_total_g: float
    mg_consumed_g: float
    t_done_h: float
    e_usb_wh: float
    p_usb_max_w: float
    peak_t_el: float
    peak_h2_pct: float
    anode_eff_pct: float
    wh_per_g: float
    electrolyte_ml_cell: float
    feasible: bool
    note: str = ""

    @property
    def n_cells(self) -> int:
        return self.n_series * self.n_parallel


@dataclass
class SizingResult:
    candidates: list = field(default_factory=list)       # придатні, відсортовані
    rejected: list = field(default_factory=list)         # (опис, причина)
    sensitivity: list = field(default_factory=list)      # (назва, t_done_h | None, mg_consumed_g)
    sensitivity_mass_range: tuple | None = None
    needed_in_wh: float = 0.0
    target_h: float = 0.0
    cancelled: bool = False


SENSITIVITY_CASES = [
    ("Базові припущення", {}),
    ("NDE-корозія ×0,7", {"anode.k_nde": 0.7}),
    ("NDE-корозія ×1,3", {"anode.k_nde": 1.3}),
    ("Корозія без навантаження ×0,5", {"anode.i_corr0": 0.5}),
    ("Корозія без навантаження ×2", {"anode.i_corr0": 2.0}),
    ("Активність катода (i₀) ×0,5", {"cathode.i0": 0.5}),
    ("Активність катода (i₀) ×2", {"cathode.i0": 2.0}),
    ("Граничний струм катода ×0,7", {"cathode.i_lim": 0.7}),
    ("Пасивація ×1,5", {"anode.pass_asr_max": 1.5}),
]


def _apply_geometry(sc: Scenario, s: int, p: int, area: float, ratio: float, base_area: float,
                    base_volume: float, cons: SizingConstraints) -> None:
    d = sc.design
    d.stack.connection = "mixed"
    d.stack.n_series, d.stack.n_parallel = s, p
    d.stack.n_cells = s * p
    length = math.sqrt(area * ratio) * 10.0
    width = area / (length / 10.0) * 10.0
    d.geometry.plate_length_mm = round(length, 1)
    d.geometry.plate_width_mm = round(width, 1)
    d.geometry.area_override_cm2 = 0.0
    d.geometry.mass_mode = "thickness"
    if cons.scale_electrolyte and base_area > 0:
        d.geometry.electrolyte_volume_ml = max(5.0, base_volume * area / base_area)


def _simulate(sc: Scenario, cancel=None):
    sim = Simulation(sc, unlimited_mg=True)
    sim.run(cancel=cancel)
    return sim


def size_for_phone(base: Scenario, cons: SizingConstraints | None = None, progress=None, cancel=None) -> SizingResult:
    cons = cons or SizingConstraints()
    res = SizingResult(target_h=base.phone.max_time_h)
    base = clone(base)
    base.sim.load_mode = "phone"
    base.sim.dt_s = cons.dt_s
    base.sim.stop_when_phone_done = True
    g0 = base.design.geometry
    ratio = g0.plate_length_mm / g0.plate_width_mm if g0.plate_width_mm > 0 else 1.0
    base_area = g0.plate_length_mm * g0.plate_width_mm / 100.0
    base_volume = g0.electrolyte_volume_ml
    from .phone import PhoneBattery
    res.needed_in_wh = PhoneBattery(base.phone).energy_needed_wh()
    p_need_avg = res.needed_in_wh / base.phone.max_time_h

    combos = [(s, p) for s in range(1, cons.max_series + 1) for p in range(1, cons.max_parallel + 1)
              if s * p <= cons.max_cells]
    total = len(combos) * len(cons.plate_areas_cm2)
    done = 0
    for s, p in combos:
        prev_mass = None
        worse = 0
        for area in sorted(cons.plate_areas_cm2):
            done += 1
            if progress:
                progress(int(100 * done / max(total, 1)))
            if cancel and cancel():
                res.cancelled = True
                return _finalize(res, base, cons, progress, cancel)
            sc = clone(base)
            _apply_geometry(sc, s, p, area, ratio, base_area, base_volume, cons)
            sc.design.geometry.plate_thickness_mm = 1.0      # маса не обмежує (unlimited_mg), товщину визначимо після
            desc = f"{s}×{p}, пластина {area:.0f} см²"
            try:
                an = analyze(sc.design)
            except Exception as exc:  # noqa: BLE001
                res.rejected.append((desc, f"помилка аналізу: {exc}"))
                continue
            if an.p_max_usb_w <= 0:
                res.rejected.append((desc, "напруга замала для перетворювача"))
                continue
            if an.p_max_usb_w * 0.95 < p_need_avg:
                res.rejected.append((desc, f"мало потужності: {an.p_max_usb_w:.2f} Вт < {p_need_avg:.2f} Вт"))
                continue
            try:
                sim = _simulate(sc, cancel)
            except SimulationError as exc:
                res.rejected.append((desc, str(exc)))
                continue
            sm = sim.summary()
            if not sm.get("phone_done") or sm["phone_t_done_s"] > base.phone.max_time_h * 3600 + 1e-6:
                res.rejected.append((desc, f"не встигає: {sm['phone_soc_pct']:.0f}% за {base.phone.max_time_h:g} год"))
                continue
            cand = _make_candidate(sc, sim, sm, an, cons, s, p, area)
            if cand is None:
                res.rejected.append((desc, "потрібна товщина більша за доступні листи"))
                continue
            if cons.max_total_mass_g > 0 and cand.mass_total_g > cons.max_total_mass_g:
                res.rejected.append((desc, f"маса {cand.mass_total_g:.1f} г перевищує обмеження"))
                continue
            res.candidates.append(cand)
            if prev_mass is not None and cand.mass_total_g >= prev_mass:
                worse += 1
                if worse >= 2:
                    break
            else:
                worse = 0
            prev_mass = cand.mass_total_g
    return _finalize(res, base, cons, progress, cancel)


def _make_candidate(sc, sim, sm, an, cons, s, p, area) -> Candidate | None:
    d = sc.design
    n = s * p
    ps = build_params(d)
    rho = ps.v("anode.density")
    consumed_cell = sm["mg_consumed_g"] / n
    need_cell = consumed_cell * (1.0 + cons.reserve_pct / 100.0) / d.geometry.max_utilization
    t_req = need_cell / (rho * area) * 10.0
    thick = next((t for t in sorted(cons.thicknesses_mm) if t >= t_req - 1e-9), None)
    if thick is None:
        return None
    d.geometry.plate_thickness_mm = thick
    geo = derive_geometry(d, rho)
    return Candidate(
        n_series=s, n_parallel=p,
        plate_length_mm=d.geometry.plate_length_mm, plate_width_mm=d.geometry.plate_width_mm,
        plate_area_cm2=area, anode_area_cell_cm2=geo.anode_area_cm2, thickness_mm=thick,
        mass_total_g=geo.total_mass_g, mg_consumed_g=sm["mg_consumed_g"],
        t_done_h=sm["phone_t_done_s"] / 3600.0, e_usb_wh=sm["e_usb_wh"], p_usb_max_w=an.p_max_usb_w,
        peak_t_el=sm["peak_t_el"], peak_h2_pct=sm["peak_h2_pct"], anode_eff_pct=sm["anode_eff_pct"],
        wh_per_g=sm["wh_per_g_out"], electrolyte_ml_cell=d.geometry.electrolyte_volume_ml, feasible=True,
    )


def candidate_scenario(base: Scenario, c: Candidate) -> Scenario:
    sc = clone(base)
    d = sc.design
    d.stack.connection = "mixed" if c.n_parallel > 1 else "series"
    d.stack.n_series, d.stack.n_parallel = c.n_series, c.n_parallel
    d.stack.n_cells = c.n_cells if c.n_parallel > 1 else c.n_series
    d.geometry.plate_length_mm = c.plate_length_mm
    d.geometry.plate_width_mm = c.plate_width_mm
    d.geometry.plate_thickness_mm = c.thickness_mm
    d.geometry.mass_mode = "thickness"
    d.geometry.area_override_cm2 = 0.0
    d.geometry.electrolyte_volume_ml = round(c.electrolyte_ml_cell, 1)
    return sc


def _finalize(res: SizingResult, base: Scenario, cons: SizingConstraints, progress, cancel) -> SizingResult:
    # маса з кроком 0,5 г, далі менше комірок (простіше виготовлення), далі менша площа
    res.candidates.sort(key=lambda c: (round(c.mass_total_g / 0.5), c.n_cells, c.plate_area_cm2))
    if not res.candidates or res.cancelled:
        return res
    best = res.candidates[0]
    masses = []
    for name, factors in SENSITIVITY_CASES:
        if cancel and cancel():
            res.cancelled = True
            break
        sc = candidate_scenario(base, best)
        sc.sim.load_mode = "phone"
        sc.sim.dt_s = cons.dt_s
        sc.sim.stop_when_phone_done = True
        ps = build_params(sc.design)
        for key, f in factors.items():
            set_override(sc.design, key, ps.v(key) * f, Status.USER, f"чутливість {name}")
        try:
            sim = _simulate(sc, cancel)
            sm = sim.summary()
            t_done = sm["phone_t_done_s"] / 3600.0 if sm.get("phone_done") else None
            res.sensitivity.append((name, t_done, sm["mg_consumed_g"], sm["phone_soc_pct"]))
            if t_done is not None:
                masses.append(sm["mg_consumed_g"] * (1 + cons.reserve_pct / 100) / sc.design.geometry.max_utilization)
        except SimulationError:
            res.sensitivity.append((name, None, float("nan"), float("nan")))
    if masses:
        res.sensitivity_mass_range = (min(masses), max(masses))
    return res
