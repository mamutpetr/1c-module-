"""SmartBoost: попереднє накопичення енергії в суперконденсаторі та згладжування провалів."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QHeaderView, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout

from .. import theme as T
from ...core.units import fmt
from ..widgets.common import BoundForm, Card, ChartCard, Field, KpiTile, VerdictList, label
from .base import Page

S = T.SERIES

CAP_FIELDS = [
    Field("design.supercap.enabled", "SmartBoost увімкнено", "bool"),
    Field("design.supercap.start_delay_s", "Час запуску USB-C", lo=0, hi=300, step=5, decimals=0, suffix="с"),
    Field("design.supercap.capacitance_f", "Ємність конденсатора", lo=0.1, hi=3000, step=1, decimals=1, suffix="Ф"),
    Field("design.supercap.v_max", "Допустима напруга", lo=0.5, hi=60, step=0.1, decimals=2, suffix="В"),
    Field("design.supercap.v_min", "Мінімальна напруга розряду", lo=0.0, hi=59, step=0.1, decimals=2, suffix="В",
          tip="Нижче цієї напруги розрядний DC/DC не працює: енергія нижче неї недоступна."),
    Field("design.supercap.v_initial", "Початкова напруга", lo=0.0, hi=60, step=0.1, decimals=2, suffix="В"),
    Field("design.supercap.esr_mohm", "Внутрішній опір (ESR)", lo=0, hi=5000, step=5, decimals=0, suffix="мОм"),
    Field("design.supercap.leakage_ua", "Струм витоку", lo=0, hi=100000, step=10, decimals=0, suffix="мкА"),
    Field("design.supercap.eta_charge_pct", "ККД зарядного DC/DC", lo=10, hi=100, step=1, decimals=1, suffix="%"),
    Field("design.supercap.eta_discharge_pct", "ККД розрядного DC/DC", lo=10, hi=100, step=1, decimals=1, suffix="%"),
    Field("design.supercap.i_max_a", "Максимальний струм", lo=0.01, hi=100, step=0.5, decimals=2, suffix="А"),
    Field("design.supercap.p_charge_max_w", "Макс. потужність заряду", lo=0.01, hi=200, step=0.5, decimals=2, suffix="Вт"),
    Field("design.supercap.p_discharge_max_w", "Макс. потужність розряду", lo=0.01, hi=200, step=0.5, decimals=2, suffix="Вт"),
    Field("design.supercap.smoothing_tau_s", "Згладжування потужності USB (τ)", lo=1, hi=3600, step=10, decimals=0, suffix="с",
          tip="Після стартового імпульсу USB-C обмежено ковзним середнім доступної потужності рушія."),
    Field("design.supercap.recharge_share_pct", "Частка на підзаряд конденсатора", lo=0, hi=90, step=1, decimals=0, suffix="%"),
    Field("design.supercap.soc_target_pct", "Цільовий заряд конденсатора", lo=0, hi=100, step=5, decimals=0, suffix="%"),
]

DIST_FIELDS = [
    Field("design.disturbances.enabled", "Короткочасні провали рушія", "bool",
          tip="Тестовий сценарій: бульбашки H₂ чи перекриття повітря тимчасово зменшують активну площу."),
    Field("design.disturbances.mean_interval_s", "Середній інтервал між провалами", lo=10, hi=36000, step=30, decimals=0, suffix="с"),
    Field("design.disturbances.duration_s", "Тривалість провалу", lo=1, hi=600, step=1, decimals=0, suffix="с"),
    Field("design.disturbances.depth_pct", "Глибина (заблокована площа)", lo=1, hi=95, step=5, decimals=0, suffix="%"),
    Field("design.disturbances.seed", "Зерно генератора випадкових чисел", "int", lo=0, hi=999999),
]


class SmartBoostPage(Page):
    title = "SmartBoost"
    subtitle = ("Генератор вмикається, перші секунди телефон не підключений, енергія накопичується в суперконденсаторі, "
                "потім вмикається USB-C. SmartBoost не створює енергії: він лише переносить її в часі з втратами.")

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        b_live = QPushButton("▶  Запустити SmartBoost")
        b_live.setObjectName("Primary")
        b_live.clicked.connect(self._live)
        b_fast = QPushButton("⏭  Розрахувати одразу")
        b_fast.clicked.connect(self._fast)
        self.head_actions.addWidget(b_live)
        self.head_actions.addWidget(b_fast)
        top = self.responsive(QHBoxLayout(), 1000)
        top.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        fc = Card("Суперконденсатор")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 300)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(30)
        self.slider_label = label("", "Secondary")
        sl = QHBoxLayout()
        sl.addWidget(label("Запуск USB-C:", "Secondary"))
        sl.addWidget(self.slider, 1)
        sl.addWidget(self.slider_label)
        fc.add(sl)
        self.slider.valueChanged.connect(self._slider)
        self.form = BoundForm(CAP_FIELDS, lambda: self.ctrl.scenario, label_width=170)
        self.form.changed.connect(self._changed)
        fc.add(self.form)
        self.cap_info = label("", "Muted", wrap=True)
        fc.add(self.cap_info)
        left.addWidget(fc)
        dc = Card("Провали потужності (тестовий сценарій)")
        self.dist = BoundForm(DIST_FIELDS, lambda: self.ctrl.scenario, label_width=170)
        self.dist.changed.connect(self._changed)
        dc.add(self.dist)
        left.addWidget(dc)
        left.addStretch(1)
        top.addLayout(left, 2)
        right = QVBoxLayout()
        right.setSpacing(12)
        self.kpi = {
            "e30": KpiTile("Накопичено до запуску", "Дж"),
            "peak": KpiTile("Пік USB-C", "Вт"),
            "gen": KpiTile("Рушій після імпульсу", "Вт"),
            "loss": KpiTile("Втрати конденсатора", "Дж"),
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
        self.c_cap = ChartCard("Накопичена енергія суперконденсатора", "Дж", x_label="Час, хв", height=170)
        self.c_cap.add_series("Енергія", S[3])
        self.c_gen = ChartCard("Потужність рушія", "Вт", x_label="Час, хв", height=170)
        self.c_gen.add_series("Віддає рушій", S[0])
        self.c_gen.add_series("Може дати рушій", S[1], dash=True)
        self.c_usb = ChartCard("Потужність USB-C", "Вт", x_label="Час, хв", height=170)
        self.c_usb.add_series("USB-C", S[2])
        for c in (self.c_cap, self.c_gen, self.c_usb):
            right.addWidget(c)
        top.addLayout(right, 3)
        self.body.addLayout(top)
        bc = Card("Енергетичний баланс суперконденсатора",
                  "Отримано з шини − віддано в шину − втрати DC/DC − втрати ESR − витік = зміна запасу.")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Стаття", "Дж"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(260)
        bc.add(self.table)
        self.body.addWidget(bc)
        ctrl.sim_reset.connect(self._clear)

    def _slider(self, v: int) -> None:
        self.slider_label.setText(f"{v} с")
        if int(self.ctrl.scenario.design.supercap.start_delay_s) != v:
            self.ctrl.scenario.design.supercap.start_delay_s = float(v)
            self.form.load()
            self.ctrl.notify_changed("design.supercap.start_delay_s")

    def _changed(self, path: str) -> None:
        self._sync()
        self.ctrl.notify_changed(path)

    def _sync(self) -> None:
        sc = self.ctrl.scenario.design.supercap
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(sc.start_delay_s)))
        self.slider.blockSignals(False)
        self.slider_label.setText(f"{int(round(sc.start_delay_s))} с")
        e_max = 0.5 * sc.capacitance_f * sc.v_max ** 2
        e_use = 0.5 * sc.capacitance_f * (sc.v_max ** 2 - min(sc.v_min, sc.v_max) ** 2)
        self.cap_info.setText(f"Повний запас ½CV² = {fmt(e_max, 0)} Дж ({fmt(e_max / 3600, 3)} Вт·год), доступно до "
                              f"мінімальної напруги {fmt(e_use, 0)} Дж. Для порівняння: заряд телефона 19 Вт·год = 69 300 Дж.")

    def _prepare(self) -> None:
        sc = self.ctrl.scenario
        changed = False
        if not sc.design.supercap.enabled:
            sc.design.supercap.enabled = True
            changed = True
        if sc.sim.load_mode not in ("phone", "usb_power", "mppt"):
            sc.sim.load_mode = "phone"
            changed = True
        if changed:
            self.form.load()
            self.ctrl.notify_changed("design.supercap.enabled")

    def _live(self) -> None:
        self._prepare()
        self.ctrl.set_speed(10)
        self.ctrl.restart()

    def _fast(self) -> None:
        self._prepare()
        self.ctrl.reset()
        self.ctrl.run_to_end()

    def on_scenario_changed(self) -> None:
        self.form.load()
        self.dist.load()
        self._sync()

    def _clear(self) -> None:
        for c in (self.c_cap, self.c_gen, self.c_usb):
            c.clear_data()
        for k in self.kpi.values():
            k.set("—", "")
        self.verdict.set_items([])
        self.table.setRowCount(0)

    def refresh_live(self) -> None:
        sim = self.ctrl.sim
        if sim is None:
            return
        r = sim.rec
        t = r.get("t_h") * 60.0
        self.c_cap.set_data(0, t, r.get("cap_j"))
        self.c_gen.set_data(0, t, r.get("p_gen_bus"))
        self.c_gen.set_data(1, t, r.get("p_gen_max"))
        self.c_usb.set_data(0, t, r.get("p_usb"))
        if sim.cap is None:
            self.verdict.set_items([("info", "У поточній симуляції суперконденсатор не задіяний. "
                                             "Натисніть «Запустити SmartBoost».")])
            return
        st = sim.smartboost_stats()
        cl = sim.cap.ledger
        self.kpi["e30"].set(fmt(st["sb_e_start_j"], 1), f"{fmt(st['sb_e_start_j'] / 3600, 4)} Вт·год")
        self.kpi["peak"].set(fmt(st["sb_peak_usb_w"], 2))
        self.kpi["gen"].set(fmt(st["sb_gen_median_w"], 2), "медіана доступної потужності")
        loss = cl.conv_loss_j + cl.esr_loss_j + cl.leak_loss_j
        self.kpi["loss"].set(fmt(loss, 1), f"ККД циклу {fmt(100 * cl.bus_out_j / cl.bus_in_j, 0) if cl.bus_in_j > 0 else '—'} %")
        self.verdict.set_items(sim.verdicts())
        rows = [("Початковий запас", cl.initial_j), ("Отримано з шини (заряд)", cl.bus_in_j),
                ("Віддано в шину (розряд)", -cl.bus_out_j), ("Втрати зарядного/розрядного DC/DC", -cl.conv_loss_j),
                ("Втрати на ESR", -cl.esr_loss_j), ("Витік", -cl.leak_loss_j), ("Поточний запас", sim.cap.e),
                ("Залишок балансу (має бути ≈ 0)", sim.cap.balance_residual_j())]
        self.table.setRowCount(len(rows))
        for k, (name, v) in enumerate(rows):
            self.table.setItem(k, 0, QTableWidgetItem(name))
            self.table.setItem(k, 1, QTableWidgetItem(f"{v:.2e}" if "Залишок" in name else fmt(v, 2)))
