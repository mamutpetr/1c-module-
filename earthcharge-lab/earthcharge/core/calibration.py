"""Калібрування моделі за експериментальними вимірюваннями.

Доступні процедури:
* «ВАХ» — підбір НРК (через потенціал анода), активності катода i₀ та омічного опору катода
  за точками (струм, напруга). Найкраще підходить ступеневий тест з різними навантаженнями.
* «Ефективність анода» — з втрати маси пластини і пропущеного заряду (закон Фарадея)
  визначається коефіцієнт NDE (або корозія без навантаження для досліду без струму).
* «Пасивація» — підбір граничного опору плівки та характерного заряду за спадом напруги
  в часі при відомому струмі.

Дослід і конструкція мають бути одного типу (повітряний чи занурений катод), інакше
результати не переносяться.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from . import materials as M
from .constants import FARADAY, arrhenius_factor
from .design import Design, Scenario, SimSettings, clone, derive_geometry
from .electrochem import CellModel
from .experiments import Experiment, construction_of_cathode
from .params import build_params, set_override
from .provenance import Status
from .simulator import Simulation


@dataclass
class CalibrationResult:
    kind: str
    ok: bool
    params: dict = field(default_factory=dict)      # ключ -> нове значення (у одиницях бібліотеки)
    before: dict = field(default_factory=dict)
    rmse_before: float = math.nan
    rmse_after: float = math.nan
    r2: float = math.nan
    n_points: int = 0
    messages: list = field(default_factory=list)
    curve: dict = field(default_factory=dict)       # для графіка: t/i, v_meas, v_before, v_after


KIND_LABELS = {
    "polarization": "Вольт-амперна характеристика",
    "efficiency": "Ефективність анода (маса)",
    "passivation": "Пасивація (спад напруги в часі)",
}


def experiment_design(exp: Experiment, base: Design | None = None) -> Design:
    """Одна комірка з параметрами досліду (одностороння пластина, площа з досліду)."""
    d = Design(name=f"Дослід: {exp.name}")
    d.anode = exp.anode if exp.anode in M.ANODES else M.DEFAULT_ANODE
    d.cathode = exp.cathode if exp.cathode in M.CATHODES else M.DEFAULT_CATHODE
    d.electrolyte = exp.electrolyte if exp.electrolyte in M.ELECTROLYTES else M.DEFAULT_ELECTROLYTE
    d.separator = exp.separator if exp.separator in M.SEPARATORS else "none"
    area = exp.area_cm2 if (exp.area_cm2 and math.isfinite(exp.area_cm2) and exp.area_cm2 > 0) else 10.0
    side = math.sqrt(area) * 10.0
    g = d.geometry
    g.plate_length_mm = g.plate_width_mm = side
    g.faces = 1
    g.active_fraction = 1.0
    g.area_override_cm2 = area
    g.cathode_area_ratio = 1.0
    g.gap_mm = exp.gap_mm if math.isfinite(exp.gap_mm) and exp.gap_mm > 0 else 3.0
    g.electrolyte_volume_ml = exp.electrolyte_ml if math.isfinite(exp.electrolyte_ml) and exp.electrolyte_ml > 0 else 100.0
    rho = M.ANODES[d.anode].props["density"].value
    if math.isfinite(exp.mass_start_g) and exp.mass_start_g > 0:
        g.plate_thickness_mm = max(0.05, exp.mass_start_g / (rho * area) * 10.0)
    else:
        g.plate_thickness_mm = 2.0
    g.max_utilization = 0.98
    d.stack.connection = "series"
    d.stack.n_cells = 1
    d.stack.wiring_resistance_mohm = 0.0
    d.environment.ambient_c = exp.temperature_c if math.isfinite(exp.temperature_c) else 25.0
    d.environment.thermal_model = False
    d.environment.air_access = "open"
    if base is not None:
        g.contact_resistance_mohm = base.geometry.contact_resistance_mohm
        for key, ov in base.overrides.items():
            group = key.split(".")[0]
            same = {"anode": base.anode == d.anode, "cathode": base.cathode == d.cathode,
                    "electrolyte": base.electrolyte == d.electrolyte, "separator": base.separator == d.separator,
                    "system": True}.get(group, False)
            if same:
                d.overrides[key] = dict(ov)
    return d


def _with_values(design: Design, values: dict) -> Design:
    d = clone(design)
    for k, v in values.items():
        set_override(d, k, v, Status.USER, "калібрування")
    return d


def predict_points(design: Design, exp: Experiment, values: dict | None = None) -> np.ndarray:
    """Напруга моделі в точках вимірювання з урахуванням накопиченого заряду (пасивація)."""
    d = _with_values(design, values or {})
    ps = build_params(d)
    geo = derive_geometry(d, ps.v("anode.density"))
    cell = CellModel(d, ps, geo)
    a = exp.arrays()
    t, i = a["t_s"], np.nan_to_num(a["i"], nan=0.0)
    temp = np.where(np.isfinite(a["temp"]), a["temp"], d.environment.ambient_c)
    v = np.empty_like(t)
    q = 0.0
    for k in range(t.size):
        if k > 0:
            dt = max(0.0, t[k] - t[k - 1])
            i_avg = 0.5 * (i[k] + i[k - 1])
            q += (i_avg + cell.corrosion_current(i_avg)) * dt / cell.A_a0
        cell.set_conditions(float(temp[k]), q)
        v[k] = cell.v_cell(float(max(i[k], 0.0)))
    return v


def _stats(v_meas: np.ndarray, v_model: np.ndarray) -> tuple[float, float]:
    ok = np.isfinite(v_meas) & np.isfinite(v_model)
    if ok.sum() == 0:
        return math.nan, math.nan
    r = v_model[ok] - v_meas[ok]
    rmse = float(np.sqrt(np.mean(r * r)))
    ss = float(np.sum((v_meas[ok] - v_meas[ok].mean()) ** 2))
    r2 = 1.0 - float(np.sum(r * r)) / ss if ss > 0 else math.nan
    return rmse, r2


def _fit(design: Design, exp: Experiment, keys: list, x0: list, lo: list, hi: list, log_keys: set,
         mask: np.ndarray | None = None):
    a = exp.arrays()
    v_meas = a["v"]
    sel = np.isfinite(v_meas) & np.isfinite(a["i"])
    if mask is not None:
        sel &= mask

    def unpack(x):
        return {k: (10.0 ** xi if k in log_keys else xi) for k, xi in zip(keys, x)}

    def resid(x):
        vm = predict_points(design, exp, unpack(x))
        r = vm[sel] - v_meas[sel]
        return np.where(np.isfinite(r), r, 1.0)

    sol = least_squares(resid, x0, bounds=(lo, hi), x_scale="jac", max_nfev=200)
    return unpack(sol.x), sel


def calibrate_polarization(exp: Experiment, base: Design | None = None, fit_tafel: bool = False) -> CalibrationResult:
    res = CalibrationResult("polarization", False)
    d = experiment_design(exp, base)
    a = exp.arrays()
    ok = np.isfinite(a["v"]) & np.isfinite(a["i"])
    res.n_points = int(ok.sum())
    if res.n_points < 3:
        res.messages.append("Потрібно щонайменше 3 точки з напругою і струмом.")
        return res
    i = a["i"][ok]
    if i.max() <= 0 or (i.max() - i.min()) < 0.2 * i.max():
        res.messages.append("Струм майже не змінюється: для ВАХ потрібні точки з різним навантаженням (ступеневий тест).")
        return res
    ps = build_params(d)
    keys = ["anode.ocp", "cathode.i0", "cathode.asr"]
    x0 = [ps.v("anode.ocp"), math.log10(ps.v("cathode.i0")), ps.v("cathode.asr")]
    lo = [-2.2, math.log10(ps.v("cathode.i0")) - 4, 0.0]
    hi = [-1.0, math.log10(ps.v("cathode.i0")) + 3, 50.0]
    if fit_tafel and res.n_points >= 8:
        keys.append("cathode.tafel_b")
        x0.append(ps.v("cathode.tafel_b"))
        lo.append(40.0)
        hi.append(250.0)
    res.before = {k: ps.v(k) for k in keys}
    v_before = predict_points(d, exp)
    values, sel = _fit(d, exp, keys, x0, lo, hi, {"cathode.i0"})
    v_after = predict_points(d, exp, values)
    res.rmse_before, _ = _stats(a["v"][sel], v_before[sel])
    res.rmse_after, res.r2 = _stats(a["v"][sel], v_after[sel])
    res.params = values
    res.ok = True
    order = np.argsort(a["i"])
    res.curve = {"x": a["i"][order], "x_label": "Струм, А", "v_meas": a["v"][order],
                 "v_before": v_before[order], "v_after": v_after[order]}
    ocv_new = ps.v("cathode.e_rest") - values["anode.ocp"]
    res.messages.append(f"НРК комірки після калібрування: {ocv_new:.3f} В.")
    if res.n_points < 6:
        res.messages.append("Мало точок: результат орієнтовний.")
    return res


def calibrate_passivation(exp: Experiment, base: Design | None = None) -> CalibrationResult:
    res = CalibrationResult("passivation", False)
    d = experiment_design(exp, base)
    a = exp.arrays()
    ok = np.isfinite(a["v"]) & np.isfinite(a["i"])
    res.n_points = int(ok.sum())
    if res.n_points < 5:
        res.messages.append("Потрібно щонайменше 5 точок напруги й струму в часі.")
        return res
    if a["t_s"][-1] - a["t_s"][0] < 600:
        res.messages.append("Дослід коротший за 10 хв: пасивацію не можна надійно визначити.")
        return res
    ps = build_params(d)
    keys = ["anode.pass_asr_max", "anode.pass_q_char"]
    x0 = [max(ps.v("anode.pass_asr_max"), 0.05), math.log10(ps.v("anode.pass_q_char"))]
    lo, hi = [0.0, 0.0], [100.0, 4.0]
    res.before = {k: ps.v(k) for k in keys}
    v_before = predict_points(d, exp)
    values, sel = _fit(d, exp, keys, x0, lo, hi, {"anode.pass_q_char"})
    v_after = predict_points(d, exp, values)
    res.rmse_before, _ = _stats(a["v"][sel], v_before[sel])
    res.rmse_after, res.r2 = _stats(a["v"][sel], v_after[sel])
    res.params = values
    res.ok = True
    res.curve = {"x": a["t_s"] / 3600.0, "x_label": "Час, год", "v_meas": a["v"],
                 "v_before": v_before, "v_after": v_after}
    return res


def calibrate_efficiency(exp: Experiment, base: Design | None = None) -> CalibrationResult:
    res = CalibrationResult("efficiency", False)
    d = experiment_design(exp, base)
    m = exp.metrics()
    dm = m["mass_loss_g"]
    res.n_points = m["n_points"]
    if not (math.isfinite(dm) and dm > 0):
        res.messages.append("Потрібні початкова й кінцева маса пластини (кінцева менша за початкову).")
        return res
    if m["duration_s"] <= 0:
        res.messages.append("Потрібен час досліду (щонайменше два рядки вимірювань).")
        return res
    ps = build_params(d)
    an = M.ANODES[d.anode]
    z = an.electrons_per_gram() * FARADAY
    q_total = dm * z                                    # Кл, увесь розчинений метал
    q_use = m["charge_ah"] * 3600.0
    area = d.geometry.area_override_cm2
    temp = exp.temperature_c if math.isfinite(exp.temperature_c) else 25.0
    f_t = arrhenius_factor(ps.v("anode.ea") * 1e3, temp)
    cf = ps.v("electrolyte.corr_factor")
    t_total = m["duration_s"]
    chunk = ps.v("anode.chunk")
    res.messages.append(f"Виміряна ефективність анода: {100 * q_use / q_total:.1f}% "
                        f"(заряд {q_use / 3600:.3f} А·год, втрата маси {dm:.3f} г).")
    if q_use < 0.02 * q_total:
        # дослід без навантаження: визначаємо корозію без струму
        i_corr_eff = (q_total - q_use * (1 + chunk)) / (area * t_total)       # А/см²
        val = i_corr_eff / (f_t * cf) * 1000.0
        res.before = {"anode.i_corr0": ps.v("anode.i_corr0")}
        res.params = {"anode.i_corr0": max(val, 0.0)}
        res.messages.append("Струм майже нульовий: калібровано корозію без навантаження.")
    else:
        q_corr0 = area * ps.v("anode.i_corr0") * 1e-3 * f_t * cf * t_total
        k_eff = (q_total - q_use - chunk * q_use - q_corr0) / q_use
        k = k_eff / cf
        res.before = {"anode.k_nde": ps.v("anode.k_nde")}
        if k < 0:
            res.messages.append("Втрата маси менша, ніж дає закон Фарадея для пропущеного заряду: "
                                "перевірте очищення пластини від Mg(OH)₂, зважування та запис струму.")
            res.params = {"anode.k_nde": 0.0}
        else:
            res.params = {"anode.k_nde": k}
    res.ok = True
    return res


def apply_calibration(design: Design, exp: Experiment, result: CalibrationResult) -> tuple[list, list]:
    """Переносить результат у конструкцію. Повертає (застосовані ключі, відхилені з причинами)."""
    applied, refused = [], []
    exp_cat = exp.construction if exp.construction in ("air", "submerged") else "other"
    design_cat = construction_of_cathode(design.cathode)
    if exp_cat == "other" or exp_cat != design_cat or construction_of_cathode(exp.cathode) != exp_cat:
        refused.append(("*", "Тип конструкції досліду не збігається з поточною конструкцією "
                             f"({M.CATEGORY_LABELS.get(design_cat, design_cat)}). Дані не змішуються."))
        return applied, refused
    src = f"Дослід #{exp.id} «{exp.name}», {exp.date}"
    for key, value in result.params.items():
        group = key.split(".")[0]
        if group == "anode" and exp.anode != design.anode:
            refused.append((key, f"анод досліду ({exp.anode}) відрізняється від анода конструкції ({design.anode})"))
            continue
        if group == "cathode" and exp.cathode != design.cathode:
            refused.append((key, f"катод досліду ({exp.cathode}) відрізняється від катода конструкції ({design.cathode})"))
            continue
        set_override(design, key, value, Status.CALIBRATED, src)
        applied.append(key)
    return applied, refused


def replay(exp: Experiment, base: Design | None = None) -> tuple[Simulation, dict]:
    """Повна симуляція досліду з виміряним профілем струму та порівняння напруги."""
    a = exp.arrays()
    t, i = a["t_s"], np.nan_to_num(a["i"], nan=0.0)
    if t.size < 2:
        raise ValueError("Для порівняння потрібно щонайменше два рядки вимірювань.")
    d = experiment_design(exp, base)
    med_dt = float(np.median(np.diff(t))) if t.size > 1 else 10.0
    dt = min(60.0, max(1.0, med_dt))
    sc = Scenario(design=d, sim=SimSettings(load_mode="current", duration_h=float(t[-1]) / 3600.0, dt_s=dt))
    # запис симуляції відноситься до кінця кроку, тому струм беремо в кінці кроку
    prof = lambda tt: float(np.interp(tt + dt, t, i))
    sim = Simulation(sc, current_profile=prof)
    sim.run()
    t_sim = sim.rec.get("t_h") * 3600.0
    v_sim = np.interp(t, t_sim, sim.rec.get("v_term"))
    if t.size and i[0] > 0:
        v_sim[0] = np.nan            # початкова точка симуляції — НРК до вмикання навантаження
    rmse, r2 = _stats(a["v"], v_sim)
    ok = np.isfinite(a["v"]) & np.isfinite(v_sim)
    bias = float(np.mean(v_sim[ok] - a["v"][ok])) if ok.any() else math.nan
    s = sim.summary()
    m = exp.metrics()
    comp = {"t_s": t, "v_meas": a["v"], "v_sim": v_sim, "rmse": rmse, "r2": r2, "bias": bias,
            "mass_loss_sim_g": s["mg_consumed_g"], "mass_loss_meas_g": m["mass_loss_g"],
            "eff_sim_pct": s["anode_eff_pct"], "eff_meas_pct": m["anode_eff_pct"],
            "energy_sim_wh": s["e_term_wh"], "energy_meas_wh": m["energy_wh"]}
    return sim, comp
