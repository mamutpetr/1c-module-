"""Часова симуляція генератора EarthCharge.

Явна схема Ейлера з фіксованим кроком dt: на кожному кроці розв'язується робоча точка
(струм і напруга), потім за законом Фарадея оновлюються маса Mg, вода, шлам, водень,
температура, суперконденсатор і телефон. Усі потоки енергії записуються в журнал
EnergyLedger так, що баланс замикається точно (див. EnergyLedger.residuals()).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields

import numpy as np

from . import constants as C
from .design import (Design, Scenario, clone, derive_geometry, has_errors, validate_design,
                     validate_phone)
from .electrochem import CellModel, OpPoint, StackModel
from .params import build_params
from .phone import PhoneBattery, cable_loss_w, usb_port_power_for_input
from .smartboost import Supercap
from .units import format_duration, fmt

USB_MODES = ("phone", "usb_power", "mppt")
RHO_MG_OH2 = 2.34   # г/см³, густина бруситу
DIRECT_MODES = ("resistor", "current", "open", "profile")

CHANNELS: list[tuple[str, str, str]] = [
    ("t_h", "Час", "год"),
    ("v_term", "Напруга батареї комірок", "В"),
    ("v_cell", "Напруга однієї комірки", "В"),
    ("ocv", "Напруга відкритого кола комірки", "В"),
    ("i_ext", "Струм батареї комірок", "А"),
    ("i_dens", "Густина струму анода", "мА/см²"),
    ("p_term", "Потужність на виводах комірок", "Вт"),
    ("p_gen_bus", "Потужність рушія після DC/DC", "Вт"),
    ("p_gen_max", "Доступна потужність рушія", "Вт"),
    ("p_usb", "Потужність USB-C", "Вт"),
    ("e_term_wh", "Вироблена енергія (виводи комірок)", "Вт·год"),
    ("e_usb_wh", "Енергія через USB-C", "Вт·год"),
    ("mg_remaining_g", "Залишок магнію", "г"),
    ("mg_useful_g", "Mg на корисний струм", "г"),
    ("mg_corr_g", "Mg на самокорозію", "г"),
    ("mg_chunk_g", "Mg — механічні втрати", "г"),
    ("anode_eff", "Ефективність анода (миттєва)", "%"),
    ("anode_eff_cum", "Ефективність анода (накопичена)", "%"),
    ("sys_eff", "Ефективність хімія → USB (накопичена)", "%"),
    ("conv_eff", "ККД перетворювача", "%"),
    ("corr_w", "Втрати на самокорозію (еквівалент)", "Вт"),
    ("h2_ml_min", "Виділення водню", "мл/хв"),
    ("h2_total_ml", "Водень, сумарно", "мл"),
    ("h2_pct", "Концентрація H₂ у корпусі", "%"),
    ("o2_ml_min", "Споживання кисню", "мл/хв"),
    ("o2_margin", "Запас граничного струму катода (до 10×)", "×"),
    ("asr_pass", "Опір пасиваційної плівки", "Ом·см²"),
    ("r_el_mohm", "Опір електроліту (комірка)", "мОм"),
    ("t_el", "Температура електроліту", "°C"),
    ("heat_w", "Тепловиділення", "Вт"),
    ("water_pct", "Залишок води в електроліті", "%"),
    ("sludge_pct", "Об'ємна частка шламу Mg(OH)₂", "%"),
    ("cap_j", "Енергія суперконденсатора", "Дж"),
    ("cap_v", "Напруга суперконденсатора", "В"),
    ("cap_p", "Потужність суперконденсатора (+ заряд)", "Вт"),
    ("phone_soc", "Заряд телефона", "%"),
    ("usb_on", "USB-C увімкнено", "0/1"),
    ("area_factor", "Активна площа (збурення)", "%"),
]
CHANNEL_INFO = {k: (label, unit) for k, label, unit in CHANNELS}


class SimulationError(Exception):
    pass


@dataclass
class EnergyLedger:
    """Енергетичний журнал, Дж. Базис: оборотна напруга Mg-повітря E_rev ≈ 3,09 В."""
    ideal_j: float = 0.0
    corrosion_j: float = 0.0
    chunk_j: float = 0.0
    mixed_potential_j: float = 0.0
    cathode_pol_j: float = 0.0
    anode_pol_j: float = 0.0
    electrolyte_j: float = 0.0
    passivation_j: float = 0.0
    cathode_ohm_j: float = 0.0
    contact_j: float = 0.0
    cells_out_j: float = 0.0
    shunt_j: float = 0.0
    wiring_j: float = 0.0
    terminal_j: float = 0.0
    direct_load_j: float = 0.0
    conv_in_j: float = 0.0
    conv_loss_j: float = 0.0
    bus_j: float = 0.0
    usb_j: float = 0.0
    bus_dump_j: float = 0.0
    cable_j: float = 0.0
    phone_in_j: float = 0.0
    heat_gen_j: float = 0.0
    heat_ambient_j: float = 0.0
    heat_evap_j: float = 0.0
    heat_stored_j: float = 0.0

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


LEDGER_LABELS = {
    "corrosion_j": "Самокорозія Mg (виділення H₂)",
    "chunk_j": "Механічні втрати Mg (частинки)",
    "mixed_potential_j": "Змішаний потенціал (НРК < 3,09 В)",
    "cathode_pol_j": "Поляризація катода (O₂, H₂)",
    "anode_pol_j": "Поляризація анода",
    "electrolyte_j": "Опір електроліту",
    "passivation_j": "Пасиваційна плівка Mg(OH)₂",
    "cathode_ohm_j": "Омічний опір катода",
    "contact_j": "Контакти комірок",
    "shunt_j": "Шунтувальні струми",
    "wiring_j": "З'єднання між комірками",
    "conv_loss_j": "Втрати DC/DC перетворювача",
    "cap_loss_j": "Втрати суперконденсатора",
    "cable_j": "Кабель USB",
    "phone_loss_j": "Власне споживання й втрати телефона",
    "stored_j": "Запасено в акумуляторі телефона",
    "usb_load_j": "Віддано навантаженню USB-C",
    "direct_load_j": "Віддано навантаженню на виводах",
    "cap_net_j": "Залишок у суперконденсаторі",
}


class Recorder:
    def __init__(self, keys: list[str], capacity: int):
        self.keys = keys
        self.n = 0
        self.cap = max(16, capacity)
        self.data = {k: np.empty(self.cap) for k in keys}

    def append(self, row: dict) -> None:
        if self.n >= self.cap:
            self.cap *= 2
            for k in self.keys:
                arr = np.empty(self.cap)
                arr[: self.n] = self.data[k][: self.n]
                self.data[k] = arr
        for k in self.keys:
            self.data[k][self.n] = row.get(k, np.nan)
        self.n += 1

    def get(self, key: str) -> np.ndarray:
        return self.data[key][: self.n]

    def last(self, key: str, default: float = float("nan")) -> float:
        return float(self.data[key][self.n - 1]) if self.n else default

    def as_dict(self) -> dict:
        return {k: self.get(k).copy() for k in self.keys}


class DipSchedule:
    """Короткочасні провали потужності (бульбашки, перекриття повітря) — тестовий сценарій."""

    def __init__(self, design: Design, duration_s: float):
        dcfg = design.disturbances
        self.enabled = dcfg.enabled and dcfg.mean_interval_s > 0 and dcfg.duration_s > 0
        self.depth = min(max(dcfg.depth_pct / 100.0, 0.0), 0.95)
        self.windows: list[tuple[float, float]] = []
        if self.enabled:
            rng = random.Random(dcfg.seed)
            t = rng.expovariate(1.0 / dcfg.mean_interval_s)
            while t < duration_s:
                self.windows.append((t, t + dcfg.duration_s))
                t += dcfg.duration_s + rng.expovariate(1.0 / dcfg.mean_interval_s)
        self._k = 0

    def factor(self, t: float) -> float:
        if not self.enabled:
            return 1.0
        while self._k < len(self.windows) and self.windows[self._k][1] <= t:
            self._k += 1
        if self._k < len(self.windows) and self.windows[self._k][0] <= t:
            return 1.0 - self.depth
        return 1.0


@dataclass
class Event:
    t_s: float
    level: str      # "info" | "ok" | "warning" | "critical"
    text: str


@dataclass
class SimState:
    t: float = 0.0
    mg_useful_g: float = 0.0      # на комірку
    mg_corr_g: float = 0.0
    mg_chunk_g: float = 0.0
    q_useful_c: float = 0.0       # на комірку
    q_corr_c: float = 0.0
    q_chunk_c: float = 0.0
    q_pass_c_cm2: float = 0.0
    water_g: float = 0.0          # на комірку
    sludge_g: float = 0.0         # на комірку
    t_el: float = 25.0
    h2_ml: float = 0.0            # усі комірки, при 25 °C
    h2_frac: float = 0.0          # об'ємна частка в корпусі
    usb_on: bool = False
    converter_trips: int = 0
    starved_steps: int = 0
    peak_t_el: float = 25.0
    peak_h2_frac: float = 0.0
    peak_h2_ml_min: float = 0.0


class Simulation:
    def __init__(self, scenario: Scenario, current_profile=None, unlimited_mg: bool = False):
        self.sc = clone(scenario)
        self.unlimited_mg = unlimited_mg   # для підбору конструкції: маса Mg не обмежує роботу
        d = self.sc.design
        self.mode = "profile" if current_profile is not None else self.sc.sim.load_mode
        issues = validate_design(d)
        if self.mode == "phone":
            issues += validate_phone(self.sc.phone)
        self.issues = issues
        if has_errors(issues):
            raise SimulationError("; ".join(i.message for i in issues if i.level == "error"))
        self.profile = current_profile
        self.ps = build_params(d)
        self.geo = derive_geometry(d, self.ps.v("anode.density"))
        self.cell = CellModel(d, self.ps, self.geo)
        self.stack = StackModel(self.cell, d, self.geo, self.ps)
        if self.cell.ocv >= C.E_REV_MG_AIR:
            raise SimulationError("Напруга відкритого кола перевищує термодинамічну межу 3,09 В — перевірте параметри.")
        self.n = self.geo.n_cells
        self.dt = max(0.05, float(self.sc.sim.dt_s))
        if self.mode == "phone":
            self.duration_s = self.sc.phone.max_time_h * 3600.0
        else:
            self.duration_s = self.sc.sim.duration_h * 3600.0
        self.cap = Supercap(d.supercap) if (d.supercap.enabled and d.converter.enabled and self.mode in USB_MODES) else None
        self.phone = PhoneBattery(self.sc.phone) if self.mode == "phone" else None
        self.dips = DipSchedule(d, self.duration_s)
        self.ledger = EnergyLedger()
        self.events: list[Event] = []
        self._flags: dict = {}
        el_density = self.ps.v("electrolyte.density")
        salt = self.ps.v("electrolyte.salt_pct") / 100.0
        vol = d.geometry.electrolyte_volume_ml
        self.water0_g = vol * el_density * (1.0 - salt)
        self.salt_g = vol * el_density * salt
        self.mg0_cell_g = self.geo.mass_per_cell_g
        self.mg_usable_cell_g = self.geo.usable_mass_per_cell_g
        self.state = SimState(water_g=self.water0_g, t_el=d.environment.ambient_c, peak_t_el=d.environment.ambient_c)
        self.finished = False
        self.finish_reason = ""
        self.last_op = OpPoint(v_term=self.stack.open_point().v_term, v_cell=self.cell.ocv)
        self.last_gen_max = 0.0
        self.last_rates: dict = {}
        self._sb_pulse = False
        self._usb_start_t = 0.0
        self._p_smooth: float | None = None
        steps = int(self.duration_s / self.dt) + 4
        self.rec = Recorder([k for k, _, _ in CHANNELS], steps)
        self._log(0.0, "info", "Генератор активовано: електроліт залито, реакція почалася.")
        if self.cell.category == "submerged":
            self._log(0.0, "warning", "Обрано занурений катод (простий гальванічний елемент), а не повітряний катод.")
        self._record_initial()

    # ------------------------------------------------------------ допоміжне
    @property
    def t(self) -> float:
        return self.state.t

    @property
    def design(self) -> Design:
        return self.sc.design

    def _log(self, t: float, level: str, text: str) -> None:
        self.events.append(Event(t, level, text))

    def _flag(self, name: str, active: bool, level: str, text_on: str, text_off: str | None = None,
              cooldown_s: float = 900.0) -> None:
        prev = self._flags.get(name)
        if active and (prev is None or not prev[0]):
            last_t = prev[1] if prev else -1e18
            if self.t - last_t >= cooldown_s:
                self._log(self.t, level, text_on)
                self._flags[name] = (True, self.t)
            else:
                self._flags[name] = (True, last_t)
        elif not active and prev is not None and prev[0]:
            if text_off:
                self._log(self.t, "info", text_off)
            self._flags[name] = (False, prev[1])

    def _record_initial(self) -> None:
        row = {k: 0.0 for k, _, _ in CHANNELS}
        st = self.state
        row.update({
            "v_term": self.last_op.v_term, "v_cell": self.cell.ocv, "ocv": self.cell.ocv,
            "mg_remaining_g": self.mg0_cell_g * self.n, "t_el": st.t_el, "water_pct": 100.0,
            "phone_soc": self.phone.soc * 100.0 if self.phone else np.nan,
            "cap_j": self.cap.e if self.cap else 0.0, "cap_v": self.cap.v if self.cap else 0.0,
            "area_factor": 100.0, "r_el_mohm": self.cell.r_el * 1000.0, "o2_margin": np.nan,
            "anode_eff": np.nan, "anode_eff_cum": np.nan, "sys_eff": np.nan, "conv_eff": np.nan,
        })
        self.rec.append(row)

    # ------------------------------------------------------------ стан
    def mg_consumed_cell_g(self) -> float:
        s = self.state
        return s.mg_useful_g + s.mg_corr_g + s.mg_chunk_g

    def mg_remaining_total_g(self) -> float:
        return max(0.0, self.mg0_cell_g - self.mg_consumed_cell_g()) * self.n

    def mg_usable_left_total_g(self) -> float:
        return max(0.0, self.mg_usable_cell_g - self.mg_consumed_cell_g()) * self.n

    def forecast_runtime_s(self) -> float:
        """Прогноз часу роботи за поточною швидкістю витрачання магнію."""
        rate = self.last_rates.get("mg_g_s_total", 0.0)
        if rate <= 0:
            return math.inf
        return self.mg_usable_left_total_g() / rate

    def _sludge_fraction(self) -> float:
        """Об'ємна частка гелю Mg(OH)₂ в електроліті."""
        st = self.state
        gel_ml = st.sludge_g / RHO_MG_OH2 * self.ps.v("system.sludge_swell")
        liquid_ml = st.water_g / C.RHO_WATER + gel_ml
        return gel_ml / liquid_ml if liquid_ml > 0 else 0.9

    def _alive_reason(self) -> str:
        st = self.state
        if not self.unlimited_mg and self.mg_consumed_cell_g() >= self.mg_usable_cell_g:
            return "Магній вичерпано: досягнуто допустимого використання пластин."
        if st.water_g <= self.ps.v("system.water_end") * self.water0_g:
            return "Електроліт вичерпано: вода витрачена на реакцію та випаровування."
        if st.t_el <= self.ps.v("electrolyte.freezing"):
            return "Електроліт замерз: реакція зупинилася."
        if st.t_el >= 100.0:
            return "Перегрів: електроліт закипає. Симуляцію зупинено."
        return ""

    # ------------------------------------------------------------ крок
    def step(self) -> None:
        if self.finished:
            return
        dt = min(self.dt, self.duration_s - self.state.t)
        if dt <= 1e-9:
            self._finish("Час симуляції завершено.")
            return
        st = self.state
        t = st.t
        reason = self._alive_reason()
        if reason:
            self._finish(reason)
            return

        area_factor = self.dips.factor(t)
        self.cell.set_conditions(st.t_el, st.q_pass_c_cm2, self._sludge_fraction(), area_factor, t / 3600.0)

        flows = {"usb": 0.0, "cap_p": 0.0, "gen_bus": 0.0, "gen_max": 0.0, "phone_in": 0.0}
        if self.mode in USB_MODES:
            op = self._dispatch_usb(dt, flows)
        else:
            op = self._dispatch_direct(t)
        self.last_op = op
        self._account(op, dt, flows)
        st.t = t + dt
        self._post_step_events(op, flows)
        if st.t >= self.duration_s - 1e-9:
            self._finish("Час симуляції завершено.")
        elif self.phone and self.phone.done and self.sc.sim.stop_when_phone_done:
            self._finish("Телефон заряджено.")

    def _dispatch_direct(self, t: float) -> OpPoint:
        mode = self.mode
        if mode == "resistor":
            return self.stack.solve_resistor(max(self.sc.sim.resistor_ohm, 1e-6))
        if mode in ("current", "profile"):
            i_set = self.profile(t) if mode == "profile" else self.sc.sim.current_a
            op, ok = self.stack.solve_current(max(0.0, float(i_set)))
            self._flag("current_limit", not ok, "warning",
                       f"Заданий струм {fmt(i_set)} А недосяжний: батарея комірок у режимі короткого замикання.")
            return op
        return self.stack.open_point()

    def _dispatch_usb(self, dt: float, flows: dict) -> OpPoint:
        d = self.design
        conv = d.converter
        st = self.state
        if not conv.enabled:
            self._flag("no_conv", True, "warning", "Перетворювач вимкнено: USB-C недоступний.")
            return self.stack.open_point()
        cap = self.cap
        usb_enabled = st.t >= d.supercap.start_delay_s - 1e-9 if cap else True
        if usb_enabled and not st.usb_on:
            st.usb_on = True
            self._usb_start_t = st.t
            self._sb_pulse = cap is not None
            if cap and d.supercap.start_delay_s > 0:
                self._log(st.t, "info", f"SmartBoost: USB-C увімкнено через {d.supercap.start_delay_s:.0f} с. "
                                       f"Накопичено {fmt(cap.e, 1)} Дж ({fmt(cap.e / 3600.0, 4)} Вт·год).")
        v_bus = conv.v_out
        r_cable = self.sc.phone.cable_resistance_mohm / 1000.0 if self.mode == "phone" else 0.0
        capab = self.stack.capability()
        gen_max = capab.p_max
        self.last_gen_max = gen_max
        flows["gen_max"] = gen_max
        self._flag("ocv_low", capab.limited_by == "ocv_low", "critical",
                   "Напруга батареї комірок нижча за мінімальну вхідну напругу перетворювача: "
                   "USB-C не працює. Збільште кількість послідовних комірок.",
                   "Напруга батареї комірок знову достатня для перетворювача.")
        charge_req = cap.charge_request_bus_w(dt) if cap else 0.0
        cap_avail = cap.discharge_avail_bus_w(dt) if (cap and usb_enabled) else 0.0
        tripped = False
        if not usb_enabled:
            port = 0.0
        elif self.mode == "mppt":
            port = gen_max
        elif self.mode == "phone":
            p_in_req = self.phone.request_input_w(dt)
            port_req = usb_port_power_for_input(p_in_req, v_bus, r_cable)
            aicl = self.ps.v("system.aicl_margin")
            deliverable = min(port_req, gen_max * aicl + cap_avail)
            if cap is not None:
                deliverable = min(deliverable, self._smartboost_limit(gen_max * aicl, dt))
            p_in = deliverable - cable_loss_w(deliverable, v_bus, r_cable)
            starved = port_req > 0 and p_in < self.sc.phone.min_input_w
            port = 0.0 if starved else deliverable
            if starved:
                st.starved_steps += 1
            self._flag("starved", starved, "warning",
                       f"Телефон не заряджається: доступно {fmt(p_in, 3)} Вт, мінімум {fmt(self.sc.phone.min_input_w, 2)} Вт.",
                       "Заряджання телефона відновлено.")
        else:
            port_req = self.sc.sim.usb_power_w
            if port_req <= gen_max + cap_avail + 1e-12:
                port = port_req
            elif conv.control == "mppt":
                port = gen_max + cap_avail
            else:
                port, tripped = 0.0, True
                st.converter_trips += 1
            self._flag("trip", tripped, "warning",
                       "Перевантаження: простий перетворювач вимикається через просідання напруги (UVLO). "
                       "Живлення USB-C переривчасте.", "Перетворювач знову тримає навантаження.")

        if tripped or gen_max <= 0:
            op = self.stack.open_point()
            gen_out = 0.0
        else:
            # Не виводимо рушій на самий верх кривої P–I (там різко зростає струм і падає ККД):
            # сумарний відбір обмежено запасом AICL, якщо навантаження само не вимагає більшого.
            if self.mode == "mppt":
                gen_limit = gen_max
            else:
                gen_limit = min(gen_max, max(port, gen_max * self.ps.v("system.aicl_margin")))
            gen_target = min(gen_limit, port + charge_req)
            if gen_target > 1e-9:
                op = self.stack.solve_output(gen_target, capab)
                gen_out = op.p_conv_out
            else:
                op = self.stack.open_point()
                gen_out = 0.0
        from_gen = min(port, gen_out)
        to_cap = gen_out - from_gen
        deficit = port - from_gen
        cap_out = 0.0
        dump = 0.0
        if cap:
            if deficit > 1e-12:
                cap_out = cap.discharge(deficit, dt)
            elif to_cap > 0:
                accept = min(to_cap, charge_req)
                dump = to_cap - accept
                cap.charge(accept, dt)
            else:
                cap.idle(dt)
        else:
            dump = to_cap
        usb = from_gen + cap_out
        flows.update(usb=usb, gen_bus=gen_out, dump=dump,
                     cap_p=(to_cap - dump) - cap_out if cap else 0.0)
        if self.phone:
            p_in = usb - cable_loss_w(usb, v_bus, r_cable)
            flows["phone_in"] = p_in
            flows["cable"] = usb - p_in
            self.phone.update(p_in, dt, st.t + dt)
        return op

    def _smartboost_limit(self, gen_avail: float, dt: float) -> float:
        """Обмеження потужності USB-C при SmartBoost.

        Стартовий імпульс: телефон бере стільки, скільки дають рушій і конденсатор разом,
        доки конденсатор не розрядиться (або 10 хв). Далі — згладжування: USB-C обмежено
        ковзним середнім доступної потужності рушія; якщо конденсатор нижче цільового заряду,
        частину потужності залишено на підзаряд. Під час короткого провалу рушія різницю
        покриває конденсатор.
        """
        cfg = self.design.supercap
        cap = self.cap
        st = self.state
        if self._sb_pulse:
            if cap.soc <= 0.02 or st.t - self._usb_start_t > 600.0:
                self._sb_pulse = False
                self._p_smooth = gen_avail
                self._log(st.t, "info", "SmartBoost: стартовий імпульс завершено, далі — згладжування провалів.")
            else:
                return math.inf
        if self._p_smooth is None:
            self._p_smooth = gen_avail
        tau = max(cfg.smoothing_tau_s, 1e-6)
        self._p_smooth += (gen_avail - self._p_smooth) * (1.0 - math.exp(-dt / tau))
        share = cfg.recharge_share_pct / 100.0 if cap.soc < cfg.soc_target_pct / 100.0 else 0.0
        return max(0.0, self._p_smooth * (1.0 - share))

    # ------------------------------------------------------------ облік
    def _account(self, op: OpPoint, dt: float, flows: dict) -> None:
        st, cell, lg, n = self.state, self.cell, self.ledger, self.n
        ps = self.ps
        i = op.i_cell
        comp = cell.components(i)
        i_h = cell.corrosion_current(i)
        i_chunk = cell.chunk_current(i)
        i_her_c = comp["i_her_c"]
        e_rev = C.E_REV_MG_AIR
        F = C.FARADAY

        # --- енергетичний журнал (усі комірки)
        lg.ideal_j += n * (i + i_h + i_chunk) * e_rev * dt
        lg.corrosion_j += n * i_h * e_rev * dt
        lg.chunk_j += n * i_chunk * e_rev * dt
        lg.mixed_potential_j += n * i * (e_rev - cell.ocv) * dt
        lg.cathode_pol_j += n * i * comp["eta_c"] * dt
        lg.anode_pol_j += n * i * comp["eta_a"] * dt
        lg.electrolyte_j += n * i * comp["ohm_el"] * dt
        lg.passivation_j += n * i * comp["ohm_pass"] * dt
        lg.cathode_ohm_j += n * i * comp["ohm_cath"] * dt
        lg.contact_j += n * i * comp["ohm_contact"] * dt
        lg.cells_out_j += n * i * comp["v"] * dt
        lg.shunt_j += op.v_int * op.i_shunt * dt
        lg.wiring_j += op.i_ext * op.i_ext * self.stack.r_wire * dt
        lg.terminal_j += op.p_term * dt
        if self.mode in USB_MODES:
            lg.conv_in_j += op.p_conv_in * dt
            lg.conv_loss_j += (op.p_conv_in - op.p_conv_out) * dt
            lg.bus_j += op.p_conv_out * dt
            lg.usb_j += flows["usb"] * dt
            lg.bus_dump_j += flows.get("dump", 0.0) * dt
            lg.cable_j += flows.get("cable", 0.0) * dt
            lg.phone_in_j += flows.get("phone_in", 0.0) * dt
        else:
            lg.direct_load_j += op.p_term * dt

        # --- закон Фарадея (на комірку)
        z = F * cell.e_per_g
        dm_useful = i * dt / z
        dm_corr = i_h * dt / z
        dm_chunk = i_chunk * dt / z
        st.mg_useful_g += dm_useful
        st.mg_corr_g += dm_corr
        st.mg_chunk_g += dm_chunk
        st.q_useful_c += i * dt
        st.q_corr_c += i_h * dt
        st.q_chunk_c += i_chunk * dt
        st.q_pass_c_cm2 += (i + i_h) * dt / cell.A_a0

        # --- речовини (на комірку)
        mol_mg_oh2 = (i + i_h) * dt / (2.0 * F)
        mol_water = (i - i_her_c) * dt / (2.0 * F) + (i_h + i_her_c) * dt / F
        mol_h2 = (i_h + i_her_c) * dt / (2.0 * F)
        mol_o2 = (i - i_her_c) * dt / (4.0 * F)
        env = self.design.environment
        a_evap = cell.A_c0 if cell.category == "air" else 0.2 * cell.A_c0
        dp = max(0.0, C.saturation_vapor_pressure_kpa(st.t_el)
                 - env.relative_humidity_pct / 100.0 * C.saturation_vapor_pressure_kpa(env.ambient_c))
        evap_g = ps.v("system.k_evap") * a_evap * dp * dt / 3600.0
        st.water_g = max(0.0, st.water_g - mol_water * C.M_H2O - evap_g)
        st.sludge_g += mol_mg_oh2 * C.M_MG_OH2
        vm_ml = C.molar_gas_volume_l(25.0) * 1000.0
        h2_ml = mol_h2 * vm_ml * n
        st.h2_ml += h2_ml
        # концентрація H2 у вільному об'ємі корпусу (точний розв'язок лінійного рівняння за крок)
        v_free = max(env.enclosure_free_volume_ml, 1.0)
        q_air = env.air_exchange_per_h * v_free / 3600.0
        q_h2 = h2_ml / dt
        q_tot = q_air + q_h2
        if q_tot > 0:
            c_ss = q_h2 / q_tot
            st.h2_frac = c_ss + (st.h2_frac - c_ss) * math.exp(-q_tot * dt / v_free)
        st.peak_h2_frac = max(st.peak_h2_frac, st.h2_frac)
        st.peak_h2_ml_min = max(st.peak_h2_ml_min, h2_ml / dt * 60.0)

        # --- тепловий баланс (усі комірки)
        q_cell = ((i - i_her_c) * (C.E_TN_MG_AIR - comp["v"])
                  + i_her_c * (-C.DH_MG_CORROSION / (2.0 * F) - comp["v"])
                  + i_h * (-C.DH_MG_CORROSION) / (2.0 * F))
        heat_w = n * q_cell + op.v_int * op.i_shunt
        evap_w = n * evap_g * C.LATENT_HEAT_WATER / dt
        mg_left = max(self.mg0_cell_g - self.mg_consumed_cell_g(), 0.0)
        c_th = n * (st.water_g * C.CP_WATER + self.salt_g * C.CP_NACL + mg_left * C.CP_MG
                    + st.sludge_g * 1.3) + ps.v("system.c_housing")
        h_a = ps.v("system.h_conv") * self.geo.heat_area_cm2 * 1e-4
        lg.heat_gen_j += heat_w * dt
        lg.heat_evap_j += evap_w * dt
        if env.thermal_model:
            amb_w = h_a * (st.t_el - env.ambient_c)
            d_t = (heat_w - amb_w - evap_w) * dt / c_th
            lg.heat_ambient_j += amb_w * dt
            lg.heat_stored_j += c_th * d_t
            st.t_el += d_t
        else:
            lg.heat_ambient_j += (heat_w - evap_w) * dt
        st.peak_t_el = max(st.peak_t_el, st.t_el)

        # --- швидкості для прогнозу та графіків
        total_rate = n * (i + i_h + i_chunk) / z
        self.last_rates = {"mg_g_s_total": total_rate, "h2_ml_min": h2_ml / dt * 60.0,
                           "o2_ml_min": n * mol_o2 * vm_ml / dt * 60.0, "heat_w": heat_w,
                           "corr_w": n * i_h * e_rev, "i_h": i_h}
        cons = self.mg_consumed_cell_g()
        q_all = st.q_useful_c + st.q_corr_c + st.q_chunk_c
        usb_total = lg.usb_j if self.mode in USB_MODES else lg.direct_load_j
        i_lim_total = cell.i_lim * cell.A_c
        row = {
            "t_h": (st.t + dt) / 3600.0,
            "v_term": op.v_term, "v_cell": op.v_cell, "ocv": cell.ocv, "i_ext": op.i_ext,
            "i_dens": i / cell.A_a * 1000.0, "p_term": op.p_term,
            "p_gen_bus": flows["gen_bus"], "p_gen_max": flows["gen_max"], "p_usb": flows["usb"],
            "e_term_wh": lg.terminal_j / 3600.0, "e_usb_wh": lg.usb_j / 3600.0,
            "mg_remaining_g": max(0.0, self.mg0_cell_g - cons) * n,
            "mg_useful_g": st.mg_useful_g * n, "mg_corr_g": st.mg_corr_g * n, "mg_chunk_g": st.mg_chunk_g * n,
            "anode_eff": 100.0 * i / (i + i_h + i_chunk) if (i + i_h + i_chunk) > 0 else 0.0,
            "anode_eff_cum": 100.0 * st.q_useful_c / q_all if q_all > 0 else 0.0,
            "sys_eff": 100.0 * usb_total / lg.ideal_j if lg.ideal_j > 0 else 0.0,
            "conv_eff": 100.0 * op.p_conv_out / op.p_conv_in if op.p_conv_in > 1e-6 and op.p_conv_out > 0 else np.nan,
            "corr_w": n * i_h * e_rev,
            "h2_ml_min": h2_ml / dt * 60.0, "h2_total_ml": st.h2_ml, "h2_pct": st.h2_frac * 100.0,
            "o2_ml_min": n * mol_o2 * vm_ml / dt * 60.0,
            "o2_margin": min(i_lim_total / i, 10.0) if i > 1e-9 else np.nan,
            "asr_pass": cell.asr_pass, "r_el_mohm": cell.r_el * 1000.0, "sludge_pct": cell.sludge_phi * 100.0,
            "t_el": st.t_el, "heat_w": heat_w,
            "water_pct": 100.0 * st.water_g / self.water0_g if self.water0_g > 0 else 0.0,
            "cap_j": self.cap.e if self.cap else 0.0, "cap_v": self.cap.v if self.cap else 0.0,
            "cap_p": flows.get("cap_p", 0.0),
            "phone_soc": self.phone.soc * 100.0 if self.phone else np.nan,
            "usb_on": 1.0 if (self.mode in USB_MODES and flows["usb"] > 0) else 0.0,
            "area_factor": 100.0 * cell.area_factor,
        }
        self.rec.append(row)

    def _post_step_events(self, op: OpPoint, flows: dict) -> None:
        st = self.state
        cell = self.cell
        i = op.i_cell
        if i > 0:
            margin = cell.i_lim * cell.A_c / i
            if self.cell.category == "air":
                self._flag("o2", margin < 1.25, "warning",
                           "Струм наближається до граничного для повітряного катода: бракує кисню або активності "
                           "каталізатора (ризик виділення H₂ на катоді).",
                           "Запас за киснем відновлено.")
            else:
                self._flag("o2", margin < 1.0, "warning",
                           "Розчиненого кисню не вистачає: на графітовому катоді виділяється водень, напруга падає.")
        self._flag("h2_warn", st.h2_frac > 0.01, "warning",
                   "Концентрація водню в корпусі перевищила 1% (25% нижньої межі вибуховості). Потрібна вентиляція.")
        self._flag("h2_crit", st.h2_frac > 0.04, "critical",
                   "Концентрація водню в корпусі вище 4% — вибухонебезпечна суміш!")
        self._flag("hot", st.t_el > 60.0, "warning", "Температура електроліту перевищила 60 °C.")
        if self.cap and st.usb_on:
            self._flag("cap_empty", self.cap.soc <= 0.02, "info",
                       "Суперконденсатор розряджено до мінімальної напруги: далі живлення лише від рушія.",
                       "Суперконденсатор знову має запас енергії.", cooldown_s=1800.0)
        if self.phone and self.phone.done and not self._flags.get("phone_done"):
            self._flags["phone_done"] = (True, st.t)
            self._log(st.t, "ok", f"Телефон заряджено до {self.sc.phone.soc_target_pct:.0f}% "
                                  f"за {format_duration(self.phone.t_done_s)}.")

    def _finish(self, reason: str) -> None:
        if self.finished:
            return
        self.finished = True
        self.finish_reason = reason
        level = "info" if reason.startswith("Час") or reason.startswith("Телефон") else "warning"
        self._log(self.state.t, level, reason)

    # ------------------------------------------------------------ запуск
    def advance(self, sim_seconds: float, max_steps: int = 10**7) -> None:
        target = self.state.t + sim_seconds
        k = 0
        while not self.finished and self.state.t < target - 1e-9 and k < max_steps:
            self.step()
            k += 1

    def run(self, progress=None, cancel=None) -> "Simulation":
        last = -1
        while not self.finished:
            self.step()
            if progress is not None:
                pct = int(100 * self.state.t / self.duration_s)
                if pct != last:
                    progress(pct)
                    last = pct
            if cancel is not None and cancel():
                break
        return self

    # ------------------------------------------------------------ результати
    def ledger_breakdown(self) -> dict:
        """Розподіл ідеальної хімічної енергії за статтями, Дж (сума = ideal_j)."""
        lg = self.ledger
        out = {k: getattr(lg, k) for k in (
            "corrosion_j", "chunk_j", "mixed_potential_j", "cathode_pol_j", "anode_pol_j", "electrolyte_j",
            "passivation_j", "cathode_ohm_j", "contact_j", "shunt_j", "wiring_j")}
        if self.mode in USB_MODES:
            # bus_dump — числовий залишок розподілу шини (≈ 0), віднесено до втрат DC/DC
            out["conv_loss_j"] = lg.conv_loss_j + lg.bus_dump_j
            if self.cap:
                cl = self.cap.ledger
                out["cap_loss_j"] = cl.conv_loss_j + cl.esr_loss_j + cl.leak_loss_j
                out["cap_net_j"] = self.cap.e - cl.initial_j
            if self.phone:
                pl = self.phone.ledger
                out["cable_j"] = lg.cable_j
                out["phone_loss_j"] = pl.self_from_usb_j + pl.charge_loss_j
                out["stored_j"] = pl.stored_j
            else:
                out["usb_load_j"] = lg.usb_j
        else:
            out["direct_load_j"] = lg.direct_load_j
        return out

    def residuals(self) -> dict:
        """Залишки всіх балансових тотожностей, Дж (мають бути ≈ 0)."""
        lg = self.ledger
        res = {}
        chem = (lg.corrosion_j + lg.chunk_j + lg.mixed_potential_j + lg.cathode_pol_j + lg.anode_pol_j
                + lg.electrolyte_j + lg.passivation_j + lg.cathode_ohm_j + lg.contact_j + lg.cells_out_j)
        res["Хімічна енергія = втрати + вихід комірок"] = lg.ideal_j - chem
        res["Вихід комірок = шунт + з'єднання + виводи"] = lg.cells_out_j - (lg.shunt_j + lg.wiring_j + lg.terminal_j)
        res["Виводи = вхід DC/DC + пряме навантаження"] = lg.terminal_j - (lg.conv_in_j + lg.direct_load_j)
        res["Вхід DC/DC = втрати + шина"] = lg.conv_in_j - (lg.conv_loss_j + lg.bus_j)
        cap_in = self.cap.ledger.bus_in_j if self.cap else 0.0
        cap_out = self.cap.ledger.bus_out_j if self.cap else 0.0
        res["Шина + розряд конденсатора = USB + заряд + скидання"] = (lg.bus_j + cap_out) - (lg.usb_j + cap_in + lg.bus_dump_j)
        if self.cap:
            res["Суперконденсатор: вхід − вихід − втрати = ΔE"] = self.cap.balance_residual_j()
        if self.phone:
            pl = self.phone.ledger
            res["USB = кабель + вхід телефона"] = lg.usb_j - (lg.cable_j + lg.phone_in_j)
            res["Вхід телефона = власне споживання + втрати + акумулятор"] = (
                pl.input_j - (pl.self_from_usb_j + pl.charge_loss_j + pl.stored_j))
            res["Акумулятор: початок + надійшло − розряд = кінець"] = (
                self.phone.initial_j + pl.stored_j - pl.self_from_batt_j - self.phone.e_j)
        res["Тепло: виділено = в довкілля + випаровування + нагрів"] = (
            lg.heat_gen_j - (lg.heat_ambient_j + lg.heat_evap_j + lg.heat_stored_j))
        st = self.state
        z = C.FARADAY * self.cell.e_per_g
        mass_from_charge = (st.q_useful_c + st.q_corr_c + st.q_chunk_c) / z
        res["Фарадей: маса Mg = заряд / (F·z̄), г"] = self.mg_consumed_cell_g() - mass_from_charge
        return res

    def summary(self) -> dict:
        st, lg, n = self.state, self.ledger, self.n
        t = max(st.t, 1e-9)
        cons = self.mg_consumed_cell_g() * n
        q_all = st.q_useful_c + st.q_corr_c + st.q_chunk_c
        out_j = lg.usb_j if self.mode in USB_MODES else lg.direct_load_j
        s = {
            "t_s": st.t,
            "finished": self.finished,
            "finish_reason": self.finish_reason,
            "e_term_wh": lg.terminal_j / 3600.0,
            "e_usb_wh": lg.usb_j / 3600.0,
            "e_out_wh": out_j / 3600.0,
            "e_ideal_wh": lg.ideal_j / 3600.0,
            "p_avg_term_w": lg.terminal_j / t,
            "p_avg_out_w": out_j / t,
            "mg_initial_g": self.mg0_cell_g * n,
            "mg_consumed_g": cons,
            "mg_useful_g": st.mg_useful_g * n,
            "mg_corr_g": st.mg_corr_g * n,
            "mg_chunk_g": st.mg_chunk_g * n,
            "mg_remaining_g": self.mg_remaining_total_g(),
            "mg_usable_left_g": self.mg_usable_left_total_g(),
            "anode_eff_pct": 100.0 * st.q_useful_c / q_all if q_all > 0 else 0.0,
            "sys_eff_pct": 100.0 * out_j / lg.ideal_j if lg.ideal_j > 0 else 0.0,
            "wh_per_g_term": lg.terminal_j / 3600.0 / cons if cons > 0 else 0.0,
            "wh_per_g_out": out_j / 3600.0 / cons if cons > 0 else 0.0,
            "h2_total_l": st.h2_ml / 1000.0,
            "peak_h2_pct": st.peak_h2_frac * 100.0,
            "peak_t_el": st.peak_t_el,
            "water_left_pct": 100.0 * st.water_g / self.water0_g if self.water0_g > 0 else 0.0,
            "forecast_runtime_s": self.forecast_runtime_s(),
            "converter_trips": st.converter_trips,
            "verdicts": self.verdicts(),
        }
        if self.phone:
            ph = self.phone
            s.update({
                "phone_soc_pct": ph.soc * 100.0,
                "phone_done": ph.done,
                "phone_t_done_s": ph.t_done_s,
                "phone_stored_wh": ph.ledger.stored_j / 3600.0,
                "phone_in_wh": ph.ledger.input_j / 3600.0,
                "phone_needed_in_wh": ph.energy_needed_wh(),
                "phone_min_time_h": ph.min_charge_time_h(),
            })
        if self.cap:
            s.update(self.smartboost_stats())
        return s

    # ------------------------------------------------------------ висновки
    def smartboost_stats(self) -> dict:
        d = self.design.supercap
        t_h = self.rec.get("t_h") * 3600.0
        cap_j = self.rec.get("cap_j")
        p_usb = self.rec.get("p_usb")
        p_gen = self.rec.get("p_gen_max")
        k_start = int(np.searchsorted(t_h, d.start_delay_s - 1e-9))
        k_start = min(k_start, len(t_h) - 1)
        e_start = float(cap_j[k_start]) if len(cap_j) else 0.0
        after = t_h >= d.start_delay_s
        depleted_at = None
        if self.cap and np.any(after):
            empty_j = self.cap.e_min + 0.02 * (self.cap.e_max - self.cap.e_min)
            idx = np.nonzero(after & (cap_j <= empty_j))[0]
            if idx.size:
                depleted_at = float(t_h[idx[0]])
        boost_window = after & (t_h <= (depleted_at if depleted_at else t_h[-1] if len(t_h) else 0))
        peak_usb = float(np.nanmax(p_usb[after])) if np.any(after) else 0.0
        gen_after = float(np.nanmedian(p_gen[after])) if np.any(after) else 0.0
        return {
            "sb_e_start_j": e_start,
            "sb_peak_usb_w": peak_usb,
            "sb_depleted_at_s": depleted_at,
            "sb_gen_median_w": gen_after,
            "sb_boost_samples": int(np.sum(boost_window)),
        }

    def verdicts(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        st = self.state
        if self.mode == "phone" and self.phone:
            out += self._phone_verdicts()
        if self.cap:
            out += self._smartboost_verdicts()
        if st.peak_h2_frac > 0.04:
            out.append(("critical", f"Пікова концентрація H₂ у корпусі {fmt(st.peak_h2_frac * 100, 1)}% — "
                                    "вище нижньої межі вибуховості (4%)."))
        elif st.peak_h2_frac > 0.01:
            out.append(("warning", f"Пікова концентрація H₂ у корпусі {fmt(st.peak_h2_frac * 100, 1)}%: потрібна вентиляція."))
        if st.peak_h2_frac > 0.01:
            need_l_min = 99.0 * st.peak_h2_ml_min / 1000.0
            out.append(("info", f"Пікове виділення H₂ {fmt(st.peak_h2_ml_min, 1)} мл/хв. Щоб утримати H₂ < 1%, "
                                f"потрібен повітрообмін ≥ {fmt(need_l_min, 1)} л/хв."))
        if st.peak_t_el > 60:
            out.append(("warning", f"Максимальна температура електроліту {fmt(st.peak_t_el, 0)} °C."))
        if self.cell.category == "submerged":
            out.append(("info", "Розрахунок для зануреного катода (Mg–графіт). Не переносьте ці показники на "
                                "Mg-повітряну комірку."))
        return out

    def _phone_verdicts(self) -> list[tuple[str, str]]:
        ph, cfg, st = self.phone, self.sc.phone, self.state
        out = []
        tgt = cfg.soc_target_pct
        max_s = cfg.max_time_h * 3600.0
        need = ph.energy_needed_wh()
        got = ph.ledger.input_j / 3600.0
        if ph.done and ph.t_done_s is not None and ph.t_done_s <= max_s + 1e-6:
            out.append(("ok", f"Телефон заряджено з {cfg.soc_start_pct:.0f}% до {tgt:.0f}% за "
                              f"{format_duration(ph.t_done_s)} (ліміт {format_duration(max_s)})."))
            return out
        if not self.finished:
            out.append(("info", f"Симуляція триває: заряд {fmt(ph.soc * 100, 1)}%."))
            return out
        what = "Повна зарядка неможлива" if tgt >= 99.999 else f"Заряджання до {tgt:.0f}% неможливе"
        out.append(("critical", f"{what} за {format_duration(max_s)}: досягнуто {fmt(ph.soc * 100, 1)}%."))
        out.append(("info", f"Енергія на вході телефона: отримано {fmt(got)} Вт·год, потрібно ≈ {fmt(need)} Вт·год."))
        reason = self.finish_reason
        if reason.startswith("Магній"):
            out.append(("warning", "Причина: магнію недостатньо — пластини вичерпано до завершення заряджання."))
        elif reason.startswith("Електроліт"):
            out.append(("warning", "Причина: " + reason))
        elif self._flags.get("ocv_low", (False,))[0] or self.last_gen_max <= 0:
            out.append(("warning", "Причина: напруга батареї комірок нижча за мінімальну вхідну напругу "
                                   "перетворювача. Додайте послідовні комірки або оберіть інший перетворювач."))
        else:
            p_need = need / cfg.max_time_h
            p_avg = got / max(st.t / 3600.0, 1e-9)
            out.append(("warning", f"Причина: потужності недостатньо. Середня потужність на вході телефона "
                                   f"{fmt(p_avg)} Вт, а для заряджання за {fmt(cfg.max_time_h, 1)} год потрібно "
                                   f"в середньому щонайменше {fmt(p_need)} Вт."))
            if p_avg > 0.05:
                remain_wh = max(0.0, (self.phone.target_soc - ph.soc)) * cfg.battery_wh() / ph.eta
                extra_h = remain_wh / max(p_avg - cfg.self_consumption_w, 1e-6)
                if extra_h < 200:
                    out.append(("info", f"За цієї потужності для досягнення {tgt:.0f}% потрібно ще ≈ "
                                        f"{fmt(extra_h, 1)} год (якщо вистачить магнію)."))
        return out

    def _smartboost_verdicts(self) -> list[tuple[str, str]]:
        d = self.design.supercap
        s = self.smartboost_stats()
        out = [("info", "SmartBoost не створює енергії: він лише накопичує енергію рушія і віддає її пізніше з втратами.")]
        if d.start_delay_s > 0:
            out.append(("info", f"За перші {d.start_delay_s:.0f} с накопичено {fmt(s['sb_e_start_j'], 1)} Дж "
                                f"({fmt(s['sb_e_start_j'] / 3600.0, 4)} Вт·год)."))
        if self.cap:
            cl = self.cap.ledger
            loss = cl.conv_loss_j + cl.esr_loss_j + cl.leak_loss_j
            out.append(("info", f"Через конденсатор пройшло {fmt(cl.bus_out_j, 1)} Дж, втрати конденсатора "
                                f"{fmt(loss, 1)} Дж."))
        depl = s["sb_depleted_at_s"]
        if self.mode == "phone" and self.phone:
            req = self.sc.phone.max_charge_power_w
            gen = s["sb_gen_median_w"]
            if depl is not None and gen < 0.95 * req:
                out.append(("warning", f"Після стартового імпульсу ({format_duration(depl - d.start_delay_s)} після "
                                       f"увімкнення USB-C) конденсатор розрядився. Далі рушій підтримує лише ≈ "
                                       f"{fmt(gen)} Вт замість {fmt(req)} Вт, які бере телефон."))
            elif gen >= 0.95 * req:
                out.append(("ok", "Рушій самостійно підтримує потужність заряджання телефона; конденсатор "
                                  "лише згладжує провали."))
            if self.design.disturbances.enabled:
                out.append(("info", f"Після імпульсу USB-C обмежено згладженою потужністю рушія (τ = "
                                    f"{fmt(self.design.supercap.smoothing_tau_s, 0)} с), "
                                    f"{fmt(self.design.supercap.recharge_share_pct, 0)} % іде на підзаряд конденсатора, "
                                    "а він покриває короткі провали."))
        return out
