"""Підбір конструкції: скільки пластин, якої площі та маси потрібно, щоб зарядити телефон за заданий час."""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QProgressBar, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import theme as T
from ...core.phone import PhoneBattery
from ...core.sizing import SizingConstraints, candidate_scenario, size_for_phone
from ...core.design import clone
from ...core.units import fmt
from ..widgets.common import BoundForm, Card, Field, label
from .base import Page


class _Holder:
    def __init__(self):
        self.c = SizingConstraints()


FIELDS = [
    Field("c.max_series", "Макс. послідовних комірок", "int", lo=1, hi=12),
    Field("c.max_parallel", "Макс. паралельних груп", "int", lo=1, hi=6),
    Field("c.max_cells", "Макс. комірок усього", "int", lo=1, hi=32),
    Field("c.reserve_pct", "Запас магнію понад розрахунок", lo=0, hi=200, step=5, decimals=0, suffix="%"),
    Field("c.max_total_mass_g", "Обмеження маси Mg (0 — немає)", lo=0, hi=10000, step=10, decimals=0, suffix="г"),
    Field("c.dt_s", "Крок моделі для підбору", lo=5, hi=120, step=5, decimals=0, suffix="с"),
]


def _parse_list(text: str) -> tuple:
    vals = []
    for part in text.replace(";", " ").replace("\n", " ").split():
        try:
            v = float(part.replace(",", "."))
            if v > 0:
                vals.append(v)
        except ValueError:
            continue
    return tuple(sorted(set(vals)))


class SizingPage(Page):
    title = "Підбір конструкції під 7 годин"
    subtitle = ("Перебір кількості комірок, схеми з'єднання та площі пластин з повною симуляцією заряджання. "
                "Для кожного варіанта товщина визначається з фактичної витрати Mg (корисний струм + самокорозія).")

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        self.h = _Holder()
        self.worker = None
        self.result = None
        top = self.responsive(QHBoxLayout(), 900)
        top.setSpacing(14)
        cc = Card("Обмеження пошуку")
        self.form = BoundForm(FIELDS, lambda: self.h, label_width=190)
        cc.add(self.form)
        self.areas = QLineEdit(" ; ".join(fmt(a, 0) for a in self.h.c.plate_areas_cm2))
        self.thick = QLineEdit(" ; ".join(fmt(t, 1) for t in self.h.c.thicknesses_mm))
        cc.add(label("Площі пластини (одна сторона), см²", "Secondary"))
        cc.add(self.areas)
        cc.add(label("Доступні товщини листа, мм", "Secondary"))
        cc.add(self.thick)
        cc.add(label("Матеріали, зазор, електроліт, перетворювач і пропорції пластини беруться з поточної конструкції; "
                     "телефон і час — зі сторінки «Зарядити смартфон».", "Muted", wrap=True))
        bl = QHBoxLayout()
        self.b_run = QPushButton("⌕  Підібрати")
        self.b_run.setObjectName("Primary")
        self.b_run.clicked.connect(self.run)
        self.b_stop = QPushButton("Зупинити")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.stop)
        bl.addWidget(self.b_run)
        bl.addWidget(self.b_stop)
        cc.add(bl)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        cc.add(self.progress)
        top.addWidget(cc, 2)
        right = QVBoxLayout()
        right.setSpacing(12)
        tc = Card("Ціль")
        self.target = label("", "Secondary", wrap=True)
        tc.add(self.target)
        right.addWidget(tc)
        bc = Card("Рекомендація")
        self.best = label("Запустіть підбір.", "Secondary", wrap=True)
        bc.add(self.best)
        self.b_apply = QPushButton("Застосувати вибраний варіант до конструкції")
        self.b_apply.setEnabled(False)
        self.b_apply.clicked.connect(self.apply)
        bc.add(self.b_apply)
        right.addWidget(bc)
        right.addStretch(1)
        top.addLayout(right, 3)
        self.body.addLayout(top)
        rc = Card("Придатні варіанти", "Відсортовано за масою магнію, далі — за кількістю комірок. Виберіть рядок, щоб застосувати.")
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(["#", "S × P", "Пластина, мм", "Площа анода/комірку, см²", "Товщина, мм",
                                              "Маса Mg, г", "Витрата Mg, г", "Час заряджання", "Макс. USB, Вт",
                                              "Пік T, °C", "Пік H₂, %", "Вт·год/г"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setMinimumHeight(300)
        self.table.itemSelectionChanged.connect(lambda: self.b_apply.setEnabled(bool(self.table.selectedItems())))
        rc.add(self.table)
        self.body.addWidget(rc)
        row = QHBoxLayout()
        row.setSpacing(14)
        sc = Card("Чутливість до припущень (найкращий варіант)",
                  "Повторний розрахунок при зміні ключових неперевірених коефіцієнтів показує, наскільки прогноз залежить від припущень.")
        self.sens = QTableWidget(0, 4)
        self.sens.setHorizontalHeaderLabels(["Припущення", "Час заряджання, год", "Витрата Mg, г", "Заряд, %"])
        self.sens.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sens.verticalHeader().setVisible(False)
        self.sens.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sens.setMinimumHeight(320)
        sc.add(self.sens)
        self.sens_note = label("", "Secondary", wrap=True)
        sc.add(self.sens_note)
        row.addWidget(sc, 3)
        jc = Card("Відкинуті варіанти")
        self.rejected = QTableWidget(0, 2)
        self.rejected.setHorizontalHeaderLabels(["Варіант", "Причина"])
        self.rejected.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rejected.verticalHeader().setVisible(False)
        self.rejected.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rejected.setMinimumHeight(320)
        jc.add(self.rejected)
        row.addWidget(jc, 2)
        self.body.addLayout(row)

    def on_scenario_changed(self) -> None:
        ph = self.ctrl.scenario.phone
        try:
            need = PhoneBattery(ph).energy_needed_wh()
            self.target.setText(
                f"Телефон {fmt(ph.battery_wh(), 2)} Вт·год, заряд {fmt(ph.soc_start_pct, 0)} → {fmt(ph.soc_target_pct, 0)} % "
                f"за {fmt(ph.max_time_h, 1)} год, потужність заряджання до {fmt(ph.max_charge_power_w, 1)} Вт.<br>"
                f"Потрібно ≈ {fmt(need, 2)} Вт·год на вході телефона. Анод: {self.ctrl.scenario.design.anode}, "
                f"катод: {self.ctrl.scenario.design.cathode}, електроліт: {self.ctrl.scenario.design.electrolyte}, "
                f"обмеження USB-C {fmt(self.ctrl.scenario.design.converter.p_out_max_w, 1)} Вт.")
        except Exception as exc:  # noqa: BLE001
            self.target.setText(str(exc))

    def run(self) -> None:
        c = self.h.c
        areas = _parse_list(self.areas.text())
        thick = _parse_list(self.thick.text())
        if not areas or not thick:
            self.ctrl.message.emit("critical", "Задайте списки площ і товщин.")
            return
        c.plate_areas_cm2, c.thicknesses_mm = areas, thick
        base = clone(self.ctrl.scenario)
        cons = SizingConstraints(**{k: getattr(c, k) for k in c.__dataclass_fields__})
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.progress.setValue(0)

        def job(progress, cancel):
            return size_for_phone(base, cons, progress=progress, cancel=cancel)

        self.base = base
        self.worker = self.ctrl.run_job("Підбір конструкції…", job, self._done, on_progress=self.progress.setValue,
                                        on_fail=self._fail)

    def stop(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _fail(self, msg: str) -> None:
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.ctrl.message.emit("critical", msg)

    def _done(self, res) -> None:
        self.result = res
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.progress.setValue(100)
        self.table.setRowCount(len(res.candidates))
        for r, c in enumerate(res.candidates):
            vals = [str(r + 1), f"{c.n_series} × {c.n_parallel}", f"{fmt(c.plate_length_mm, 0)} × {fmt(c.plate_width_mm, 0)}",
                    fmt(c.anode_area_cell_cm2, 0), fmt(c.thickness_mm, 2), fmt(c.mass_total_g, 1), fmt(c.mg_consumed_g, 1),
                    f"{fmt(c.t_done_h, 2)} год", fmt(c.p_usb_max_w, 2), fmt(c.peak_t_el, 0), fmt(c.peak_h2_pct, 2), fmt(c.wh_per_g, 2)]
            for k, v in enumerate(vals):
                self.table.setItem(r, k, QTableWidgetItem(v))
        if res.candidates:
            self.table.selectRow(0)
            b = res.candidates[0]
            rng = res.sensitivity_mass_range
            rng_txt = (f" З урахуванням невизначеності припущень потрібна маса Mg ≈ {fmt(rng[0], 1)}–{fmt(rng[1], 1)} г."
                       if rng else "")
            self.best.setText(
                f"<b style='color:{T.GOOD}'>Найменша маса магнію:</b> {b.n_series} послідовно × {b.n_parallel} паралельно = "
                f"{b.n_cells} комірок, пластини {fmt(b.plate_length_mm, 0)} × {fmt(b.plate_width_mm, 0)} × {fmt(b.thickness_mm, 2)} мм, "
                f"активна площа анода {fmt(b.anode_area_cell_cm2, 0)} см² на комірку, усього Mg {fmt(b.mass_total_g, 1)} г "
                f"(витрата за заряджання {fmt(b.mg_consumed_g, 1)} г). Телефон заряджається за {fmt(b.t_done_h, 2)} год.{rng_txt}"
                f"<br><span style='color:{T.MUTED}'>Це прогноз оціночної моделі. Перевірте його дослідом і відкалібруйте модель "
                f"у розділі «Лабораторія».</span>")
        else:
            self.best.setText(f"<b style='color:{T.CRITICAL}'>Жоден варіант не заряджає телефон за "
                              f"{fmt(res.target_h, 1)} год у заданих межах.</b> Розширте межі (більше комірок, більші площі), "
                              f"збільште обмеження потужності USB-C або час.")
        self.sens.setRowCount(len(res.sensitivity))
        for r, (name, t_done, mg, soc) in enumerate(res.sensitivity):
            self.sens.setItem(r, 0, QTableWidgetItem(name))
            self.sens.setItem(r, 1, QTableWidgetItem(fmt(t_done, 2) if t_done else "не встигає"))
            self.sens.setItem(r, 2, QTableWidgetItem(fmt(mg, 1)))
            self.sens.setItem(r, 3, QTableWidgetItem(fmt(soc, 0)))
        fails = sum(1 for s in res.sensitivity if s[1] is None)
        self.sens_note.setText(f"У {fails} з {len(res.sensitivity)} сценаріїв невизначеності телефон не встигає зарядитися."
                               if fails else "За всіх перевірених припущень найкращий варіант встигає зарядити телефон.")
        self.rejected.setRowCount(len(res.rejected))
        for r, (desc, why) in enumerate(res.rejected):
            self.rejected.setItem(r, 0, QTableWidgetItem(desc))
            self.rejected.setItem(r, 1, QTableWidgetItem(why))
        if res.cancelled:
            self.ctrl.message.emit("warning", "Підбір зупинено: показано знайдені на цей момент варіанти.")

    def apply(self) -> None:
        if not self.result or not self.table.selectedItems():
            return
        row = self.table.currentRow()
        c = self.result.candidates[row]
        sc = candidate_scenario(self.ctrl.scenario, c)
        sc.design.name = f"Підбір: {c.n_series}×{c.n_parallel}, {fmt(c.plate_area_cm2, 0)} см²"
        self.ctrl.replace_scenario(sc)
        self.ctrl.message.emit("ok", f"Застосовано варіант {c.n_series}×{c.n_parallel} з масою Mg {fmt(c.mass_total_g, 1)} г.")
