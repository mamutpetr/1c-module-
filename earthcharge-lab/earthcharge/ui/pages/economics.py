"""Бізнес-калькулятор картриджів. Фінанси відокремлені від фізики: фізичні величини або беруться
з окремої симуляції заряджання, або вводяться вручну."""
from __future__ import annotations


import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import theme as T
from ...core.design import clone
from ...core.economics import LINE_LABELS, compare_cartridges, physics_from_simulation
from ...core.simulator import Simulation
from ...core.units import fmt
from ..widgets.common import BoundForm, Card, Field, label
from .base import Page

S = T.SERIES

PRICE_FIELDS = [
    Field("prices.mg_price_per_kg", "Магній (лист), за кг", lo=0, hi=1e6, step=10, decimals=2),
    Field("prices.cathode_price_per_cm2", "Повітряний катод, за см²", lo=0, hi=1000, step=0.05, decimals=3),
    Field("prices.cathode_location", "Де катод", "choice", choices=(("device", "у пристрої (багаторазовий)"), ("cartridge", "у картриджі"))),
    Field("prices.cathode_life_charges", "Ресурс катода в пристрої", lo=1, hi=10000, step=10, decimals=0, suffix="заряджань"),
    Field("prices.separator_price_per_cm2", "Сепаратор, за см²", lo=0, hi=100, step=0.01, decimals=3),
    Field("prices.salt_price_per_kg", "Сіль для електроліту, за кг", lo=0, hi=1e5, step=1, decimals=2),
    Field("prices.electrolyte_pack_per_activation", "Пакування електроліту, за активацію", lo=0, hi=1e4, step=0.5, decimals=2),
    Field("prices.housing_base", "Корпус картриджа", lo=0, hi=1e5, step=1, decimals=2),
    Field("prices.housing_extra_per_charge", "Корпус: + за кожне додаткове заряджання", lo=0, hi=1e4, step=0.5, decimals=2),
    Field("prices.contacts_cost", "Контакти", lo=0, hi=1e4, step=0.5, decimals=2),
    Field("prices.assembly_cost", "Виробництво / складання", lo=0, hi=1e5, step=1, decimals=2),
    Field("prices.packaging_cost", "Упаковка", lo=0, hi=1e4, step=0.5, decimals=2),
    Field("prices.logistics_per_unit", "Логістика на одиницю", lo=0, hi=1e4, step=0.5, decimals=2),
    Field("prices.overhead_pct", "Накладні витрати", lo=0, hi=300, step=1, decimals=1, suffix="%"),
    Field("prices.defect_pct", "Брак", lo=0, hi=90, step=0.5, decimals=1, suffix="%"),
    Field("prices.target_margin_pct", "Цільова валова маржа", lo=0, hi=95, step=1, decimals=1, suffix="%"),
    Field("prices.vat_pct", "ПДВ у роздрібній ціні", lo=0, hi=50, step=1, decimals=1, suffix="%"),
    Field("prices.reserve_pct", "Запас магнію", lo=0, hi=200, step=5, decimals=0, suffix="%"),
    Field("prices.electrolyte_drained", "Електроліт зливають після кожного заряджання", "bool"),
    Field("prices.hours_between_charges", "Інтервал між заряджаннями", lo=0, hi=10000, step=6, decimals=0, suffix="год"),
]

PHYS_FIELDS = [
    Field("phys_manual.mg_per_charge_g", "Mg на одне заряджання", lo=0.01, hi=1e5, step=0.5, decimals=2, suffix="г"),
    Field("phys_manual.usb_wh_per_charge", "Енергія USB-C на заряджання", lo=0.01, hi=1e5, step=0.5, decimals=2, suffix="Вт·год"),
    Field("phys_manual.anode_area_total_cm2", "Площа анодів усього", lo=0, hi=1e6, step=10, decimals=0, suffix="см²"),
    Field("phys_manual.cathode_area_total_cm2", "Площа катодів усього", lo=0, hi=1e6, step=10, decimals=0, suffix="см²"),
    Field("phys_manual.electrolyte_ml_per_activation", "Електроліт на активацію", lo=0, hi=1e6, step=10, decimals=0, suffix="мл"),
    Field("phys_manual.salt_wt_pct", "Концентрація солі", lo=0, hi=40, step=0.5, decimals=1, suffix="%"),
    Field("phys_manual.max_utilization", "Допустиме використання Mg", lo=1, hi=100, step=1, decimals=0, suffix="%", scale=100.0),
    Field("phys_manual.idle_corrosion_g_per_h", "Самокорозія без навантаження", lo=0, hi=1000, step=0.01, decimals=4, suffix="г/год"),
]


class EconomicsPage(Page):
    title = "Економіка картриджів"
    subtitle = ("Собівартість, рекомендована ціна й маржа для картриджів на 1, 3 і 5 заряджань. Ціни за замовчуванням — "
                "лише приклад: замініть їх на реальні пропозиції постачальників.")
    uses_param_panel = False

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        self.phys_sim = None
        top = self.responsive(QHBoxLayout(), 1000)
        top.setSpacing(14)
        pc = Card("Ціни та витрати")
        cur = QHBoxLayout()
        cur.addWidget(label("Валюта", "Secondary"))
        self.currency = QLineEdit(self.ctrl.prices.currency)
        self.currency.setMaximumWidth(90)
        self.currency.editingFinished.connect(self._currency)
        cur.addWidget(self.currency)
        cur.addStretch(1)
        pc.add(cur)
        self.prices_form = BoundForm(PRICE_FIELDS, lambda: self.ctrl, label_width=220)
        self.prices_form.changed.connect(lambda _: self.recalc())
        pc.add(self.prices_form)
        top.addWidget(pc, 2)
        right = QVBoxLayout()
        right.setSpacing(12)
        fc = Card("Фізичні вхідні дані", "Єдиний зв'язок з фізикою. Фінансова модель не змінює фізичних розрахунків.")
        src = QHBoxLayout()
        self.r_sim = QRadioButton("із симуляції заряджання поточної конструкції")
        self.r_man = QRadioButton("вручну")
        self.r_sim.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.r_sim)
        g.addButton(self.r_man)
        self.r_sim.toggled.connect(lambda _: self.recalc())
        src.addWidget(self.r_sim)
        src.addWidget(self.r_man)
        src.addStretch(1)
        fc.add(src)
        b = QPushButton("↻  Оновити з фізичної моделі")
        b.clicked.connect(self.update_physics)
        fc.add(b)
        self.phys_info = label("", "Secondary", wrap=True)
        fc.add(self.phys_info)
        self.phys_form = BoundForm(PHYS_FIELDS, lambda: self.ctrl, label_width=220)
        self.phys_form.changed.connect(lambda _: self.recalc())
        fc.add(self.phys_form)
        right.addWidget(fc)
        top.addLayout(right, 3)
        self.body.addLayout(top)
        rc = Card("Порівняння картриджів")
        self.table = QTableWidget(0, 4)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(560)
        rc.add(self.table)
        self.body.addWidget(rc)
        cc = Card("Вартість одного заряджання", "Для покупця (роздрібна ціна / кількість заряджань) і собівартість на одне заряджання.")
        leg = QHBoxLayout()
        for color, text in ((S[0], "Для покупця"), (S[2], "Собівартість")):
            sw = label("■", "")
            sw.setStyleSheet(f"color: {color};")
            leg.addWidget(sw)
            leg.addWidget(label(text, "Secondary"))
        leg.addStretch(1)
        cc.add(leg)
        self.bar = pg.PlotWidget()
        self.bar.setBackground(T.PANEL)
        self.bar.setMinimumHeight(260)
        pi = self.bar.getPlotItem()
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.showGrid(x=False, y=True, alpha=0.12)
        for ax in ("left", "bottom"):
            pi.getAxis(ax).setPen(pg.mkPen(T.BORDER_2))
            pi.getAxis(ax).setTextPen(pg.mkPen(T.MUTED))
        cc.add(self.bar)
        self.body.addWidget(cc)

    def _currency(self) -> None:
        self.ctrl.prices.currency = self.currency.text().strip() or "грн"
        self.recalc()

    def update_physics(self) -> None:
        sc = clone(self.ctrl.scenario)
        sc.sim.load_mode = "phone"
        sc.sim.dt_s = max(10.0, sc.sim.dt_s)

        def job(progress, cancel):
            sim = Simulation(sc)
            sim.run(progress=progress, cancel=cancel)
            return sim

        self.ctrl.run_job("Фізичний розрахунок для економіки…", job, self._phys_done)

    def _phys_done(self, sim) -> None:
        self.phys_sim = sim
        self.recalc()

    def physics(self):
        if self.r_sim.isChecked() and self.phys_sim is not None:
            return physics_from_simulation(self.phys_sim)
        return self.ctrl.phys_manual

    def recalc(self) -> None:
        manual = self.r_man.isChecked()
        self.phys_form.setEnabled(manual)
        phys = self.physics()
        cur = self.ctrl.prices.currency
        if self.r_sim.isChecked():
            if self.phys_sim is None:
                self.phys_info.setText("Натисніть «Оновити з фізичної моделі» або оберіть ручне введення. Поки що "
                                       "використано ручні значення.")
            else:
                s = self.phys_sim.summary()
                ok = s.get("phone_done")
                self.phys_info.setText(
                    f"{phys.source}. Mg на заряджання: {fmt(phys.mg_per_charge_g, 2)} г, USB-C: {fmt(phys.usb_wh_per_charge, 2)} Вт·год, "
                    f"самокорозія без навантаження: {fmt(phys.idle_corrosion_g_per_h, 4)} г/год."
                    + ("" if ok else f" <span style='color:{T.WARNING}'>Увага: телефон не заряджено повністю — "
                                     f"картридж не забезпечує повне заряджання.</span>"))
        else:
            self.phys_info.setText(f"Ручні значення: {phys.source}.")
        try:
            res = compare_cartridges(phys, self.ctrl.prices)
        except ValueError as exc:
            self.phys_info.setText(str(exc))
            return
        self.table.setColumnCount(1 + len(res))
        self.table.setHorizontalHeaderLabels(["Показник"] + [f"Картридж на {r.charges} заряд." for r in res])
        rows = [("Маса магнію в картриджі, г", [fmt(r.mg_mass_g, 1) for r in res])]
        for key, lbl in LINE_LABELS.items():
            rows.append((f"{lbl}, {cur}", [fmt(r.lines[key], 2) for r in res]))
        rows += [
            (f"Собівартість (COGS), {cur}", [fmt(r.cogs, 2) for r in res]),
            (f"Рекомендована відпускна ціна без ПДВ, {cur}", [fmt(r.price_net, 2) for r in res]),
            (f"Роздрібна ціна з ПДВ, {cur}", [fmt(r.price_retail, 2) for r in res]),
            ("Валова маржа, %", [fmt(r.gross_margin_pct, 1) for r in res]),
            (f"Валовий прибуток з картриджа, {cur}", [fmt(r.gross_profit, 2) for r in res]),
            (f"Вартість одного заряджання для покупця, {cur}", [fmt(r.cost_per_charge_customer, 2) for r in res]),
            (f"Собівартість одного заряджання, {cur}", [fmt(r.cogs_per_charge, 2) for r in res]),
            (f"Ціна за 1 Вт·год для покупця, {cur}", [fmt(r.price_per_wh, 2) for r in res]),
        ]
        self.table.setRowCount(len(rows))
        for i, (name, vals) in enumerate(rows):
            it = QTableWidgetItem(name)
            self.table.setItem(i, 0, it)
            for j, v in enumerate(vals):
                self.table.setItem(i, j + 1, QTableWidgetItem(v))
        pi = self.bar.getPlotItem()
        pi.clear()
        x = np.arange(len(res))
        w = 0.36
        pi.addItem(pg.BarGraphItem(x=x - w / 2 - 0.01, height=[r.cost_per_charge_customer for r in res], width=w,
                                   brush=pg.mkBrush(S[0]), pen=pg.mkPen(T.PANEL, width=2)))
        pi.addItem(pg.BarGraphItem(x=x + w / 2 + 0.01, height=[r.cogs_per_charge for r in res], width=w,
                                   brush=pg.mkBrush(S[2]), pen=pg.mkPen(T.PANEL, width=2)))
        pi.getAxis("bottom").setTicks([[(k, f"{r.charges} заряд.") for k, r in enumerate(res)]])
        pi.setLabel("left", cur, color=T.MUTED, size="8pt")
        top = max([r.cost_per_charge_customer for r in res] + [1e-9])
        pi.setYRange(0, top * 1.15, padding=0)
        pi.setXRange(-0.6, len(res) - 0.4, padding=0)
        for k, r in enumerate(res):
            t1 = pg.TextItem(fmt(r.cost_per_charge_customer, 1), color=T.TEXT_2, anchor=(0.5, 1.1))
            t1.setPos(k - w / 2, r.cost_per_charge_customer)
            pi.addItem(t1)

    def on_shown(self) -> None:
        self.currency.setText(self.ctrl.prices.currency)
        self.prices_form.load()
        self.phys_form.load()
        if self.phys_sim is None and self.ctrl.forecast is not None and self.ctrl.forecast.mode == "phone":
            self.phys_sim = self.ctrl.forecast
        self.recalc()

    def on_scenario_changed(self) -> None:
        self.prices_form.load()
        self.phys_form.load()
        self.recalc()
