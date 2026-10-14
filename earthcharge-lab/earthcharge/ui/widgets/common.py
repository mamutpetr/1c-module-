"""Спільні віджети: картки, KPI-плитки, графіки з підказками, форми, прив'язані до сценарію."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .. import theme as T
from ...core.units import fmt

UA_LOCALE = QLocale(QLocale.Ukrainian, QLocale.Ukraine)


def label(text: str, kind: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if kind:
        lb.setObjectName(kind)
    lb.setWordWrap(wrap)
    return lb


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(8)
        if title:
            head = QHBoxLayout()
            head.setSpacing(8)
            self.title = label(title, "H2")
            head.addWidget(self.title)
            head.addStretch(1)
            self.head_right = QHBoxLayout()
            self.head_right.setSpacing(6)
            head.addLayout(self.head_right)
            self.lay.addLayout(head)
        if subtitle:
            self.subtitle = label(subtitle, "Muted", wrap=True)
            self.lay.addWidget(self.subtitle)
        # хвостовий розпірник: вміст притиснуто догори, доки віджет не попросить розтягування
        self.lay.addStretch(0)

    def add(self, w, stretch: int = 0):
        pos = self.lay.count() - 1
        if isinstance(w, QWidget):
            self.lay.insertWidget(pos, w, stretch)
        else:
            self.lay.insertLayout(pos, w, stretch)
        return w


class Badge(QLabel):
    def __init__(self, text: str = "", color: str = T.TEXT_2, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.set(text, color)

    def set(self, text: str, color: str) -> None:
        self.setText(text)
        self.setStyleSheet(T.badge_style(color))


class KpiTile(QFrame):
    def __init__(self, caption: str, unit: str = "", parent=None, compact: bool = False):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8 if compact else 10, 12, 8 if compact else 10)
        lay.setSpacing(2)
        self.cap = label(caption.upper(), "KpiCaption", wrap=True)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.value = label("—", "KpiValue")
        self.unit = label(unit, "Muted")
        row.addWidget(self.value)
        row.addWidget(self.unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        self.sub = label("", "Muted")
        lay.addWidget(self.cap)
        lay.addLayout(row)
        lay.addWidget(self.sub)
        self.sub.setVisible(False)

    def set(self, value: str, sub: str | None = None, color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f"{v:g}".replace(".", ",") for v in values]


class ChartCard(QFrame):
    """Графік у картці: заголовок, легенда (для ≥ 2 рядів), перехрестя з підказкою значень."""

    def __init__(self, title: str, y_unit: str, x_label: str = "Час, год", parent=None, height: int = 200):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.title = label(title, "H3")
        head.addWidget(self.title)
        head.addStretch(1)
        self.readout = label("", "Muted")
        self.readout.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.readout, 1)
        lay.addLayout(head)
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setVisible(False)
        lay.addWidget(self.legend)
        self.pw = pg.PlotWidget(axisItems={"bottom": TimeAxis(orientation="bottom"), "left": TimeAxis(orientation="left")})
        self.pw.setMinimumHeight(height)
        self.pw.setMinimumWidth(160)
        self.setMinimumWidth(240)
        self.pw.setBackground(T.PANEL)
        pi = self.pw.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.12)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        for ax in ("left", "bottom"):
            a = pi.getAxis(ax)
            a.setPen(pg.mkPen(T.BORDER_2))
            a.setTextPen(pg.mkPen(T.MUTED))
            f = QFont()
            f.setPointSizeF(8.0)
            a.setTickFont(f)
            a.enableAutoSIPrefix(False)
        pi.getAxis("left").setWidth(48)
        pi.setLabel("bottom", x_label, color=T.MUTED, size="8pt")
        pi.setLabel("left", y_unit, color=T.MUTED, size="8pt")
        self.y_unit = y_unit
        self.x_label = x_label
        lay.addWidget(self.pw)
        self.curves: list = []
        self.names: list = []
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(T.MUTED, width=1, style=Qt.DashLine))
        self.vline.setVisible(False)
        pi.addItem(self.vline, ignoreBounds=True)
        self.dots: list = []
        self._proxy = pg.SignalProxy(self.pw.scene().sigMouseMoved, rateLimit=30, slot=self._on_move)
        self.pw.leaveEvent = self._on_leave

    def add_series(self, name: str, color: str, width: float = 2.0, dash: bool = False, fill: bool = False):
        pen = pg.mkPen(color, width=width, style=Qt.DashLine if dash else Qt.SolidLine)
        c = self.pw.plot([], [], pen=pen, name=name)
        c.setDownsampling(auto=True, method="peak")
        c.setClipToView(True)
        if fill:
            col = QColor(color)
            col.setAlpha(40)
            c.setFillLevel(0)
            c.setBrush(col)
        self.curves.append(c)
        self.names.append(name)
        dot = pg.ScatterPlotItem(size=8, brush=pg.mkBrush(color), pen=pg.mkPen(T.PANEL, width=2))
        dot.setVisible(False)
        self.pw.getPlotItem().addItem(dot, ignoreBounds=True)
        self.dots.append(dot)
        self._rebuild_legend()
        return c

    def _rebuild_legend(self) -> None:
        """Легенда для ≥ 2 рядів: один рядок тексту з кольоровими позначками, що переноситься."""
        if len(self.curves) < 2:
            self.legend.setVisible(False)
            return
        parts = []
        for c, name in zip(self.curves, self.names):
            color = c.opts["pen"].color().name()
            dash = c.opts["pen"].style() == Qt.DashLine
            parts.append(f"<span style='color:{color}; font-weight:700'>{'┅┅' if dash else '━━'}</span>"
                         f"&nbsp;<span style='color:{T.TEXT_2}'>{name}</span>")
        self.legend.setText("&nbsp;&nbsp;&nbsp; ".join(parts))
        self.legend.setVisible(True)

    def set_data(self, idx: int, x, y) -> None:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.size == 0:
            self.curves[idx].setData([], [])
            return
        self.curves[idx].setData(x, y, connect="finite")

    def clear_data(self) -> None:
        for c in self.curves:
            c.setData([], [])
        self.readout.setText("")

    def _on_leave(self, ev) -> None:
        self.vline.setVisible(False)
        for d in self.dots:
            d.setVisible(False)
        self.readout.setText("")

    def _on_move(self, evt) -> None:
        pos = evt[0]
        vb = self.pw.getPlotItem().vb
        if not self.pw.sceneBoundingRect().contains(pos) or not self.curves:
            return
        mp = vb.mapSceneToView(pos)
        parts = []
        shown = False
        for c, d, name in zip(self.curves, self.dots, self.names):
            xd, yd = c.xData, c.yData
            if xd is None or len(xd) == 0:
                d.setVisible(False)
                continue
            k = int(np.clip(np.searchsorted(xd, mp.x()), 0, len(xd) - 1))
            if k > 0 and abs(xd[k - 1] - mp.x()) < abs(xd[k] - mp.x()):
                k -= 1
            xv, yv = float(xd[k]), float(yd[k])
            if not math.isfinite(yv):
                d.setVisible(False)
                continue
            d.setData([xv], [yv])
            d.setVisible(True)
            self.vline.setPos(xv)
            shown = True
            parts.append((name, yv, xv))
        self.vline.setVisible(shown)
        if parts:
            xv = parts[0][2]
            txt = f"{fmt(xv, 2)} {self.x_label.split(',')[-1].strip()}  ·  " + "  ·  ".join(
                f"{n}: {fmt(v, 3 if abs(v) < 10 else 1)}" for n, v, _ in parts)
            self.readout.setText(txt + f" {self.y_unit}")


class VerdictList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not items:
            self.lay.addWidget(label("Ще немає результатів. Запустіть симуляцію.", "Muted", wrap=True))
            return
        for level, text in items:
            color = T.LEVEL_COLORS.get(level, T.TEXT_2)
            row = QFrame()
            row.setObjectName("VerdictRow")
            row.setStyleSheet(f"QFrame#VerdictRow {{ background: {T.PANEL_2}; border-left: 3px solid {color}; border-radius: 6px; }}")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            ic = QLabel(T.LEVEL_ICONS.get(level, "•"))
            ic.setStyleSheet(f"color: {color}; font-weight: 700; background: transparent;")
            ic.setFixedWidth(16)
            tx = QLabel(text)
            tx.setWordWrap(True)
            tx.setStyleSheet("background: transparent;")
            tx.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(ic, 0, Qt.AlignTop)
            h.addWidget(tx, 1)
            self.lay.addWidget(row)


# ---------------------------------------------------------------------------
# Форми, прив'язані до полів сценарію
# ---------------------------------------------------------------------------

@dataclass
class Field:
    path: str                    # напр. "design.geometry.gap_mm"
    label: str
    kind: str = "float"          # float | int | bool | choice
    lo: float = 0.0
    hi: float = 1e6
    step: float = 1.0
    decimals: int = 2
    suffix: str = ""
    tip: str = ""
    choices: tuple = ()          # ((key, label), ...)
    scale: float = 1.0           # відображення = значення × scale (напр. частка -> %)


def get_path(obj, path: str):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


class DoubleSpin(QDoubleSpinBox):
    def __init__(self, f: Field):
        super().__init__()
        self.setLocale(UA_LOCALE)
        self.setRange(f.lo, f.hi)
        self.setDecimals(f.decimals)
        self.setSingleStep(f.step)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignRight)
        if f.suffix:
            self.setSuffix(" " + f.suffix)
        self.setMinimumWidth(80)

    def wheelEvent(self, e):  # не змінювати значення випадковим прокручуванням сторінки
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class IntSpin(QSpinBox):
    def __init__(self, f: Field):
        super().__init__()
        self.setRange(int(f.lo), int(f.hi))
        self.setSingleStep(int(max(1, f.step)))
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignRight)
        if f.suffix:
            self.setSuffix(" " + f.suffix)
        self.setMinimumWidth(96)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class Combo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # довгі назви не розширюють форму: текст обрізається, повна назва — у списку та підказці
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.currentTextChanged.connect(self.setToolTip)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class BoundForm(QWidget):
    """Форма, що редагує поля об'єкта-сценарію за шляхами. Сигнал changed(path)."""
    changed = Signal(str)

    def __init__(self, fields: list[Field], get_root, parent=None, label_width: int = 0):
        super().__init__(parent)
        self.fields = fields
        self.get_root = get_root
        self.widgets: dict = {}
        self.rows: dict = {}
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._loading = False
        for f in fields:
            w = self._make(f)
            lb = label(f.label, "Secondary", wrap=True)
            if label_width:
                lb.setMinimumWidth(label_width)
            if f.tip:
                lb.setToolTip(f.tip)
                w.setToolTip(f.tip)
            self.form.addRow(lb, w)
            self.widgets[f.path] = w
            self.rows[f.path] = lb
        self.load()

    def _make(self, f: Field):
        if f.kind == "float":
            w = DoubleSpin(f)
            w.valueChanged.connect(lambda v, p=f.path, sc=f.scale: self._set(p, float(v) / sc))
        elif f.kind == "int":
            w = IntSpin(f)
            w.valueChanged.connect(lambda v, p=f.path: self._set(p, int(v)))
        elif f.kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda v, p=f.path: self._set(p, bool(v)))
        elif f.kind == "choice":
            w = Combo()
            for key, text in f.choices:
                w.addItem(text, key)
            w.currentIndexChanged.connect(lambda i, p=f.path, ww=w: self._set(p, ww.itemData(i)))
        else:
            raise ValueError(f.kind)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return w

    def _set(self, path: str, value) -> None:
        if self._loading:
            return
        set_path(self.get_root(), path, value)
        self.changed.emit(path)

    def load(self) -> None:
        self._loading = True
        root = self.get_root()
        for f in self.fields:
            w = self.widgets[f.path]
            v = get_path(root, f.path)
            w.blockSignals(True)
            if f.kind == "float":
                w.setValue(float(v) * f.scale)
            elif f.kind == "int":
                w.setValue(int(v))
            elif f.kind == "bool":
                w.setChecked(bool(v))
            elif f.kind == "choice":
                idx = w.findData(v)
                w.setCurrentIndex(max(idx, 0))
            w.blockSignals(False)
        self._loading = False

    def set_visible(self, path: str, visible: bool) -> None:
        self.widgets[path].setVisible(visible)
        self.rows[path].setVisible(visible)

    def set_enabled(self, path: str, enabled: bool) -> None:
        self.widgets[path].setEnabled(enabled)


def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.HLine)
    ln.setStyleSheet(f"color: {T.BORDER}; background: {T.BORDER}; max-height: 1px;")
    return ln


def grid(widgets: list, cols: int, spacing: int = 10) -> QGridLayout:
    g = QGridLayout()
    g.setSpacing(spacing)
    for k, w in enumerate(widgets):
        g.addWidget(w, k // cols, k % cols)
    return g
