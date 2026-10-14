"""Порівняння двох варіантів конструкції поруч."""
from __future__ import annotations

import math

from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem)

from .. import theme as T
from ...core.analysis import analyze
from ...core.design import clone
from ...core.scenarios import load_scenario
from ...core.simulator import Simulation
from ...core.units import format_duration, fmt
from ..controller import SCENARIO_DIR
from ..widgets.common import Card, ChartCard, label
from .base import Page

S = T.SERIES
COLORS = {"A": S[0], "B": S[1]}

CHARTS = [
    ("Напруга батареї комірок", "В", "v_term"),
    ("Потужність на виході", "Вт", "_out"),
    ("Енергія на виході", "Вт·год", "_e_out"),
    ("Залишок магнію", "г", "mg_remaining_g"),
    ("Ефективність анода (накопичена)", "%", "anode_eff_cum"),
    ("Заряд телефона", "%", "phone_soc"),
]

METRICS = [
    ("Комірок (S × P)", lambda s, sim: f"{sim.geo.n_series} × {sim.geo.n_parallel}", None),
    ("Пластина, мм", lambda s, sim: f"{fmt(sim.design.geometry.plate_length_mm, 0)} × {fmt(sim.design.geometry.plate_width_mm, 0)} × {fmt(sim.geo.thickness_mm, 2)}", None),
    ("Маса Mg, г", lambda s, sim: s["mg_initial_g"], 1),
    ("Енергія на виході, Вт·год", lambda s, sim: s["e_out_wh"], 2),
    ("Середня потужність на виході, Вт", lambda s, sim: s["p_avg_out_w"], 2),
    ("Витрачено Mg, г", lambda s, sim: s["mg_consumed_g"], 2),
    ("  з них самокорозія, г", lambda s, sim: s["mg_corr_g"], 2),
    ("Ефективність анода, %", lambda s, sim: s["anode_eff_pct"], 1),
    ("Вт·год на грам Mg (вихід)", lambda s, sim: s["wh_per_g_out"], 2),
    ("Загальна ефективність хімія → вихід, %", lambda s, sim: s["sys_eff_pct"], 1),
    ("Пік температури, °C", lambda s, sim: s["peak_t_el"], 1),
    ("Водень сумарно, л", lambda s, sim: s["h2_total_l"], 2),
    ("Заряд телефона, %", lambda s, sim: s.get("phone_soc_pct", float("nan")), 1),
    ("Час до цілі", lambda s, sim: format_duration(s["phone_t_done_s"]) if s.get("phone_t_done_s") else "—", None),
]


class ComparePage(Page):
    title = "Порівняння варіантів"
    subtitle = "Два варіанти конструкції з однаковими або власними налаштуваннями навантаження. Розрахунок виконується повністю у фоні."

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        self.slots: dict = {"A": None, "B": None}
        self.results: dict = {}
        b_run = QPushButton("⇄  Порівняти")
        b_run.setObjectName("Primary")
        b_run.clicked.connect(self.run)
        self.head_actions.addWidget(b_run)
        row = self.responsive(QHBoxLayout(), 900)
        row.setSpacing(14)
        self.slot_cards = {}
        for key in ("A", "B"):
            c = Card(f"Варіант {key}")
            c.title.setStyleSheet(f"color: {COLORS[key]};")
            info = label("Не задано", "Secondary", wrap=True)
            c.add(info)
            bl = QHBoxLayout()
            b1 = QPushButton("Поточна конструкція")
            b1.clicked.connect(lambda _=False, k=key: self.take_current(k))
            b2 = QPushButton("Відкрити…")
            b2.clicked.connect(lambda _=False, k=key: self.load_file(k))
            b3 = QPushButton("Зробити поточною")
            b3.clicked.connect(lambda _=False, k=key: self.make_current(k))
            for b in (b1, b2, b3):
                bl.addWidget(b)
            c.add(bl)
            self.slot_cards[key] = (c, info)
            row.addWidget(c)
        self.body.addLayout(row)
        mc = Card("Ключові показники")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Показник", "A", "B", "Різниця B − A"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(420)
        mc.add(self.table)
        self.verdicts = label("", "Secondary", wrap=True)
        mc.add(self.verdicts)
        self.body.addWidget(mc)
        g = QGridLayout()
        g.setSpacing(12)
        self.charts = []
        for k, (title, unit, key) in enumerate(CHARTS):
            c = ChartCard(title, unit, height=190)
            c.add_series("A", COLORS["A"])
            c.add_series("B", COLORS["B"])
            c.key = key
            self.charts.append(c)
            g.addWidget(c, k // 3, k % 3)
        self.body.addLayout(g)

    def _describe(self, key: str) -> None:
        sc = self.slots[key]
        _, info = self.slot_cards[key]
        if sc is None:
            info.setText("Не задано")
            return
        try:
            a = analyze(sc.design)
            g = a.geo
            info.setText(f"<b>{sc.design.name}</b><br>{g.n_series} посл. × {g.n_parallel} пар., анод {sc.design.anode}, "
                         f"катод {sc.design.cathode}<br>Mg {fmt(g.total_mass_g, 1)} г, площа анода {fmt(g.anode_area_cm2, 0)} см²/комірку, "
                         f"НРК {fmt(a.ocv_stack, 2)} В, макс. USB {fmt(a.p_max_usb_w, 2)} Вт<br>Навантаження: {sc.sim.load_mode}")
        except Exception as exc:  # noqa: BLE001
            info.setText(f"{sc.design.name}: помилка — {exc}")

    def take_current(self, key: str) -> None:
        self.slots[key] = clone(self.ctrl.scenario)
        self._describe(key)

    def load_file(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити сценарій", str(SCENARIO_DIR), "Сценарій EarthCharge (*.json)")
        if not path:
            return
        try:
            sc, _, _ = load_scenario(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Порівняння", f"Не вдалося відкрити: {exc}")
            return
        self.slots[key] = sc
        self._describe(key)

    def make_current(self, key: str) -> None:
        if self.slots[key] is not None:
            self.ctrl.replace_scenario(clone(self.slots[key]))

    def run(self) -> None:
        for k in ("A", "B"):
            if self.slots[k] is None:
                self.take_current(k)
        scs = {k: clone(v) for k, v in self.slots.items()}

        def job(progress, cancel):
            out = {}
            for n, (k, sc) in enumerate(scs.items()):
                sc.sim.dt_s = max(sc.sim.dt_s, 5.0)
                sim = Simulation(sc)
                sim.run(progress=lambda p, n=n: progress(int((n * 100 + p) / 2)), cancel=cancel)
                out[k] = sim
            return out

        self.ctrl.run_job("Порівняння варіантів…", job, self._done)

    def _done(self, res: dict) -> None:
        self.results = res
        sims = [res["A"], res["B"]]
        sums = [s.summary() for s in sims]
        self.table.setRowCount(len(METRICS))
        for r, (name, fn, digits) in enumerate(METRICS):
            vals = [fn(s, sim) for s, sim in zip(sums, sims)]
            self.table.setItem(r, 0, QTableWidgetItem(name))
            for c, v in enumerate(vals):
                txt = fmt(v, digits) if (digits is not None and isinstance(v, (int, float))) else str(v)
                self.table.setItem(r, c + 1, QTableWidgetItem(txt))
            if digits is not None and all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
                d = vals[1] - vals[0]
                self.table.setItem(r, 3, QTableWidgetItem(("+" if d > 0 else "") + fmt(d, digits)))
            else:
                self.table.setItem(r, 3, QTableWidgetItem(""))
        lines = []
        for k, s in zip(("A", "B"), sums):
            v = s["verdicts"]
            if v:
                lines.append(f"<b style='color:{COLORS[k]}'>{k}:</b> {v[0][1]}")
        self.verdicts.setText("<br>".join(lines))
        for c in self.charts:
            for i, sim in enumerate(sims):
                t = sim.rec.get("t_h")
                usb = sim.mode in ("phone", "usb_power", "mppt")
                if c.key == "_out":
                    y = sim.rec.get("p_usb" if usb else "p_term")
                elif c.key == "_e_out":
                    y = sim.rec.get("e_usb_wh" if usb else "e_term_wh")
                else:
                    y = sim.rec.get(c.key)
                c.set_data(i, t, y)

    def on_shown(self) -> None:
        for k in ("A", "B"):
            if self.slots[k] is None:
                self.take_current(k)
        super().on_shown()
