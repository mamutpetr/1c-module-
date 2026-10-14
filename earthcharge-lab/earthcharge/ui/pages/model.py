"""Модель і перевірки: усі параметри зі статусом походження, рівняння, самоперевірка."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem)

from .. import theme as T
from ...core.design import clone
from ...core.params import GROUP_LABELS, build_params, clear_override, set_override
from ...core.provenance import STATUS_HINTS, STATUS_LABELS, Status
from ...core.validation import run_model_checks
from ..widgets.common import Card, VerdictList, label
from .base import Page

EQUATIONS = """
<p><b>Напруга комірки.</b> V = (E<sub>катод,спок</sub> − E<sub>анод,НРК</sub>) − η<sub>катод</sub>(i) − η<sub>анод</sub>(i)
− I·(R<sub>ел</sub> + R<sub>пас</sub> + R<sub>кат</sub> + R<sub>конт</sub>).</p>
<p><b>Катод.</b> Відновлення O₂ за Батлером–Фольмером з граничним струмом (Кутецький–Левич):
i<sub>ORR</sub> = i<sub>k</sub>·i<sub>гр</sub>/(i<sub>k</sub> + i<sub>гр</sub>), i<sub>k</sub> = 2i₀·sh(η/b). Якщо кисню бракує,
струм забезпечує виділення H₂ на катоді, і напруга різко падає. Для повітряного катода i<sub>гр</sub> задає каталізатор і подача
повітря через отвори (дифузія за Фіком). Для зануреного графіту i<sub>гр</sub> = 4F·D·C/δ визначає розчинений O₂.</p>
<p><b>Електроліт.</b> R<sub>ел</sub> = d·N<sub>M</sub>/(σ·A), σ(T) = σ<sub>ref</sub>·(1 + α·(T − T<sub>ref</sub>)),
шлам Mg(OH)₂ знижує провідність за Бруггеманом: σ<sub>еф</sub> = σ·(1 − φ)<sup>1,5</sup>.</p>
<p><b>Самокорозія.</b> I<sub>H₂</sub> = A·i<sub>corr0</sub>·f(T)·k<sub>ел</sub> + k<sub>NDE</sub>·k<sub>ел</sub>·I (негативний
різницевий ефект), механічні втрати I<sub>ch</sub> = k<sub>ch</sub>·I. Ефективність анода = I/(I + I<sub>H₂</sub> + I<sub>ch</sub>).</p>
<p><b>Закон Фарадея.</b> dm/dt = (I + I<sub>H₂</sub> + I<sub>ch</sub>)/(F·z̄), z̄ = Σ w<sub>k</sub>·n<sub>k</sub>/M<sub>k</sub> — моль
електронів на грам сплаву (для чистого Mg 2205 мА·год/г, 0,4534 г/(А·год)). Водень: 1 моль H₂ на 2 F корозійного заряду.</p>
<p><b>Пасивація.</b> ASR<sub>пас</sub> = ASR<sub>max</sub>·(1 − exp(−q/q<sub>char</sub>)), q — розчинений заряд на см².</p>
<p><b>Енергетичний баланс.</b> Ідеальна енергія = заряд розчиненого Mg × 3,09 В (ΔG реакції Mg + ½O₂ + H₂O → Mg(OH)₂).
Вона точно розкладається на втрати (корозія, змішаний потенціал, поляризації, опори, шунт, перетворювач, суперконденсатор,
кабель, телефон) і корисний результат. Тепло рахується від термонейтральної напруги 3,31 В і ентальпії корозії.</p>
<p><b>Перетворювач.</b> P<sub>вих</sub> = η·(V·I − I²·R<sub>вх</sub>) − P<sub>q</sub>, з обмеженнями V ≥ V<sub>min</sub>,
I ≤ I<sub>max</sub>, P ≤ P<sub>max</sub>. Режим MPPT утримує точку максимальної потужності; простий boost вимикається при перевантаженні.</p>
"""


class ModelPage(Page):
    title = "Модель і перевірки"
    subtitle = ("Кожен параметр має статус походження. Значення зі статусом «Оціночна модель» — припущення, а не перевірені факти: "
                "уточнюйте їх калібруванням у «Лабораторії».")
    uses_param_panel = False

    def __init__(self, ctrl, parent=None):
        super().__init__(ctrl, parent)
        legend = QHBoxLayout()
        for st in Status:
            chip = QLabel(STATUS_LABELS[st])
            chip.setObjectName("Badge")
            chip.setStyleSheet(T.badge_style(T.STATUS_COLORS[st.value]))
            chip.setToolTip(STATUS_HINTS[st])
            legend.addWidget(chip)
        legend.addStretch(1)
        self.body.addLayout(legend)
        pc = Card("Параметри поточної конструкції", "Подвійне клацання по значенню — змінити (статус стане «Задано користувачем»).")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Група", "Параметр", "Значення", "Одиниці", "Статус", "Джерело / пояснення"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        for col, wdt in enumerate((110, 300, 90, 110, 170)):
            self.table.setColumnWidth(col, wdt)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(520)
        self.table.setWordWrap(True)
        self.table.itemChanged.connect(self._edited)
        pc.add(self.table)
        bl = QHBoxLayout()
        b_reset = QPushButton("Повернути бібліотечне значення для вибраного")
        b_reset.clicked.connect(self._reset_selected)
        b_reset_all = QPushButton("Скинути всі ручні значення та калібрування")
        b_reset_all.clicked.connect(self._reset_all)
        bl.addWidget(b_reset)
        bl.addWidget(b_reset_all)
        bl.addStretch(1)
        pc.add(bl)
        self.summary = label("", "Secondary", wrap=True)
        pc.add(self.summary)
        self.body.addWidget(pc)
        row = self.responsive(QHBoxLayout(), 1000)
        row.setSpacing(14)
        ec = Card("Рівняння моделі")
        eq = label(EQUATIONS, "", wrap=True)
        eq.setTextFormat(Qt.RichText)
        ec.add(eq)
        row.addWidget(ec, 3)
        vc = Card("Самоперевірка моделі", "Закон Фарадея, одиниці, збереження енергії в усьому ланцюгу, межі ефективності.")
        b = QPushButton("Запустити перевірку")
        b.setObjectName("Primary")
        b.clicked.connect(self._run_checks)
        vc.add(b)
        self.checks = VerdictList()
        vc.add(self.checks)
        row.addWidget(vc, 2)
        self.body.addLayout(row)
        self._loading = False

    def on_scenario_changed(self) -> None:
        self._fill()

    def _fill(self) -> None:
        self._loading = True
        ps = build_params(self.ctrl.scenario.design)
        items = list(ps.items())
        self.table.setRowCount(len(items))
        self._keys = []
        counts = {}
        for r, (key, p) in enumerate(items):
            self._keys.append(key)
            counts[p.status] = counts.get(p.status, 0) + 1
            group = GROUP_LABELS.get(key.split(".")[0], key)
            cells = [group, p.label, f"{p.value:.6g}".replace(".", ","), p.unit, STATUS_LABELS[p.status],
                     p.source + (f" Діапазон: {p.lo:g}…{p.hi:g}." if p.lo is not None and p.hi is not None else "")]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c != 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 4:
                    it.setForeground(QColor(T.STATUS_COLORS[p.status.value]))
                if c == 1:
                    it.setToolTip(key)
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()
        total = len(items)
        unc = counts.get(Status.ASSUMPTION, 0) + counts.get(Status.LITERATURE, 0)
        self.summary.setText(
            f"Усього параметрів: {total}. Довідкових: {counts.get(Status.REFERENCE, 0)}, літературний діапазон: "
            f"{counts.get(Status.LITERATURE, 0)}, оціночних припущень: {counts.get(Status.ASSUMPTION, 0)}, "
            f"заданих вручну: {counts.get(Status.USER, 0)}, каліброваних: {counts.get(Status.CALIBRATED, 0)}. "
            f"Прогноз залежить від {unc} неперевірених параметрів — точність обмежена, доки їх не відкалібровано.")
        self._loading = False

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 2:
            return
        key = self._keys[item.row()]
        try:
            v = float(item.text().replace(",", ".").strip())
        except ValueError:
            self.ctrl.message.emit("warning", "Введіть число.")
            self._fill()
            return
        set_override(self.ctrl.scenario.design, key, v, Status.USER, "Введено вручну на сторінці «Модель»")
        self.ctrl.notify_changed("override")
        self._fill()

    def _reset_selected(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        clear_override(self.ctrl.scenario.design, self._keys[r])
        self.ctrl.notify_changed("override")
        self._fill()

    def _reset_all(self) -> None:
        self.ctrl.scenario.design.overrides.clear()
        self.ctrl.notify_changed("override")
        self._fill()

    def _run_checks(self) -> None:
        sc = clone(self.ctrl.scenario)

        def job(progress, cancel):
            return run_model_checks(sc)

        self.ctrl.run_job("Перевірка моделі…", job, self._checks_done)

    def _checks_done(self, checks) -> None:
        passed = sum(c.passed for c in checks)
        items = [("ok" if passed == len(checks) else "critical", f"Пройдено {passed} з {len(checks)} перевірок.")]
        items += [("ok" if c.passed else "critical", f"{c.name}: {c.detail}") for c in checks]
        self.checks.set_items(items)
