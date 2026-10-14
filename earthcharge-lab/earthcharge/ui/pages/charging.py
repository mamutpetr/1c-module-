"""Режим «Зарядити смартфон»."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from .. import theme as T
from ...core.design import has_errors, validate_phone
from ...core.phone import PhoneBattery
from ...core.units import format_duration, fmt
from ..widgets.common import BoundForm, Card, ChartCard, Field, KpiTile, VerdictList, label
from .base import Page

S = T.SERIES

PHONE_FIELDS = [
    Field("phone.spec_mode", "Задати акумулятор", "choice", choices=(("mah", "ємністю (мА·год) і напругою"), ("wh", "енергією (Вт·год)"))),
    Field("phone.capacity_mah", "Ємність", lo=100, hi=50000, step=100, decimals=0, suffix="мА·год"),
    Field("phone.nominal_v", "Номінальна напруга", lo=1, hi=20, step=0.05, decimals=2, suffix="В"),
    Field("phone.energy_wh", "Енергія акумулятора", lo=0.5, hi=200, step=0.5, decimals=2, suffix="Вт·год"),
    Field("phone.soc_start_pct", "Поточний заряд", lo=0, hi=99, step=5, decimals=0, suffix="%"),
    Field("phone.soc_target_pct", "Бажаний заряд", lo=1, hi=100, step=5, decimals=0, suffix="%"),
    Field("phone.max_charge_power_w", "Потужність заряджання (макс.)", lo=0.2, hi=100, step=0.5, decimals=1, suffix="Вт"),
    Field("phone.max_time_h", "Час на заряджання", lo=0.25, hi=48, step=0.5, decimals=2, suffix="год"),
    Field("design.converter.efficiency_pct", "ККД перетворювача", lo=10, hi=100, step=1, decimals=1, suffix="%"),
    Field("phone.charge_efficiency_pct", "ККД заряджання телефона", lo=10, hi=100, step=1, decimals=0, suffix="%",
          tip="Частка вхідної енергії USB, що потрапляє в акумулятор (контролер, нагрів)."),
    Field("phone.self_consumption_w", "Споживання самого телефона", lo=0, hi=10, step=0.05, decimals=2, suffix="Вт"),
    Field("phone.cv_start_pct", "Початок зниження потужності (CV)", lo=0, hi=99, step=1, decimals=0, suffix="%"),
    Field("phone.taper_floor_pct", "Потужність наприкінці, % від макс.", lo=1, hi=100, step=1, decimals=0, suffix="%"),
    Field("phone.min_input_w", "Мінімальна потужність для заряджання", lo=0, hi=10, step=0.1, decimals=2, suffix="Вт"),
    Field("phone.cable_resistance_mohm", "Опір кабелю USB", lo=0, hi=2000, step=10, decimals=0, suffix="мОм"),
]


class ChargingPage(Page):
    title = "Зарядити смартфон"
    subtitle = ("Заряджання телефона від генератора через USB-C. Профіль CC/CV — оціночна модель: реальні телефони "
                "змінюють потужність залежно від температури й контролера.")

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        b_live = QPushButton("▶  Зарядити смартфон")
        b_live.setObjectName("Primary")
        b_live.clicked.connect(self._live)
        b_fast = QPushButton("⏭  Розрахувати одразу")
        b_fast.clicked.connect(self._fast)
        self.head_actions.addWidget(b_live)
        self.head_actions.addWidget(b_fast)
        top = self.responsive(QHBoxLayout(), 1000)
        top.setSpacing(14)
        fc = Card("Телефон і заряджання")
        self.form = BoundForm(PHONE_FIELDS, lambda: self.ctrl.scenario, label_width=170)
        self.form.changed.connect(self._changed)
        fc.add(self.form)
        self.need = label("", "Secondary", wrap=True)
        fc.add(self.need)
        top.addWidget(fc, 2)
        right = QVBoxLayout()
        right.setSpacing(12)
        self.kpi = {
            "soc": KpiTile("Заряд телефона", "%"),
            "time": KpiTile("Час до цілі", ""),
            "usb": KpiTile("Енергія USB-C", "Вт·год"),
            "mg": KpiTile("Витрачено Mg", "г"),
        }
        kg = QGridLayout()
        kg.setSpacing(10)
        for k, w in enumerate(self.kpi.values()):
            kg.addWidget(w, 0, k)
        right.addLayout(kg)
        vc = Card("Висновок")
        self.verdict = VerdictList()
        vc.add(self.verdict)
        right.addWidget(vc)
        self.c_soc = ChartCard("Заряд телефона від 0 до 100%", "%", height=230)
        self.c_soc.add_series("Заряд", S[2])
        self.c_soc.add_series("Ціль", S[3], dash=True)
        self.c_soc.pw.setYRange(0, 100)
        right.addWidget(self.c_soc)
        top.addLayout(right, 3)
        self.body.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.c_p = ChartCard("Потужність: телефон бере / рушій може дати", "Вт", height=210)
        self.c_p.add_series("USB-C", S[0])
        self.c_p.add_series("Доступно від рушія", S[1], dash=True)
        self.c_e = ChartCard("Енергія", "Вт·год", height=210)
        self.c_e.add_series("USB-C", S[0])
        self.c_e.add_series("Виводи комірок", S[2])
        row.addWidget(self.c_p)
        row.addWidget(self.c_e)
        self.body.addLayout(row)
        ctrl.sim_reset.connect(self._clear)

    def _changed(self, path: str) -> None:
        self._update_visibility()
        self._update_need()
        self.ctrl.notify_changed(path)

    def _update_visibility(self) -> None:
        mah = self.ctrl.scenario.phone.spec_mode == "mah"
        self.form.set_visible("phone.capacity_mah", mah)
        self.form.set_visible("phone.nominal_v", mah)
        self.form.set_visible("phone.energy_wh", not mah)

    def _update_need(self) -> None:
        ph = self.ctrl.scenario.phone
        issues = validate_phone(ph)
        if has_errors(issues):
            self.need.setText("⚠ " + "; ".join(i.message for i in issues if i.level == "error"))
            return
        pb = PhoneBattery(ph)
        need = pb.energy_needed_wh()
        tmin = pb.min_charge_time_h()
        self.need.setText(
            f"Акумулятор: {fmt(ph.battery_wh(), 2)} Вт·год. Для {fmt(ph.soc_start_pct, 0)} → {fmt(ph.soc_target_pct, 0)} % "
            f"потрібно ≈ {fmt(need, 2)} Вт·год на вході телефона, тобто в середньому ≥ {fmt(need / ph.max_time_h, 2)} Вт "
            f"протягом {fmt(ph.max_time_h, 1)} год. Навіть від ідеального джерела з обмеженням {fmt(ph.max_charge_power_w, 1)} Вт "
            f"заряджання триває ≈ {fmt(tmin, 1)} год.")

    def _prepare(self) -> bool:
        if has_errors(validate_phone(self.ctrl.scenario.phone)):
            self.ctrl.message.emit("critical", "Виправте параметри телефона.")
            return False
        if self.ctrl.scenario.sim.load_mode != "phone":
            self.ctrl.scenario.sim.load_mode = "phone"
            self.ctrl.notify_changed("sim.load_mode")
        return True

    def _live(self) -> None:
        if self._prepare():
            self.ctrl.restart()

    def _fast(self) -> None:
        if self._prepare():
            self.ctrl.reset()
            self.ctrl.run_to_end()

    def on_scenario_changed(self) -> None:
        self.form.load()
        self._update_visibility()
        self._update_need()

    def _clear(self) -> None:
        for c in (self.c_soc, self.c_p, self.c_e):
            c.clear_data()
        for k in self.kpi.values():
            k.set("—", "")
        self.verdict.set_items([])

    def refresh_live(self) -> None:
        sim = self.ctrl.sim
        if sim is None:
            return
        if sim.mode != "phone":
            self.verdict.set_items([("info", "Поточна симуляція не в режимі смартфона. Натисніть «Зарядити смартфон».")])
            return
        r = sim.rec
        t = r.get("t_h")
        self.c_soc.set_data(0, t, r.get("phone_soc"))
        tgt = sim.sc.phone.soc_target_pct
        self.c_soc.set_data(1, [0, sim.duration_s / 3600.0], [tgt, tgt])
        self.c_p.set_data(0, t, r.get("p_usb"))
        self.c_p.set_data(1, t, r.get("p_gen_max"))
        self.c_e.set_data(0, t, r.get("e_usb_wh"))
        self.c_e.set_data(1, t, r.get("e_term_wh"))
        ph = sim.phone
        self.kpi["soc"].set(fmt(ph.soc * 100, 1), f"ціль {fmt(tgt, 0)} %", T.GOOD if ph.done else None)
        if ph.done and ph.t_done_s is not None:
            self.kpi["time"].set(format_duration(ph.t_done_s), "досягнуто", T.GOOD)
        else:
            self.kpi["time"].set("—" if not sim.finished else "не досягнуто", f"ліміт {format_duration(sim.duration_s)}",
                                 T.CRITICAL if sim.finished else None)
        self.kpi["usb"].set(fmt(r.last("e_usb_wh"), 2), f"потрібно ≈ {fmt(ph.energy_needed_wh(), 1)}")
        self.kpi["mg"].set(fmt(sim.mg_consumed_cell_g() * sim.n, 2), f"з них корозія {fmt(sim.state.mg_corr_g * sim.n, 2)} г")
        self.verdict.set_items(sim.verdicts())
