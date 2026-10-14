"""Конструктор: розріз комірки, похідні величини та вольт-амперні характеристики без часової симуляції."""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem

from .. import theme as T
from ...core.analysis import analyze
from ...core.design import has_errors, validate_design
from ..widgets.cell_view import CellCrossSection
from ..widgets.common import Card, ChartCard, VerdictList, label
from .base import Page

S = T.SERIES


class ConstructorPage(Page):
    title = "Конструктор"
    subtitle = ("Збирайте генератор у правій панелі. Розріз, похідні величини та характеристики перераховуються "
                "миттєво; часова симуляція — на сторінці «Генератор».")

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        top = self.responsive(QHBoxLayout(), 1100)
        top.setSpacing(14)
        cc = Card("Комірка в розрізі")
        self.cell = CellCrossSection(show_labels=True)
        self.cell.setMinimumHeight(380)
        cc.add(self.cell, 1)
        top.addWidget(cc, 3)
        tc = Card("Розрахункові характеристики", "Статичний аналіз при температурі середовища, без пасивації та шламу.")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Величина", "Значення"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(380)
        tc.add(self.table, 1)
        top.addWidget(tc, 2)
        self.body.addLayout(top)

        row = self.responsive(QHBoxLayout(), 1000)
        row.setSpacing(14)
        self.c_v = ChartCard("ВАХ однієї комірки", "В", x_label="Густина струму анода, мА/см²", height=230)
        self.c_v.add_series("Напруга", S[0])
        self.c_p = ChartCard("Питома потужність комірки", "мВт/см²", x_label="Густина струму анода, мА/см²", height=230)
        self.c_p.add_series("Потужність", S[2])
        self.c_e = ChartCard("Ефективність анода", "%", x_label="Густина струму анода, мА/см²", height=230)
        self.c_e.add_series("Корисна частка Mg", S[3])
        for c in (self.c_v, self.c_p, self.c_e):
            row.addWidget(c)
        self.body.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        self.c_sv = ChartCard("Батарея комірок: напруга на виводах", "В", x_label="Струм, А", height=230)
        self.c_sv.add_series("Напруга", S[0])
        self.c_sp = ChartCard("Батарея комірок: потужність", "Вт", x_label="Струм, А", height=230)
        self.c_sp.add_series("На виводах", S[0])
        self.c_sp.add_series("На USB-C (після DC/DC)", S[2])
        row2.addWidget(self.c_sv)
        row2.addWidget(self.c_sp)
        self.body.addLayout(row2)
        ic = Card("Перевірка конструкції")
        self.issues = VerdictList()
        ic.add(self.issues)
        self.note = label("Позначки статусу параметрів і припущення — на сторінці «Модель і перевірки».", "Muted", wrap=True)
        ic.add(self.note)
        self.body.addWidget(ic)

    def on_scenario_changed(self) -> None:
        d = self.ctrl.scenario.design
        self.cell.set_design(d)
        self.cell.reset_live()
        issues = validate_design(d)
        self.issues.set_items([(i.level if i.level != "error" else "critical", i.message) for i in issues]
                              or [("ok", "Конструкція коректна.")])
        if has_errors(issues):
            self.table.setRowCount(0)
            for c in (self.c_v, self.c_p, self.c_e, self.c_sv, self.c_sp):
                c.clear_data()
            return
        a = analyze(d)
        rows = a.as_rows()
        self.table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(k))
            self.table.setItem(r, 1, QTableWidgetItem(v))
        self.table.resizeRowsToContents()
        cc, cs = a.curve_cell, a.curve_stack
        self.c_v.set_data(0, cc["i_ma_cm2"], cc["v"])
        self.c_p.set_data(0, cc["i_ma_cm2"], cc["p_mw_cm2"])
        self.c_e.set_data(0, cc["i_ma_cm2"][1:], cc["eff"][1:])
        self.c_sv.set_data(0, cs["i_a"], cs["v"])
        self.c_sp.set_data(0, cs["i_a"], cs["p_w"])
        self.c_sp.set_data(1, cs["i_a"], np.where(np.isfinite(cs["p_usb_w"]) & (cs["p_usb_w"] > 0), cs["p_usb_w"], np.nan))
