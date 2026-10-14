"""Лабораторія: досліди, вимірювання, імпорт CSV, порівняння із симуляцією та калібрування моделі."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import theme as T
from ...core import materials as M
from ...core.calibration import KIND_LABELS, apply_calibration, calibrate_efficiency, calibrate_passivation, \
    calibrate_polarization, replay
from ...core.design import clone
from ...core.experiments import (CONSTRUCTION_LABELS, Experiment, Measurement, apply_import, construction_of_cathode,
                                 experiment_to_csv, parse_csv_file)
from ...core.params import build_params
from ...core.units import fmt
from ..controller import EXPORT_DIR
from ..widgets.common import Card, ChartCard, Combo, DoubleSpin, Field, VerdictList, label
from .base import Page

S = T.SERIES
NUM_FIELDS = [
    ("area_cm2", "Площа електрода (анода)", 0, 100000, 1, "см²"),
    ("gap_mm", "Відстань анод — катод", 0, 200, 1, "мм"),
    ("electrolyte_ml", "Об'єм електроліту", 0, 100000, 0, "мл"),
    ("temperature_c", "Температура середовища", -40, 100, 1, "°C"),
    ("mass_start_g", "Початкова маса Mg (0 — не зважено)", 0, 100000, 3, "г"),
    ("mass_end_g", "Кінцева маса Mg (0 — не зважено)", 0, 100000, 3, "г"),
]


def _num(text: str) -> float:
    try:
        return float(text.replace(",", ".").strip())
    except (ValueError, AttributeError):
        return math.nan


def _txt(x: float, digits: int = 6) -> str:
    return "" if x is None or not math.isfinite(x) else f"{x:.{digits}g}".replace(".", ",")


class LabPage(Page):
    title = "Лабораторія"
    subtitle = ("Записуйте власні досліди (мультиметр, навантаження), імпортуйте CSV, порівнюйте із симуляцією й калібруйте "
                "модель. Досліди Mg–графіт і Mg–повітря зберігаються окремо й не змішуються.")
    uses_param_panel = False

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        self.exp = Experiment()
        self.cal_result = None
        top = self.responsive(QHBoxLayout(), 1000)
        top.setSpacing(14)
        lc = Card("Досліди")
        self.list = QTableWidget(0, 5)
        self.list.setHorizontalHeaderLabels(["#", "Дата", "Назва", "Конструкція", "Точок"])
        self.list.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.list.verticalHeader().setVisible(False)
        self.list.setEditTriggers(QTableWidget.NoEditTriggers)
        self.list.setSelectionBehavior(QTableWidget.SelectRows)
        self.list.setSelectionMode(QTableWidget.SingleSelection)
        self.list.setMinimumHeight(330)
        self.list.cellClicked.connect(self._open_row)
        lc.add(self.list, 1)
        bl = QHBoxLayout()
        for text, fn in (("Новий", self.new), ("Імпорт CSV…", self.import_csv), ("Експорт CSV…", self.export_csv),
                         ("Видалити", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bl.addWidget(b)
        lc.add(bl)
        top.addWidget(lc, 2)

        fc = Card("Опис досліду")
        form = QFormLayout()
        form.setVerticalSpacing(6)
        self.name = QLineEdit()
        self.date = QLineEdit()
        self.construction = Combo()
        for k, v in CONSTRUCTION_LABELS.items():
            self.construction.addItem(v, k)
        self.anode = Combo()
        for k, a in M.ANODES.items():
            self.anode.addItem(a.name, k)
        self.cathode = Combo()
        for k, c in M.CATHODES.items():
            self.cathode.addItem(c.name, k)
        self.cathode.currentIndexChanged.connect(self._cathode_changed)
        self.electrolyte = Combo()
        for k, e in M.ELECTROLYTES.items():
            self.electrolyte.addItem(e.name, k)
        self.separator = Combo()
        for k, sp in M.SEPARATORS.items():
            self.separator.addItem(sp.name, k)
        form.addRow(label("Назва", "Secondary"), self.name)
        form.addRow(label("Дата", "Secondary"), self.date)
        form.addRow(label("Тип конструкції", "Secondary"), self.construction)
        form.addRow(label("Анод", "Secondary"), self.anode)
        form.addRow(label("Катод", "Secondary"), self.cathode)
        form.addRow(label("Електроліт", "Secondary"), self.electrolyte)
        form.addRow(label("Сепаратор", "Secondary"), self.separator)
        self.nums = {}
        for key, text, lo, hi, dec, suf in NUM_FIELDS:
            w = DoubleSpin(Field(key, text, lo=lo, hi=hi, decimals=dec, suffix=suf))
            self.nums[key] = w
            form.addRow(label(text, "Secondary"), w)
        self.load_desc = QLineEdit()
        self.load_desc.setPlaceholderText("напр. резистор 10 Ом, світлодіод, ступені 0,05–0,5 А")
        form.addRow(label("Навантаження", "Secondary"), self.load_desc)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Примітки: підготовка пластини, сепаратор, очищення перед зважуванням…")
        self.notes.setMaximumHeight(80)
        form.addRow(label("Примітки", "Secondary"), self.notes)
        fc.add(form)
        self.cat_warning = label("", "", wrap=True)
        fc.add(self.cat_warning)
        b_save = QPushButton("Зберегти дослід")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self.save)
        fc.add(b_save)
        top.addWidget(fc, 3)
        self.body.addLayout(top)

        mid = self.responsive(QHBoxLayout(), 1000)
        mid.setSpacing(14)
        mc = Card("Вимірювання", "Час у секундах, напруга у вольтах, струм в амперах. Десяткова кома або крапка.")
        self.meas = QTableWidget(0, 4)
        self.meas.setHorizontalHeaderLabels(["Час, с", "Напруга, В", "Струм, А", "Темп., °C"])
        self.meas.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.meas.verticalHeader().setVisible(False)
        self.meas.setMinimumHeight(330)
        mc.add(self.meas, 1)
        bl2 = QHBoxLayout()
        for text, fn in (("+ Рядок", self.add_row), ("− Рядок", self.remove_row), ("Оновити графіки", self.refresh_plots)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bl2.addWidget(b)
        mc.add(bl2)
        self.metrics = label("", "Secondary", wrap=True)
        mc.add(self.metrics)
        mid.addWidget(mc, 2)
        charts = QVBoxLayout()
        charts.setSpacing(12)
        self.c_v = ChartCard("Напруга: дослід і симуляція", "В", height=170)
        self.c_v.add_series("Дослід", S[0])
        self.c_v.add_series("Симуляція", S[1], dash=True)
        self.c_i = ChartCard("Струм", "А", height=150)
        self.c_i.add_series("Дослід", S[0])
        self.c_p = ChartCard("Потужність", "Вт", height=150)
        self.c_p.add_series("Дослід", S[2])
        for c in (self.c_v, self.c_i, self.c_p):
            charts.addWidget(c)
        mid.addLayout(charts, 3)
        self.body.addLayout(mid)

        bottom = self.responsive(QHBoxLayout(), 1000)
        bottom.setSpacing(14)
        cc = Card("Порівняння з симуляцією", "Модель однієї комірки з площею, зазором і матеріалами досліду, "
                                             "навантажена виміряним профілем струму.")
        b_cmp = QPushButton("Порівняти з симуляцією")
        b_cmp.clicked.connect(self.compare)
        cc.add(b_cmp)
        self.cmp_text = VerdictList()
        cc.add(self.cmp_text)
        bottom.addWidget(cc, 2)
        kc = Card("Калібрування моделі")
        kl = QHBoxLayout()
        self.kind = Combo()
        for k, v in KIND_LABELS.items():
            self.kind.addItem(v, k)
        self.fit_tafel = QCheckBox("підбирати також тафелів нахил")
        kl.addWidget(self.kind, 1)
        kl.addWidget(self.fit_tafel)
        b_cal = QPushButton("Калібрувати")
        b_cal.setObjectName("Primary")
        b_cal.clicked.connect(self.calibrate)
        kl.addWidget(b_cal)
        kc.add(kl)
        self.cal_table = QTableWidget(0, 4)
        self.cal_table.setHorizontalHeaderLabels(["Параметр", "Було", "Стало", "Одиниці"])
        self.cal_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cal_table.verticalHeader().setVisible(False)
        self.cal_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cal_table.setMaximumHeight(150)
        kc.add(self.cal_table)
        self.cal_msgs = VerdictList()
        kc.add(self.cal_msgs)
        self.c_fit = ChartCard("Якість підгонки", "В", x_label="Струм, А", height=190)
        self.c_fit.add_series("Виміряно", S[0])
        self.c_fit.add_series("Модель до", S[3], dash=True)
        self.c_fit.add_series("Модель після", S[2])
        kc.add(self.c_fit)
        self.b_apply = QPushButton("Застосувати до поточної конструкції")
        self.b_apply.setEnabled(False)
        self.b_apply.clicked.connect(self.apply_cal)
        kc.add(self.b_apply)
        bottom.addWidget(kc, 3)
        self.body.addLayout(bottom)
        self.reload_list()
        self._to_form()

    # ------------------------------------------------------------ список
    def reload_list(self) -> None:
        rows = self.ctrl.db.list()
        self.list.setRowCount(len(rows))
        self._ids = []
        for r, row in enumerate(rows):
            self._ids.append(row["id"])
            vals = [str(row["id"]), row["date"] or "", row["name"], CONSTRUCTION_LABELS.get(row["construction"], row["construction"]),
                    str(row["n_points"])]
            for k, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if k == 3:
                    it.setForeground(QColor(T.TEXT if row["construction"] == "air" else T.WARNING))
                self.list.setItem(r, k, it)

    def _open_row(self, row: int, col: int) -> None:
        try:
            self.exp = self.ctrl.db.load(self._ids[row])
        except KeyError:
            return
        self._to_form()

    def new(self) -> None:
        d = self.ctrl.scenario.design
        self.exp = Experiment(anode=d.anode, cathode=d.cathode, electrolyte=d.electrolyte, separator=d.separator,
                              construction=construction_of_cathode(d.cathode), gap_mm=d.geometry.gap_mm,
                              temperature_c=d.environment.ambient_c)
        self._to_form()

    def delete(self) -> None:
        if self.exp.id is None:
            return
        if QMessageBox.question(self, "Лабораторія", f"Видалити дослід «{self.exp.name}»?") != QMessageBox.Yes:
            return
        self.ctrl.db.delete(self.exp.id)
        self.exp = Experiment()
        self.reload_list()
        self._to_form()

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Імпорт вимірювань", str(Path.home()), "CSV (*.csv *.txt);;Усі файли (*)")
        if not path:
            return
        try:
            imp = parse_csv_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Імпорт CSV", f"Не вдалося прочитати файл:\n{exc}")
            return
        self._from_form()
        apply_import(self.exp, imp)
        if not self.exp.name or self.exp.name == "Новий дослід":
            self.exp.name = Path(path).stem
        self._to_form()
        msg = f"Імпортовано {len(imp.measurements)} рядків."
        if imp.warnings:
            msg += " " + " ".join(imp.warnings)
        self.ctrl.message.emit("ok", msg + " Перевірте опис і натисніть «Зберегти дослід».")

    def export_csv(self) -> None:
        self._from_form()
        path, flt = QFileDialog.getSaveFileName(self, "Експорт досліду", str(EXPORT_DIR / f"{self.exp.name}.csv"),
                                                "Excel (Україна): «;» і кома (*.csv);;Стандартний CSV (*.csv)")
        if not path:
            return
        Path(path).write_text(experiment_to_csv(self.exp, excel_ua=flt.startswith("Excel")), encoding="utf-8-sig")
        self.ctrl.message.emit("ok", f"Дослід експортовано: {path}")

    def save(self) -> None:
        self._from_form()
        if not self.exp.measurements:
            if QMessageBox.question(self, "Лабораторія", "Дослід без вимірювань. Зберегти лише опис?") != QMessageBox.Yes:
                return
        self.ctrl.db.save(self.exp)
        self.reload_list()
        self._to_form()
        self.ctrl.message.emit("ok", f"Дослід #{self.exp.id} збережено.")

    # ------------------------------------------------------------ форма
    def _cathode_changed(self) -> None:
        cat = construction_of_cathode(self.cathode.currentData())
        if self.construction.currentData() != "other":
            self.construction.setCurrentIndex(self.construction.findData(cat))
        self._update_cat_warning()

    def _update_cat_warning(self) -> None:
        exp_cat = self.construction.currentData()
        design_cat = construction_of_cathode(self.ctrl.scenario.design.cathode)
        cath_cat = construction_of_cathode(self.cathode.currentData())
        if exp_cat != cath_cat and exp_cat != "other":
            self.cat_warning.setText(f"⚠ Тип конструкції не відповідає вибраному катоду ({M.CATEGORY_LABELS[cath_cat]}).")
            self.cat_warning.setStyleSheet(f"color: {T.WARNING};")
        elif exp_cat != design_cat:
            self.cat_warning.setText(f"Цей дослід — «{CONSTRUCTION_LABELS[exp_cat]}», а поточна конструкція — "
                                     f"«{M.CATEGORY_LABELS[design_cat]}». Калібрування до неї не застосовуватиметься.")
            self.cat_warning.setStyleSheet(f"color: {T.WARNING};")
        else:
            self.cat_warning.setText("Тип досліду збігається з поточною конструкцією: калібрування можна застосувати.")
            self.cat_warning.setStyleSheet(f"color: {T.MUTED};")

    def _to_form(self) -> None:
        e = self.exp
        self.name.setText(e.name)
        self.date.setText(e.date or "")
        for combo, val in ((self.construction, e.construction), (self.anode, e.anode), (self.cathode, e.cathode),
                           (self.electrolyte, e.electrolyte), (self.separator, e.separator)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(val)))
            combo.blockSignals(False)
        for key, w in self.nums.items():
            v = getattr(e, key)
            w.setValue(v if (isinstance(v, (int, float)) and math.isfinite(v)) else 0.0)
        self.load_desc.setText(e.load_desc or "")
        self.notes.setPlainText(e.notes or "")
        ms = sorted(e.measurements, key=lambda m: m.t_s)
        self.meas.setRowCount(len(ms))
        for r, m in enumerate(ms):
            for c, v in enumerate((m.t_s, m.voltage_v, m.current_a, m.temperature_c)):
                self.meas.setItem(r, c, QTableWidgetItem(_txt(v)))
        self._update_cat_warning()
        self.refresh_plots()

    def _from_form(self) -> None:
        e = self.exp
        e.name = self.name.text().strip() or "Дослід"
        e.date = self.date.text().strip()
        e.construction = self.construction.currentData()
        e.anode = self.anode.currentData()
        e.cathode = self.cathode.currentData()
        e.electrolyte = self.electrolyte.currentData()
        e.separator = self.separator.currentData()
        for key, w in self.nums.items():
            v = w.value()
            if key.startswith("mass") and v <= 0:
                v = math.nan
            setattr(e, key, v)
        e.load_desc = self.load_desc.text()
        e.notes = self.notes.toPlainText()
        ms = []
        for r in range(self.meas.rowCount()):
            vals = [_num(self.meas.item(r, c).text()) if self.meas.item(r, c) else math.nan for c in range(4)]
            if math.isfinite(vals[0]):
                ms.append(Measurement(*vals))
        e.measurements = sorted(ms, key=lambda m: m.t_s)

    def add_row(self) -> None:
        r = self.meas.rowCount()
        self.meas.insertRow(r)
        last_t = _num(self.meas.item(r - 1, 0).text()) if r > 0 and self.meas.item(r - 1, 0) else -60.0
        self.meas.setItem(r, 0, QTableWidgetItem(_txt(last_t + 60.0 if math.isfinite(last_t) else 0.0)))
        self.meas.setCurrentCell(r, 1)

    def remove_row(self) -> None:
        r = self.meas.currentRow()
        if r >= 0:
            self.meas.removeRow(r)

    def refresh_plots(self) -> None:
        self._from_form()
        a = self.exp.arrays()
        t = a["t_s"] / 3600.0
        self.c_v.set_data(0, t, a["v"])
        self.c_v.set_data(1, [], [])
        self.c_i.set_data(0, t, a["i"])
        self.c_p.set_data(0, t, a["v"] * a["i"])
        m = self.exp.metrics() if self.exp.measurements else None
        if not m:
            self.metrics.setText("Немає вимірювань.")
            return
        parts = [f"Точок: {m['n_points']}, тривалість {fmt(m['duration_s'] / 3600, 2)} год",
                 f"заряд {fmt(m['charge_ah'] * 1000, 1)} мА·год, енергія {fmt(m['energy_wh'] * 1000, 1)} мВт·год",
                 f"середня напруга {fmt(m['v_mean'], 3)} В, середня густина струму {fmt(m['i_density_ma_cm2'], 2)} мА/см²"]
        if math.isfinite(m["mass_loss_g"]):
            parts.append(f"втрата маси {fmt(m['mass_loss_g'], 3)} г (за Фарадеєм на корисний струм {fmt(m['faraday_mass_g'], 3)} г)")
        if math.isfinite(m.get("anode_eff_pct", math.nan)):
            parts.append(f"виміряна ефективність анода {fmt(m['anode_eff_pct'], 1)} %, {fmt(m['wh_per_g'], 3)} Вт·год/г Mg")
        self.metrics.setText(" · ".join(parts))

    # ------------------------------------------------------------ симуляція й калібрування
    def compare(self) -> None:
        self._from_form()
        if len(self.exp.measurements) < 2:
            self.ctrl.message.emit("warning", "Для порівняння потрібно щонайменше два рядки вимірювань.")
            return
        exp = copy.deepcopy(self.exp)
        base = clone(self.ctrl.scenario.design)

        def job(progress, cancel):
            return replay(exp, base)

        self.ctrl.run_job("Симуляція досліду…", job, self._compare_done)

    def _compare_done(self, res) -> None:
        sim, comp = res
        self.c_v.set_data(1, comp["t_s"] / 3600.0, comp["v_sim"])
        items = [("info", f"Похибка напруги (RMSE): {fmt(comp['rmse'] * 1000, 1)} мВ, середнє зміщення "
                          f"{fmt(comp['bias'] * 1000, 1)} мВ, R² = {fmt(comp['r2'], 3)}."),
                 ("info", f"Енергія: дослід {fmt(comp['energy_meas_wh'] * 1000, 1)} мВт·год, модель "
                          f"{fmt(comp['energy_sim_wh'] * 1000, 1)} мВт·год.")]
        if math.isfinite(comp["mass_loss_meas_g"]):
            items.append(("info", f"Втрата маси Mg: дослід {fmt(comp['mass_loss_meas_g'], 3)} г, модель "
                                  f"{fmt(comp['mass_loss_sim_g'], 3)} г; ефективність анода: дослід "
                                  f"{fmt(comp['eff_meas_pct'], 1)} %, модель {fmt(comp['eff_sim_pct'], 1)} %."))
        level = "ok" if comp["rmse"] < 0.05 else "warning"
        items.append((level, "Модель добре узгоджується з дослідом." if level == "ok" else
                      "Помітна розбіжність: виконайте калібрування за цим дослідом."))
        if sim.cell.category == "submerged":
            items.append(("info", "Дослід із зануреним катодом: його не можна переносити на Mg-повітряну комірку."))
        self.cmp_text.set_items(items)

    def calibrate(self) -> None:
        self._from_form()
        kind = self.kind.currentData()
        exp = copy.deepcopy(self.exp)
        base = clone(self.ctrl.scenario.design)
        fit_tafel = self.fit_tafel.isChecked()
        fn = {"polarization": lambda: calibrate_polarization(exp, base, fit_tafel),
              "efficiency": lambda: calibrate_efficiency(exp, base),
              "passivation": lambda: calibrate_passivation(exp, base)}[kind]
        self.ctrl.run_job("Калібрування…", lambda p, c: fn(), self._cal_done)

    def _cal_done(self, res) -> None:
        self.cal_result = res
        props = build_params(self.ctrl.scenario.design).props if res.params else {}
        self.cal_table.setRowCount(len(res.params))
        for r, (k, v) in enumerate(res.params.items()):
            p = props.get(k)
            self.cal_table.setItem(r, 0, QTableWidgetItem(f"{p.label if p else k} ({k})"))
            self.cal_table.setItem(r, 1, QTableWidgetItem(fmt(res.before.get(k, math.nan), 4)))
            self.cal_table.setItem(r, 2, QTableWidgetItem(fmt(v, 4)))
            self.cal_table.setItem(r, 3, QTableWidgetItem(p.unit if p else ""))
        items = [("ok" if res.ok else "critical", f"{KIND_LABELS[res.kind]}: " + ("виконано" if res.ok else "неможливо"))]
        if res.ok and math.isfinite(res.rmse_after):
            items.append(("info", f"RMSE до: {fmt(res.rmse_before * 1000, 1)} мВ, після: {fmt(res.rmse_after * 1000, 1)} мВ, "
                                  f"R² = {fmt(res.r2, 3)}, точок: {res.n_points}."))
        items += [("info", m) for m in res.messages]
        self.cal_msgs.set_items(items)
        cv = res.curve
        if cv:
            self.c_fit.pw.getPlotItem().setLabel("bottom", cv["x_label"], color=T.MUTED, size="8pt")
            self.c_fit.x_label = cv["x_label"]
            self.c_fit.set_data(0, cv["x"], cv["v_meas"])
            self.c_fit.set_data(1, cv["x"], cv["v_before"])
            self.c_fit.set_data(2, cv["x"], cv["v_after"])
        else:
            self.c_fit.clear_data()
        same = construction_of_cathode(self.ctrl.scenario.design.cathode) == self.exp.construction
        self.b_apply.setEnabled(res.ok and bool(res.params) and self.exp.id is not None and same)
        if res.ok and self.exp.id is None:
            self.cal_msgs.set_items(items + [("warning", "Збережіть дослід, щоб застосувати калібрування (потрібне посилання на дослід).")])
        elif res.ok and not same:
            self.cal_msgs.set_items(items + [("warning", "Тип досліду не збігається з поточною конструкцією — застосування заблоковано.")])

    def apply_cal(self) -> None:
        if not self.cal_result:
            return
        applied, refused = apply_calibration(self.ctrl.scenario.design, self.exp, self.cal_result)
        msgs = []
        if applied:
            msgs.append(("ok", "Застосовано: " + ", ".join(applied) + ". Статус параметрів — «Калібровано»."))
            self.ctrl.notify_changed("calibration")
        for k, why in refused:
            msgs.append(("warning", f"Не застосовано {k}: {why}"))
        self.cal_msgs.set_items(msgs)
        self.b_apply.setEnabled(False)

    def on_scenario_changed(self) -> None:
        self._update_cat_warning()

    def on_shown(self) -> None:
        self.reload_list()
        self._update_cat_warning()
