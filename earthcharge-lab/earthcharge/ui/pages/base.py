"""Базовий клас сторінки та спільні перетворення даних симуляції для інтерфейсу."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...core.design import LOAD_MODES
from ...core.units import fmt
from ..widgets.common import label


class Page(QWidget):
    title = ""
    subtitle = ""
    uses_param_panel = True

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(22, 16, 22, 8)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label(self.title, "H1"))
        if self.subtitle:
            sub = label(self.subtitle, "Muted", wrap=True)
            tl.addWidget(sub)
        head.addLayout(tl, 1)
        self.head_actions = QHBoxLayout()
        self.head_actions.setSpacing(8)
        head.addLayout(self.head_actions)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(22, 6, 22, 22)
        self.body.setSpacing(14)
        scroll.setWidget(self.content)
        outer.addWidget(scroll, 1)
        self._responsive: list = []

    def responsive(self, box: QBoxLayout, min_width: int) -> QBoxLayout:
        """Рядок, що стає стовпцем, коли сторінка вужча за min_width."""
        self._responsive.append((box, min_width))
        return box

    def resizeEvent(self, e) -> None:
        w = self.width()
        for box, mw in self._responsive:
            box.setDirection(QBoxLayout.LeftToRight if w >= mw else QBoxLayout.TopToBottom)
        super().resizeEvent(e)

    # викликаються головним вікном
    def refresh_live(self) -> None:
        pass

    def on_scenario_changed(self) -> None:
        pass

    def on_shown(self) -> None:
        self.on_scenario_changed()
        self.refresh_live()


def series(sim, key: str) -> np.ndarray:
    return sim.rec.get(key) if sim is not None else np.array([])


def live_values(sim) -> dict:
    """Поточні значення для розрізу комірки, схеми й KPI."""
    if sim is None:
        return {}
    r = sim.rec
    last = lambda k: r.last(k)
    cell = sim.cell
    asr_max = sim.ps.v("anode.pass_asr_max") * sim.ps.v("electrolyte.pass_factor")
    mg0 = sim.mg0_cell_g * sim.n
    mode = sim.mode
    vals = {
        "mg_frac": last("mg_remaining_g") / mg0 if mg0 > 0 else 0.0,
        "h2_ml_min": last("h2_ml_min"), "o2_ml_min": last("o2_ml_min"),
        "i": last("i_ext"), "sludge_pct": last("sludge_pct"),
        "pass_frac": cell.asr_pass / asr_max if asr_max > 0 else 0.0,
        "t_el": last("t_el"), "v_term": last("v_term"), "i_ext": last("i_ext"), "p_term": last("p_term"),
        "p_usb": last("p_usb"), "conv_eff": last("conv_eff"), "usb_on": last("usb_on"),
        "cap_j": last("cap_j"), "cap_v": last("cap_v"), "cap_p": last("cap_p"),
        "p_usb_from_bus": last("p_gen_bus"),
    }
    if mode == "phone":
        vals["load_line"] = f"Заряд {fmt(last('phone_soc'), 1)} %"
        vals["load_line2"] = f"{fmt(last('p_usb'), 2)} Вт"
    elif mode in ("usb_power", "mppt"):
        vals["load_line"] = LOAD_MODES.get(mode, mode)[:22]
        vals["load_line2"] = f"{fmt(last('p_usb'), 2)} Вт"
    else:
        vals["load_line"] = "навантаження на виводах"
        vals["load_line2"] = f"{fmt(last('p_term'), 2)} Вт"
    return vals


def load_label(mode: str) -> str:
    return {"phone": "Телефон", "usb_power": "Навантаження USB", "mppt": "Навантаження MPPT",
            "resistor": "Резистор", "current": "Електронне навантаження", "open": "Розімкнено"}.get(mode, mode)


def safe(x: float, default: float = 0.0) -> float:
    return x if (x is not None and isinstance(x, (int, float)) and math.isfinite(x)) else default
