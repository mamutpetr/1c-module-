"""Головна сторінка: модель генератора наживо, характеристики, графіки та енергетичний баланс."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QListWidget, QListWidgetItem, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import theme as T
from ...core.design import LOAD_MODES
from ...core.simulator import LEDGER_LABELS
from ...core.units import fmt
from ..widgets.cell_view import CellCrossSection, SystemDiagram
from ..widgets.common import BoundForm, Card, ChartCard, Field, KpiTile, label
from .base import Page, live_values, load_label, safe

S = T.SERIES

MAIN_CHARTS = [
    ("Напруга за часом", "В", [("v_term", "Батарея комірок", S[0], False), ("v_cell", "Одна комірка", S[1], False)]),
    ("Струм за часом", "А", [("i_ext", "Струм", S[0], False)]),
    ("Потужність за часом", "Вт", [("p_term", "Виводи комірок", S[0], False), ("p_usb", "USB-C", S[2], False),
                                    ("p_gen_max", "Доступно від рушія", S[1], True)]),
    ("Вироблені ват-години", "Вт·год", [("e_term_wh", "Виводи комірок", S[0], False), ("e_usb_wh", "USB-C", S[2], False)]),
    ("Маса залишкового магнію", "г", [("mg_remaining_g", "Залишок Mg", S[0], False)]),
    ("Ефективність", "%", [("anode_eff_cum", "Анод (Mg → струм)", S[0], False), ("sys_eff", "Хімія → вихід", S[1], False)]),
    ("Корисне витрачання Mg і самокорозія", "г", [("mg_useful_g", "Корисний струм", S[2], False),
                                                   ("mg_corr_g", "Самокорозія (H₂)", S[1], False),
                                                   ("mg_chunk_g", "Механічні втрати", S[3], False)]),
    ("Запас енергії суперконденсатора", "Дж", [("cap_j", "Енергія", S[3], False)]),
    ("Відсоток заряду телефона", "%", [("phone_soc", "Заряд", S[2], False)]),
]

CHEM_CHARTS = [
    ("Виділення водню", "мл/хв", [("h2_ml_min", "H₂", S[0], False)]),
    ("Концентрація H₂ у корпусі", "%", [("h2_pct", "H₂", S[7], False)]),
    ("Температура електроліту", "°C", [("t_el", "Електроліт", S[1], False)]),
    ("Споживання кисню", "мл/хв", [("o2_ml_min", "O₂", S[2], False)]),
    ("Запас за граничним струмом катода (до 10×)", "×", [("o2_margin", "i_гр / i", S[2], False)]),
    ("Опір пасиваційної плівки", "Ом·см²", [("asr_pass", "Плівка Mg(OH)₂", S[3], False)]),
    ("Опір електроліту в зазорі", "мОм", [("r_el_mohm", "Комірка", S[0], False)]),
    ("Вода і шлам", "%", [("water_pct", "Залишок води", S[0], False), ("sludge_pct", "Шлам Mg(OH)₂", S[1], False)]),
    ("Втрати на самокорозію (еквівалент)", "Вт", [("corr_w", "Корозія", S[1], False)]),
]

LOAD_FIELDS = [
    Field("sim.load_mode", "Навантаження", "choice", choices=tuple(LOAD_MODES.items())),
    Field("sim.usb_power_w", "Потужність USB-C", lo=0.01, hi=100, step=0.5, decimals=2, suffix="Вт"),
    Field("sim.resistor_ohm", "Опір навантаження", lo=0.01, hi=10000, step=0.5, decimals=2, suffix="Ом"),
    Field("sim.current_a", "Струм навантаження", lo=0.0, hi=100, step=0.1, decimals=3, suffix="А"),
    Field("sim.duration_h", "Тривалість симуляції", lo=0.05, hi=500, step=1, decimals=2, suffix="год"),
    Field("sim.dt_s", "Крок моделі", lo=0.2, hi=120, step=1, decimals=1, suffix="с",
          tip="Менший крок точніше відтворює короткі процеси (SmartBoost, провали), але рахує довше."),
]


def build_chart_grid(specs, cols=3, x_label="Час, год", height=170):
    charts = []
    g = QGridLayout()
    g.setSpacing(12)
    for k, (title, unit, sers) in enumerate(specs):
        c = ChartCard(title, unit, x_label=x_label, height=height)
        for key, name, color, dash in sers:
            c.add_series(name, color, dash=dash)
        c.keys = [s[0] for s in sers]
        charts.append(c)
        g.addWidget(c, k // cols, k % cols)
    return g, charts


class DashboardPage(Page):
    title = "Генератор"
    subtitle = "Модель магній-повітряного генератора наживо. Натисніть «Активувати», щоб залити електроліт і запустити реакцію."

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        top = self.responsive(QHBoxLayout(), 1040)
        top.setSpacing(14)
        cell_card = Card("Комірка в розрізі")
        self.cell = CellCrossSection(show_labels=True)
        self.cell.setMinimumHeight(330)
        cell_card.add(self.cell, 1)
        top.addWidget(cell_card, 3)
        right = QVBoxLayout()
        right.setSpacing(12)
        load_card = Card("Режим навантаження")
        self.load_form = BoundForm(LOAD_FIELDS, lambda: self.ctrl.scenario, label_width=120)
        self.load_form.changed.connect(self._load_changed)
        load_card.add(self.load_form)
        self.load_note = label("", "Muted", wrap=True)
        load_card.add(self.load_note)
        right.addWidget(load_card)
        self.kpis = {
            "e_term": KpiTile("Енергія на виводах", "Вт·год", compact=True),
            "e_usb": KpiTile("Енергія USB-C", "Вт·год", compact=True),
            "mg": KpiTile("Mg корисно / корозія", "г", compact=True),
            "eff": KpiTile("Ефективність анода", "%", compact=True),
            "h2": KpiTile("Водень", "мл/хв", compact=True),
            "temp": KpiTile("Електроліт", "°C", compact=True),
        }
        kg = QGridLayout()
        kg.setSpacing(10)
        for k, w in enumerate(self.kpis.values()):
            kg.addWidget(w, k // 2, k % 2)
        right.addLayout(kg)
        right.addStretch(1)
        top.addLayout(right, 2)
        self.body.addLayout(top)

        sys_card = Card("Енергосистема", "Потік енергії від комірок до навантаження. SmartBoost-конденсатор підключено до шини USB-C.")
        self.system = SystemDiagram()
        sys_card.add(self.system)
        self.body.addWidget(sys_card)

        self.tabs = QTabWidget()
        w1 = QWidget()
        g1, self.main_charts = build_chart_grid(MAIN_CHARTS)
        w1.setLayout(g1)
        w2 = QWidget()
        g2, self.chem_charts = build_chart_grid(CHEM_CHARTS)
        w2.setLayout(g2)
        self.tabs.addTab(w1, "Основні графіки")
        self.tabs.addTab(w2, "Хімія і безпека")
        self.tabs.addTab(self._build_balance(), "Енергетичний баланс")
        self.events = QListWidget()
        self.events.setMinimumHeight(300)
        self.tabs.addTab(self.events, "Журнал подій")
        self.tabs.currentChanged.connect(lambda _: self.refresh_live())
        self.body.addWidget(self.tabs)
        ctrl.sim_reset.connect(self._on_reset)
        self._update_load_visibility()

    # ------------------------------------------------------------ баланс
    def _build_balance(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(12)
        card = Card("Куди пішла хімічна енергія магнію",
                    "Базис: оборотна напруга Mg-повітря 3,09 В × заряд розчиненого Mg (корисний струм + корозія + "
                    "механічні втрати). Сума статей дорівнює 100%.")
        self.balance_plot = pg.PlotWidget()
        self.balance_plot.setBackground(T.PANEL)
        self.balance_plot.setMinimumHeight(360)
        pi = self.balance_plot.getPlotItem()
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.showGrid(x=True, y=False, alpha=0.12)
        pi.getAxis("left").setWidth(250)
        pi.getAxis("left").setTextPen(pg.mkPen(T.TEXT_2))
        pi.getAxis("bottom").setTextPen(pg.mkPen(T.MUTED))
        pi.setLabel("bottom", "Вт·год", color=T.MUTED, size="8pt")
        for ax in ("left", "bottom"):
            pi.getAxis(ax).setPen(pg.mkPen(T.BORDER_2))
        card.add(self.balance_plot, 1)
        leg = QHBoxLayout()
        for color, text in ((S[1], "Втрати"), (S[2], "Корисний результат")):
            sw = label("■", "")
            sw.setStyleSheet(f"color: {color};")
            leg.addWidget(sw)
            leg.addWidget(label(text, "Secondary"))
        leg.addStretch(1)
        card.add(leg)
        lay.addWidget(card, 3)
        tcard = Card("Таблиця балансу")
        self.balance_table = QTableWidget(0, 3)
        self.balance_table.setHorizontalHeaderLabels(["Стаття", "Вт·год", "%"])
        self.balance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.balance_table.verticalHeader().setVisible(False)
        self.balance_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tcard.add(self.balance_table, 1)
        self.balance_check = label("", "Muted", wrap=True)
        tcard.add(self.balance_check)
        lay.addWidget(tcard, 2)
        return w

    def _refresh_balance(self, sim) -> None:
        pi = self.balance_plot.getPlotItem()
        pi.clear()
        self.balance_table.setRowCount(0)
        if sim is None or sim.ledger.ideal_j <= 0:
            self.balance_check.setText("")
            return
        br = sim.ledger_breakdown()
        ideal = sim.ledger.ideal_j
        useful = {"stored_j", "usb_load_j", "direct_load_j", "cap_net_j"}
        items = sorted(br.items(), key=lambda kv: kv[1])
        names, vals, colors = [], [], []
        for k, v in items:
            names.append(LEDGER_LABELS.get(k, k))
            vals.append(v / 3600.0)
            colors.append(S[2] if k in useful else S[1])
        ys = np.arange(len(vals))
        for y, v, c in zip(ys, vals, colors):
            bar = pg.BarGraphItem(x0=[0], y=[y], height=0.62, width=[max(v, 0)], brush=pg.mkBrush(c), pen=pg.mkPen(T.PANEL, width=2))
            pi.addItem(bar)
        pi.getAxis("left").setTicks([[(int(y), n) for y, n in zip(ys, names)]])
        pi.setYRange(-0.6, len(vals) - 0.4, padding=0)
        pi.setXRange(0, max(vals) * 1.08 if vals else 1, padding=0)
        rows = sorted(br.items(), key=lambda kv: -kv[1])
        self.balance_table.setRowCount(len(rows) + 1)
        for r, (k, v) in enumerate(rows):
            self.balance_table.setItem(r, 0, QTableWidgetItem(LEDGER_LABELS.get(k, k)))
            self.balance_table.setItem(r, 1, QTableWidgetItem(fmt(v / 3600.0, 3)))
            self.balance_table.setItem(r, 2, QTableWidgetItem(fmt(100 * v / ideal, 1)))
        self.balance_table.setItem(len(rows), 0, QTableWidgetItem("Разом (хімічна енергія Mg)"))
        self.balance_table.setItem(len(rows), 1, QTableWidgetItem(fmt(ideal / 3600.0, 3)))
        self.balance_table.setItem(len(rows), 2, QTableWidgetItem("100,0"))
        worst = max(abs(x) for x in sim.residuals().values())
        self.balance_check.setText(f"Перевірка збереження енергії: найбільший залишок балансових тотожностей "
                                   f"{worst:.1e} Дж ({'OK' if worst < 1e-6 * max(ideal, 1) else 'ПОМИЛКА'}).")

    # ------------------------------------------------------------ події
    def _load_changed(self, path: str) -> None:
        self._update_load_visibility()
        self.ctrl.notify_changed(path)

    def _update_load_visibility(self) -> None:
        mode = self.ctrl.scenario.sim.load_mode
        self.load_form.set_visible("sim.usb_power_w", mode == "usb_power")
        self.load_form.set_visible("sim.resistor_ohm", mode == "resistor")
        self.load_form.set_visible("sim.current_a", mode == "current")
        self.load_form.set_visible("sim.duration_h", mode != "phone")
        notes = {
            "phone": f"Параметри телефона — на сторінці «Смартфон». Тривалість = {fmt(self.ctrl.scenario.phone.max_time_h, 1)} год.",
            "usb_power": "Постійна потужність на виході USB-C через перетворювач.",
            "mppt": "Перетворювач відбирає максимальну доступну потужність.",
            "resistor": "Резистор безпосередньо на виводах батареї комірок (без перетворювача).",
            "current": "Електронне навантаження з постійним струмом (як у лабораторному досліді).",
            "open": "Комірки залиті, але навантаження немає: магній витрачається лише на самокорозію.",
        }
        self.load_note.setText(notes.get(mode, ""))

    def on_scenario_changed(self) -> None:
        self.load_form.load()
        self._update_load_visibility()
        d = self.ctrl.scenario.design
        self.cell.set_design(d)
        self.system.set_design(d, load_label(self.ctrl.scenario.sim.load_mode))
        if self.ctrl.sim is None:
            self.cell.reset_live()
            self.system.set_live({}, False)

    def _on_reset(self) -> None:
        for c in self.main_charts + self.chem_charts:
            c.clear_data()
        self.cell.reset_live()
        self.system.set_live({}, False)
        self.events.clear()
        for k in self.kpis.values():
            k.set("—", "")
        self._refresh_balance(None)

    def refresh_live(self) -> None:
        sim = self.ctrl.sim
        if sim is None:
            return
        vals = live_values(sim)
        self.cell.set_live(vals, self.ctrl.running)
        self.system.set_design(sim.design, load_label(sim.mode))
        self.system.set_live(vals, self.ctrl.running)
        r = sim.rec
        last = r.last
        self.kpis["e_term"].set(fmt(last("e_term_wh"), 2), f"ідеально {fmt(sim.ledger.ideal_j / 3600, 1)} Вт·год")
        self.kpis["e_usb"].set(fmt(last("e_usb_wh"), 2), f"{fmt(last('p_usb'), 2)} Вт зараз")
        self.kpis["mg"].set(f"{fmt(last('mg_useful_g'), 2)} / {fmt(last('mg_corr_g'), 2)}",
                            f"залишок {fmt(last('mg_remaining_g'), 1)} г")
        eff = safe(last("anode_eff_cum"))
        self.kpis["eff"].set(fmt(eff, 1), "накопичена")
        h2pct = safe(last("h2_pct"))
        self.kpis["h2"].set(fmt(last("h2_ml_min"), 2), f"у корпусі {fmt(h2pct, 2)} %",
                            T.CRITICAL if h2pct > 4 else T.WARNING if h2pct > 1 else None)
        te = safe(last("t_el"), 25)
        self.kpis["temp"].set(fmt(te, 1), f"пік {fmt(sim.state.peak_t_el, 1)} °C", T.WARNING if te > 60 else None)
        idx = self.tabs.currentIndex()
        t = r.get("t_h")
        if idx == 0:
            charts = self.main_charts
        elif idx == 1:
            charts = self.chem_charts
        else:
            charts = []
        for c in charts:
            for k, key in enumerate(c.keys):
                c.set_data(k, t, r.get(key))
        if idx == 2:
            self._refresh_balance(sim)
        if self.events.count() != len(sim.events):
            self.events.clear()
            for e in sim.events:
                hh = int(e.t_s // 3600)
                mm = int((e.t_s % 3600) // 60)
                ss = int(e.t_s % 60)
                it = QListWidgetItem(f"{hh:02d}:{mm:02d}:{ss:02d}   {T.LEVEL_ICONS.get(e.level, '•')}  {e.text}")
                it.setForeground(QColor(T.LEVEL_COLORS.get(e.level, T.TEXT_2)))
                self.events.addItem(it)
            self.events.scrollToBottom()
