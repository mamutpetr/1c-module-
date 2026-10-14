"""Головне вікно: навігація зліва, сторінки в центрі, параметри справа, стан і керування вгорі."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_SUBTITLE, APP_VERSION
from ..core.design import LOAD_MODES
from ..core.scenarios import load_scenario, save_scenario
from ..core.units import format_duration, fmt
from . import theme as T
from .controller import EXAMPLES_DIR, EXPORT_DIR, SCENARIO_DIR, AppController
from .widgets.common import label
from .widgets.icons import app_icon, nav_icon
from .widgets.param_panel import ParamPanel


class Chip(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background: {T.PANEL_2}; border: 1px solid {T.BORDER}; border-radius: 10px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(0)
        self.cap = label(caption.upper(), "KpiCaption")
        self.val = QLabel("—")
        self.val.setStyleSheet("font-size: 12.5pt; font-weight: 600; background: transparent; border: none;")
        self.cap.setStyleSheet(self.cap.styleSheet() + "border: none;")
        lay.addWidget(self.cap)
        lay.addWidget(self.val)

    def set(self, text: str, color: str | None = None) -> None:
        self.val.setText(text)
        self.val.setStyleSheet(f"font-size: 12.5pt; font-weight: 600; background: transparent; border: none;"
                               f"{f'color: {color};' if color else ''}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ctrl = AppController()
        self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}")
        self.setWindowIcon(app_icon())
        self.resize(1680, 1000)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        mid = QHBoxLayout()
        mid.setSpacing(0)
        mid.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        mid.addWidget(self.stack, 1)
        self.params = ParamPanel(self.ctrl)
        mid.addWidget(self.params)
        root.addLayout(mid, 1)
        self.setCentralWidget(central)
        self._build_statusbar()
        self._build_pages()
        self._wire()
        self._shortcuts()
        self.nav.setCurrentRow(0)
        self._refresh_state()
        self.ctrl.request_forecast()

    # ------------------------------------------------------------ побудова
    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("EARTHCHARGE LAB", "Brand"))
        brand.addWidget(label(APP_SUBTITLE.upper(), "BrandSub"))
        row.addLayout(brand)
        row.addSpacing(18)
        self.chips = {
            "mode": Chip("Режим"), "power": Chip("Потужність"), "voltage": Chip("Напруга"), "current": Chip("Струм"),
            "mg": Chip("Залишок магнію"), "runtime": Chip("Прогноз роботи"), "time": Chip("Час моделі"),
        }
        self.chips["mode"].setMinimumWidth(190)
        for c in self.chips.values():
            row.addWidget(c)
        row.addStretch(1)
        lay.addLayout(row)
        ctl = QHBoxLayout()
        ctl.setSpacing(8)
        self.btn_activate = QPushButton("▶  Активувати")
        self.btn_activate.setObjectName("Primary")
        self.btn_pause = QPushButton("⏸  Пауза")
        self.btn_finish = QPushButton("⏭  До кінця")
        self.btn_reset = QPushButton("■  Скинути")
        self.btn_restart = QPushButton("↻  Перезапустити")
        for b in (self.btn_activate, self.btn_pause, self.btn_finish, self.btn_reset, self.btn_restart):
            ctl.addWidget(b)
        ctl.addSpacing(10)
        ctl.addWidget(label("Прискорення:", "Muted"))
        self.speed_group = QButtonGroup(self)
        for sp in AppController.SPEEDS:
            b = QPushButton(f"×{sp}")
            b.setObjectName("Speed")
            b.setCheckable(True)
            b.setChecked(sp == self.ctrl.speed)
            self.speed_group.addButton(b, sp)
            ctl.addWidget(b)
        ctl.addSpacing(10)
        self.dirty_label = label("", "")
        self.dirty_label.setStyleSheet(f"color: {T.WARNING};")
        ctl.addWidget(self.dirty_label)
        ctl.addStretch(1)
        self.btn_open = QPushButton("Відкрити сценарій")
        self.btn_save = QPushButton("Зберегти сценарій")
        self.btn_export = QToolButton()
        self.btn_export.setText("Експорт ▾")
        self.btn_export.setPopupMode(QToolButton.InstantPopup)
        self.btn_export.setStyleSheet(f"QToolButton {{ background: {T.PANEL_2}; border: 1px solid {T.BORDER_2}; "
                                      f"border-radius: 8px; padding: 6px 12px; color: {T.TEXT}; }}")
        menu = QMenu(self)
        self.act_csv = QAction("Часові ряди симуляції (CSV)…", self)
        self.act_csv_sum = QAction("Підсумки та енергобаланс (CSV)…", self)
        self.act_pdf = QAction("Звіт PDF…", self)
        menu.addAction(self.act_csv)
        menu.addAction(self.act_csv_sum)
        menu.addSeparator()
        menu.addAction(self.act_pdf)
        self.btn_export.setMenu(menu)
        for b in (self.btn_open, self.btn_save):
            ctl.addWidget(b)
        ctl.addWidget(self.btn_export)
        self.btn_panel = QPushButton("Параметри ▸")
        self.btn_panel.setCheckable(True)
        self.btn_panel.setChecked(True)
        self.btn_panel.setToolTip("Показати або сховати панель параметрів конструкції")
        ctl.addWidget(self.btn_panel)
        lay.addLayout(ctl)
        return bar

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(8, 14, 8, 14)
        lay.setSpacing(6)
        lay.addWidget(label("  НАВІГАЦІЯ", "KpiCaption"))
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(20, 20))
        lay.addWidget(self.nav, 1)
        self.forecast_box = label("", "Muted", wrap=True)
        self.forecast_box.setStyleSheet(f"color: {T.MUTED}; padding: 8px; background: {T.PANEL}; border: 1px solid {T.BORDER}; border-radius: 10px;")
        self.forecast_box.setTextFormat(Qt.RichText)
        lay.addWidget(self.forecast_box)
        lay.addWidget(label(f"  v{APP_VERSION} · локальна програма", "Muted"))
        return side

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.setStyleSheet(f"QStatusBar {{ background: {T.PANEL}; border-top: 1px solid {T.BORDER}; color: {T.TEXT_2}; }}")
        self.busy = QProgressBar()
        self.busy.setMaximumWidth(220)
        self.busy.setRange(0, 0)
        self.busy.setVisible(False)
        self.busy_label = label("", "Secondary")
        sb.addPermanentWidget(self.busy_label)
        sb.addPermanentWidget(self.busy)

    def _build_pages(self) -> None:
        from .pages.charging import ChargingPage
        from .pages.compare import ComparePage
        from .pages.constructor import ConstructorPage
        from .pages.dashboard import DashboardPage
        from .pages.economics import EconomicsPage
        from .pages.lab import LabPage
        from .pages.model import ModelPage
        from .pages.sizing import SizingPage
        from .pages.smartboost import SmartBoostPage
        spec = [("Генератор", "bolt", DashboardPage), ("Конструктор", "layers", ConstructorPage),
                ("Зарядити смартфон", "phone", ChargingPage), ("SmartBoost", "cap", SmartBoostPage),
                ("Порівняння", "compare", ComparePage), ("Підбір під 7 год", "target", SizingPage),
                ("Лабораторія", "flask", LabPage), ("Економіка", "coin", EconomicsPage),
                ("Модель і перевірки", "check", ModelPage)]
        self.pages = []
        for name, icon, cls in spec:
            page = cls(self.ctrl)
            self.pages.append(page)
            self.stack.addWidget(page)
            it = QListWidgetItem(nav_icon(icon), "  " + name)
            self.nav.addItem(it)

    def _wire(self) -> None:
        c = self.ctrl
        self.nav.currentRowChanged.connect(self._on_nav)
        self.btn_activate.clicked.connect(self._on_activate)
        self.btn_pause.clicked.connect(c.pause)
        self.btn_finish.clicked.connect(c.run_to_end)
        self.btn_reset.clicked.connect(c.reset)
        self.btn_restart.clicked.connect(c.restart)
        self.speed_group.idClicked.connect(c.set_speed)
        self.btn_panel.toggled.connect(self._panel_toggled)
        self.btn_open.clicked.connect(self.open_scenario)
        self.btn_save.clicked.connect(self.save_scenario)
        self.act_csv.triggered.connect(self.export_csv)
        self.act_csv_sum.triggered.connect(self.export_summary)
        self.act_pdf.triggered.connect(self.export_pdf)
        c.sim_updated.connect(self._on_sim_updated)
        c.sim_started.connect(self._on_sim_updated)
        c.sim_reset.connect(self._on_sim_reset)
        c.state_changed.connect(self._refresh_state)
        c.scenario_changed.connect(self._on_scenario_changed)
        c.message.connect(self._on_message)
        c.busy_changed.connect(self._on_busy)
        c.forecast_ready.connect(self._on_forecast)
        c.forecast_failed.connect(lambda m: self.forecast_box.setText(f"<b>Прогноз</b><br>недоступний: {m.splitlines()[0]}"))
        c.sim_finished.connect(lambda: self._on_message("info", "Симуляцію завершено: " + (c.sim.finish_reason if c.sim else "")))

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_scenario)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_scenario)
        QShortcut(QKeySequence("F5"), self, activated=self._on_activate)
        QShortcut(QKeySequence("F6"), self, activated=self.ctrl.pause)

    # ------------------------------------------------------------ навігація
    def current_page(self):
        return self.pages[self.stack.currentIndex()] if self.pages else None

    def _on_nav(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        page = self.pages[row]
        self.params.setVisible(page.uses_param_panel and self.btn_panel.isChecked())
        self.btn_panel.setEnabled(page.uses_param_panel)
        page.on_shown()

    def _panel_toggled(self, on: bool) -> None:
        page = self.current_page()
        self.params.setVisible(on and (page is None or page.uses_param_panel))
        self.btn_panel.setText("Параметри ▸" if on else "◂ Параметри")

    def go_to(self, cls_name: str) -> None:
        for k, p in enumerate(self.pages):
            if type(p).__name__ == cls_name:
                self.nav.setCurrentRow(k)

    # ------------------------------------------------------------ симуляція
    def _on_activate(self) -> None:
        c = self.ctrl
        if c.sim is not None and c.running:
            return
        if c.sim is not None and not c.sim.finished and not c.params_dirty:
            c.resume()
        else:
            c.reset()
            c.activate()

    def _on_sim_updated(self) -> None:
        self._refresh_kpis()
        page = self.current_page()
        if page is not None:
            page.refresh_live()

    def _on_sim_reset(self) -> None:
        self._refresh_kpis()
        page = self.current_page()
        if page is not None:
            page.refresh_live()

    def _on_scenario_changed(self, source: str) -> None:
        page = self.current_page()
        if page is not None:
            page.on_scenario_changed()
        self._refresh_state()

    def _refresh_state(self) -> None:
        c = self.ctrl
        has = c.sim is not None
        finished = has and c.sim.finished
        self.btn_activate.setText("▶  Продовжити" if (has and not finished and not c.running and not c.params_dirty) else "▶  Активувати")
        self.btn_activate.setEnabled(not c.running)
        self.btn_pause.setEnabled(c.running)
        self.btn_reset.setEnabled(has)
        self.btn_restart.setEnabled(True)
        b = self.speed_group.button(c.speed)
        if b:
            b.setChecked(True)
        self.dirty_label.setText("Параметри змінено — натисніть «Перезапустити», щоб застосувати"
                                 if (has and c.params_dirty) else "")
        self._refresh_kpis()

    def _refresh_kpis(self) -> None:
        c = self.ctrl
        sim = c.sim
        mode_txt = LOAD_MODES.get(c.scenario.sim.load_mode, "")
        if sim is None:
            self.chips["mode"].set("Очікування")
            self.chips["mode"].setToolTip(mode_txt)
            for k in ("power", "voltage", "current", "time"):
                self.chips[k].set("—")
            fc = c.forecast
            if fc is not None:
                self.chips["mg"].set(f"{fmt(fc.mg0_cell_g * fc.n, 1)} г")
            else:
                self.chips["mg"].set("—")
            self.chips["runtime"].set("—")
            return
        r = sim.rec
        if sim.finished:
            state, color = "Завершено", T.TEXT_2
        elif c.running:
            state, color = f"Працює ×{c.speed}", T.GOOD
        else:
            state, color = "Пауза", T.WARNING
        self.chips["mode"].set(state, color)
        self.chips["mode"].setToolTip(f"{state}: {LOAD_MODES.get(sim.mode, sim.mode)}")
        p = r.last("p_usb") if sim.mode in ("phone", "usb_power", "mppt") else r.last("p_term")
        self.chips["power"].set(f"{fmt(p, 2)} Вт")
        self.chips["voltage"].set(f"{fmt(r.last('v_term'), 2)} В")
        self.chips["current"].set(f"{fmt(r.last('i_ext'), 2)} А")
        mg = r.last("mg_remaining_g")
        mg0 = sim.mg0_cell_g * sim.n
        self.chips["mg"].set(f"{fmt(mg, 1)} г · {fmt(100 * mg / mg0 if mg0 else 0, 0)} %")
        rt = sim.forecast_runtime_s()
        self.chips["runtime"].set("—" if (sim.finished or not math.isfinite(rt)) else ("> 100 год" if rt > 360000 else format_duration(rt)))
        self.chips["time"].set(format_duration(sim.state.t))

    def _on_forecast(self, sim) -> None:
        s = sim.summary()
        lines = [f"<b style='color:{T.TEXT}'>Швидкий прогноз</b>"]
        if sim.mode == "phone":
            if s.get("phone_done"):
                lines.append(f"<span style='color:{T.GOOD}'>✔ телефон: {s['phone_t_done_s'] and format_duration(s['phone_t_done_s'])}</span>")
            else:
                lines.append(f"<span style='color:{T.CRITICAL}'>✖ телефон: {fmt(s['phone_soc_pct'], 0)} % за "
                             f"{fmt(sim.sc.phone.max_time_h, 1)} год</span>")
        lines.append(f"USB-C: {fmt(s['e_usb_wh'], 1)} Вт·год")
        lines.append(f"Mg витрачено: {fmt(s['mg_consumed_g'], 1)} г")
        lines.append(f"Пік температури: {fmt(s['peak_t_el'], 0)} °C")
        lines.append(f"<span style='color:{T.MUTED}'>оціночна модель, оновлюється при зміні параметрів</span>")
        self.forecast_box.setText("<br>".join(lines))
        if self.ctrl.sim is None:
            self._refresh_kpis()

    def _on_message(self, level: str, text: str) -> None:
        color = T.LEVEL_COLORS.get(level, T.TEXT_2)
        self.statusBar().setStyleSheet(f"QStatusBar {{ background: {T.PANEL}; border-top: 1px solid {T.BORDER}; color: {color}; }}")
        self.statusBar().showMessage(f"{T.LEVEL_ICONS.get(level, '')}  {text}", 12000)
        if level == "critical" and "\n" in text:
            QMessageBox.warning(self, APP_NAME, text)

    def _on_busy(self, busy: bool, title: str) -> None:
        self.busy.setVisible(busy)
        self.busy_label.setText(title if busy else "")

    # ------------------------------------------------------------ файли
    def open_scenario(self) -> None:
        start = SCENARIO_DIR if any(SCENARIO_DIR.glob("*.json")) else EXAMPLES_DIR
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити сценарій", str(start), "Сценарій EarthCharge (*.json)")
        if not path:
            return
        try:
            sc, prices, phys = load_scenario(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Не вдалося відкрити сценарій:\n{exc}")
            return
        self.ctrl.scenario_path = Path(path)
        self.ctrl.replace_scenario(sc, prices, phys)
        self._on_message("ok", f"Сценарій завантажено: {Path(path).name}")

    def save_scenario(self) -> None:
        default = self.ctrl.scenario_path or (SCENARIO_DIR / f"{self.ctrl.scenario.design.name}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти сценарій", str(default), "Сценарій EarthCharge (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        save_scenario(path, self.ctrl.scenario, self.ctrl.prices, self.ctrl.phys_manual)
        self.ctrl.scenario_path = Path(path)
        self._on_message("ok", f"Сценарій збережено: {path}")

    def _sim_for_export(self):
        sim = self.ctrl.sim or self.ctrl.forecast
        if sim is None:
            QMessageBox.information(self, APP_NAME, "Немає результатів: запустіть симуляцію або дочекайтеся прогнозу.")
        return sim

    def export_csv(self) -> None:
        from ..export.csv_export import downsample_every, simulation_csv, write_text
        sim = self._sim_for_export()
        if sim is None:
            return
        path, flt = QFileDialog.getSaveFileName(self, "Експорт CSV", str(EXPORT_DIR / "earthcharge_simulation.csv"),
                                                "Excel (Україна): «;» і кома (*.csv);;Стандартний CSV: «,» і крапка (*.csv)")
        if not path:
            return
        excel = flt.startswith("Excel")
        write_text(path, simulation_csv(sim, excel_ua=excel, every=downsample_every(sim.rec.n)))
        self._on_message("ok", f"CSV збережено: {path}")

    def export_summary(self) -> None:
        from ..export.csv_export import summary_csv, write_text
        sim = self._sim_for_export()
        if sim is None:
            return
        path, flt = QFileDialog.getSaveFileName(self, "Експорт підсумків", str(EXPORT_DIR / "earthcharge_summary.csv"),
                                                "Excel (Україна): «;» і кома (*.csv);;Стандартний CSV: «,» і крапка (*.csv)")
        if not path:
            return
        write_text(path, summary_csv(sim, excel_ua=flt.startswith("Excel")))
        self._on_message("ok", f"CSV збережено: {path}")

    def export_pdf(self) -> None:
        from ..export.pdf_report import build_report
        sim = self._sim_for_export()
        if sim is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Звіт PDF", str(EXPORT_DIR / "earthcharge_report.pdf"), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            build_report(path, self.ctrl, sim)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Не вдалося створити PDF:\n{exc}")
            return
        self._on_message("ok", f"Звіт PDF збережено: {path}")

    def closeEvent(self, e) -> None:
        self.ctrl.shutdown()
        super().closeEvent(e)
