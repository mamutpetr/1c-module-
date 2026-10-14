"""Права панель: параметри конструкції генератора."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLineEdit, QScrollArea, QToolButton, QVBoxLayout, QWidget

from .. import theme as T
from ...core import materials as M
from ...core.analysis import analyze
from ...core.design import validate_design
from ...core.units import fmt
from .common import BoundForm, Field, VerdictList, label

ANODE_CHOICES = tuple((k, a.name) for k, a in M.ANODES.items())
CATHODE_CHOICES = tuple((k, c.name) for k, c in M.CATHODES.items())
ELECTROLYTE_CHOICES = tuple((k, e.name) for k, e in M.ELECTROLYTES.items())
SEPARATOR_CHOICES = tuple((k, s.name) for k, s in M.SEPARATORS.items())

SECTIONS = [
    ("Анод (магній)", [
        Field("design.anode", "Матеріал анода", "choice", choices=ANODE_CHOICES),
        Field("design.geometry.plate_length_mm", "Довжина пластини", lo=5, hi=500, step=5, decimals=1, suffix="мм"),
        Field("design.geometry.plate_width_mm", "Ширина пластини", lo=5, hi=500, step=5, decimals=1, suffix="мм"),
        Field("design.geometry.mass_mode", "Задаю", "choice", choices=(("thickness", "товщину пластини"), ("mass", "загальну масу Mg"))),
        Field("design.geometry.plate_thickness_mm", "Товщина пластини", lo=0.05, hi=20, step=0.1, decimals=2, suffix="мм"),
        Field("design.geometry.target_total_mass_g", "Загальна маса Mg", lo=0.1, hi=5000, step=1, decimals=1, suffix="г"),
        Field("design.geometry.faces", "Робочі сторони анода", "choice", choices=((2, "дві (катод з обох боків)"), (1, "одна (тил ізольовано)"))),
        Field("design.geometry.active_fraction", "Активна частка площі", lo=1, hi=100, step=1, decimals=0, suffix="%", scale=100.0,
              tip="Частина пластини, відкрита електроліту (решта — рамка, кріплення, контакт)."),
        Field("design.geometry.area_override_cm2", "Активна площа вручну", lo=0, hi=5000, step=5, decimals=1, suffix="см²",
              tip="0 — обчислюється з розмірів пластини. Інакше — активна площа анода на одну комірку."),
        Field("design.geometry.max_utilization", "Допустиме використання Mg", lo=10, hi=100, step=1, decimals=0, suffix="%", scale=100.0,
              tip="Частка маси пластини, яку можна розчинити до перфорації й втрати контакту."),
        Field("design.geometry.contact_resistance_mohm", "Опір контактів комірки", lo=0, hi=1000, step=1, decimals=1, suffix="мОм"),
    ]),
    ("Катод і доступ повітря", [
        Field("design.cathode", "Тип катода", "choice", choices=CATHODE_CHOICES),
        Field("design.geometry.cathode_area_ratio", "Площа катода / площа анода", lo=0.1, hi=5, step=0.1, decimals=2),
        Field("design.environment.air_access", "Доступ повітря", "choice", choices=(("open", "катоди відкриті"), ("vents", "через отвори корпусу"))),
        Field("design.environment.vent_area_cm2", "Площа вентиляційних отворів", lo=0.01, hi=1000, step=0.5, decimals=2, suffix="см²"),
        Field("design.environment.vent_length_mm", "Довжина каналу отворів", lo=0.1, hi=100, step=0.5, decimals=1, suffix="мм"),
    ]),
    ("Електроліт і зазор", [
        Field("design.electrolyte", "Електроліт", "choice", choices=ELECTROLYTE_CHOICES),
        Field("design.separator", "Сепаратор", "choice", choices=SEPARATOR_CHOICES),
        Field("design.geometry.gap_mm", "Відстань анод — катод", lo=0.2, hi=30, step=0.5, decimals=1, suffix="мм"),
        Field("design.geometry.electrolyte_volume_ml", "Об'єм електроліту на комірку", lo=1, hi=5000, step=5, decimals=0, suffix="мл"),
    ]),
    ("Батарея комірок", [
        Field("design.stack.connection", "З'єднання", "choice", choices=(("series", "послідовне"), ("parallel", "паралельне"), ("mixed", "змішане (S × P)"))),
        Field("design.stack.n_cells", "Кількість комірок", "int", lo=1, hi=64),
        Field("design.stack.n_series", "Послідовно (S)", "int", lo=1, hi=32),
        Field("design.stack.n_parallel", "Паралельно (P)", "int", lo=1, hi=16),
        Field("design.stack.wiring_resistance_mohm", "Опір з'єднань", lo=0, hi=2000, step=1, decimals=1, suffix="мОм"),
        Field("design.stack.shared_electrolyte", "Спільний електроліт (одна ванна)", "bool",
              tip="При послідовному з'єднанні виникають шунтувальні струми через електроліт."),
        Field("design.stack.shunt_path_mm", "Довжина шунтувального шляху", lo=1, hi=500, step=1, decimals=0, suffix="мм"),
        Field("design.stack.shunt_cross_section_cm2", "Переріз шунтувального шляху", lo=0.01, hi=100, step=0.1, decimals=2, suffix="см²"),
    ]),
    ("Електронний перетворювач", [
        Field("design.converter.enabled", "DC/DC перетворювач на USB-C", "bool"),
        Field("design.converter.control", "Керування", "choice", choices=(("mppt", "регулювання входу (MPPT)"), ("simple", "простий boost з UVLO"))),
        Field("design.converter.efficiency_pct", "ККД", lo=10, hi=100, step=1, decimals=1, suffix="%"),
        Field("design.converter.quiescent_mw", "Власне споживання", lo=0, hi=2000, step=5, decimals=0, suffix="мВт"),
        Field("design.converter.v_in_min", "Мінімальна вхідна напруга", lo=0.1, hi=24, step=0.1, decimals=2, suffix="В"),
        Field("design.converter.i_in_max_a", "Максимальний вхідний струм", lo=0.05, hi=50, step=0.5, decimals=2, suffix="А"),
        Field("design.converter.input_resistance_mohm", "Опір вхідного кола", lo=0, hi=2000, step=5, decimals=0, suffix="мОм"),
        Field("design.converter.v_out", "Вихідна напруга USB", lo=3, hi=20, step=0.1, decimals=2, suffix="В"),
        Field("design.converter.p_out_max_w", "Обмеження вихідної потужності", lo=0.1, hi=100, step=0.5, decimals=1, suffix="Вт",
              tip="Обмеження потужності утримує комірки в ефективнішій зоні ВАХ і зменшує нагрів."),
    ]),
    ("Суперконденсатор (SmartBoost)", [
        Field("design.supercap.enabled", "Встановлено суперконденсатор", "bool"),
        Field("design.supercap.capacitance_f", "Ємність", lo=0.1, hi=3000, step=1, decimals=1, suffix="Ф"),
        Field("design.supercap.v_max", "Допустима напруга", lo=0.5, hi=60, step=0.1, decimals=2, suffix="В"),
        Field("design.supercap.start_delay_s", "Запуск USB-C через", lo=0, hi=300, step=5, decimals=0, suffix="с"),
    ]),
    ("Середовище й безпека", [
        Field("design.environment.ambient_c", "Температура середовища", lo=-40, hi=80, step=1, decimals=1, suffix="°C"),
        Field("design.environment.relative_humidity_pct", "Відносна вологість", lo=0, hi=100, step=5, decimals=0, suffix="%"),
        Field("design.environment.thermal_model", "Тепловий розрахунок (нагрів електроліту)", "bool"),
        Field("design.environment.heat_area_override_cm2", "Поверхня тепловіддачі вручну", lo=0, hi=20000, step=10, decimals=0, suffix="см²",
              tip="0 — оцінка з габаритів батареї комірок."),
        Field("design.environment.enclosure_free_volume_ml", "Вільний об'єм корпусу", lo=1, hi=100000, step=10, decimals=0, suffix="мл"),
        Field("design.environment.air_exchange_per_h", "Повітрообмін корпусу", lo=0, hi=100000, step=10, decimals=0, suffix="1/год",
              tip="Кратність обміну повітря у вільному об'ємі (для оцінки концентрації H₂). Припущення."),
    ]),
]


class Section(QWidget):
    def __init__(self, title: str, body: QWidget, expanded: bool = True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.btn = QToolButton()
        self.btn.setText(title.upper())
        self.btn.setCheckable(True)
        self.btn.setChecked(expanded)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.btn.setStyleSheet(f"QToolButton {{ color: {T.TEXT_2}; font-size: 8.5pt; letter-spacing: 1px; }}")
        self.btn.toggled.connect(self._toggle)
        lay.addWidget(self.btn)
        self.body = body
        lay.addWidget(body)
        body.setVisible(expanded)

    def _toggle(self, on: bool) -> None:
        self.body.setVisible(on)
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


class ParamPanel(QFrame):
    changed = Signal(str)

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setObjectName("RightPanel")
        self.setMinimumWidth(340)
        self.setMaximumWidth(400)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QVBoxLayout()
        head.setContentsMargins(16, 14, 16, 6)
        head.addWidget(label("КОНСТРУКЦІЯ ГЕНЕРАТОРА", "KpiCaption"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Назва варіанта")
        self.name_edit.editingFinished.connect(self._name_changed)
        head.addWidget(self.name_edit)
        self.summary = label("", "Secondary", wrap=True)
        head.addWidget(self.summary)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 4, 16, 16)
        lay.setSpacing(10)
        self.forms: list[BoundForm] = []
        self.notes: dict = {}
        for k, (title, fields) in enumerate(SECTIONS):
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            form = BoundForm(fields, lambda: self.ctrl.scenario, label_width=130)
            form.changed.connect(self._on_change)
            bl.addWidget(form)
            note = label("", "Muted", wrap=True)
            note.setTextFormat(Qt.RichText)
            bl.addWidget(note)
            self.notes[title] = note
            self.forms.append(form)
            lay.addWidget(Section(title, body, expanded=k < 4))
        lay.addWidget(label("ПЕРЕВІРКА ВВЕДЕННЯ", "KpiCaption"))
        self.issues = VerdictList()
        lay.addWidget(self.issues)
        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        ctrl.scenario_changed.connect(self._on_external_change)
        ctrl.scenario_replaced.connect(self.reload)
        self.reload()

    # ------------------------------------------------------------ події
    def _name_changed(self) -> None:
        self.ctrl.scenario.design.name = self.name_edit.text().strip() or "Варіант"
        self.ctrl.notify_changed("design.name")

    def _on_change(self, path: str) -> None:
        d = self.ctrl.scenario.design
        group = {"design.anode": "anode.", "design.cathode": "cathode.", "design.electrolyte": "electrolyte.",
                 "design.separator": "separator."}.get(path)
        if group:
            dropped = [k for k in d.overrides if k.startswith(group)]
            for k in dropped:
                d.overrides.pop(k)
            if dropped:
                self.ctrl.message.emit("info", "Матеріал змінено: скинуто калібрування й ручні значення для "
                                               f"{len(dropped)} параметрів попереднього матеріалу.")
        self._update_visibility()
        self._update_info()
        self._own_source = path
        try:
            self.ctrl.notify_changed(path)
        finally:
            self._own_source = None

    def _on_external_change(self, source: str) -> None:
        if source and source == getattr(self, "_own_source", None):
            return
        self.reload()

    def reload(self) -> None:
        self.name_edit.setText(self.ctrl.scenario.design.name)
        for f in self.forms:
            f.load()
        self._update_visibility()
        self._update_info()

    def _form_of(self, path: str) -> BoundForm | None:
        for f in self.forms:
            if path in f.widgets:
                return f
        return None

    def _vis(self, path: str, on: bool) -> None:
        f = self._form_of(path)
        if f:
            f.set_visible(path, on)

    def _update_visibility(self) -> None:
        d = self.ctrl.scenario.design
        self._vis("design.geometry.plate_thickness_mm", d.geometry.mass_mode == "thickness")
        self._vis("design.geometry.target_total_mass_g", d.geometry.mass_mode == "mass")
        mixed = d.stack.connection == "mixed"
        self._vis("design.stack.n_cells", not mixed)
        self._vis("design.stack.n_series", mixed)
        self._vis("design.stack.n_parallel", mixed)
        self._vis("design.stack.shunt_path_mm", d.stack.shared_electrolyte)
        self._vis("design.stack.shunt_cross_section_cm2", d.stack.shared_electrolyte)
        vents = d.environment.air_access == "vents"
        self._vis("design.environment.vent_area_cm2", vents)
        self._vis("design.environment.vent_length_mm", vents)
        conv = d.converter.enabled
        for p in ("control", "efficiency_pct", "quiescent_mw", "v_in_min", "i_in_max_a", "input_resistance_mohm", "v_out", "p_out_max_w"):
            self._vis(f"design.converter.{p}", conv)
        sc = d.supercap.enabled
        for p in ("capacitance_f", "v_max", "start_delay_s"):
            self._vis(f"design.supercap.{p}", sc)

    def _update_info(self) -> None:
        d = self.ctrl.scenario.design
        an, cat, el = M.ANODES[d.anode], M.CATHODES[d.cathode], M.ELECTROLYTES[d.electrolyte]
        warn = lambda t: f"<span style='color:{T.WARNING}'>▲ {t}</span>"
        self.notes["Анод (магній)"].setText("<br>".join(x for x in (an.note, warn(an.warning) if an.warning else "") if x))
        self.notes["Катод і доступ повітря"].setText("<br>".join(x for x in (
            f"Категорія: {M.CATEGORY_LABELS[cat.category]}", cat.note, warn(cat.warning) if cat.warning else "") if x))
        self.notes["Електроліт і зазор"].setText("<br>".join(x for x in (el.note, warn(el.warning) if el.warning else "") if x))
        issues = validate_design(d)
        self.issues.set_items([(i.level if i.level != "error" else "critical", i.message) for i in issues]
                              or [("ok", "Помилок введення немає.")])
        if any(i.level == "error" for i in issues):
            self.summary.setText("Виправте помилки введення, щоб отримати розрахунок.")
            return
        try:
            a = analyze(d)
        except Exception as exc:  # noqa: BLE001
            self.summary.setText(f"Помилка аналізу: {exc}")
            return
        g = a.geo
        self.summary.setText(
            f"{g.n_series} посл. × {g.n_parallel} пар. · Mg {fmt(g.total_mass_g, 1)} г · "
            f"анод {fmt(g.anode_area_cm2, 0)} см²/комірку · НРК {fmt(a.ocv_stack, 2)} В · "
            f"макс. USB {fmt(a.p_max_usb_w, 2)} Вт")
