"""Схематичний розріз комірки та схема енергосистеми з анімацією потоків."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme as T
from ...core import materials as M
from ...core.design import Design, stack_counts
from ...core.units import fmt


def _mix(c1: str, c2: str, t: float) -> QColor:
    a, b = QColor(c1), QColor(c2)
    t = min(max(t, 0.0), 1.0)
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class CellCrossSection(QWidget):
    def __init__(self, parent=None, show_labels: bool = True):
        super().__init__(parent)
        self.show_labels = show_labels
        self.setMinimumSize(420, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.design: Design | None = None
        self.live = {"mg_frac": 1.0, "h2_ml_min": 0.0, "o2_ml_min": 0.0, "i": 0.0, "sludge_pct": 0.0,
                     "pass_frac": 0.0, "t_el": 25.0, "v": 0.0}
        self.running = False
        self.bubbles: list = []
        self.o2: list = []
        self.electrons: list = []
        self.phase = 0.0
        self.rng = random.Random(3)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._animate)

    # ------------------------------------------------------------ дані
    def set_design(self, design: Design) -> None:
        self.design = design
        self.update()

    def set_live(self, values: dict, running: bool) -> None:
        self.live.update({k: v for k, v in values.items() if v is not None and v == v})
        self.running = running
        if running and not self.timer.isActive() and self.isVisible():
            self.timer.start()
        if not running:
            self.timer.stop()
        self.update()

    def reset_live(self) -> None:
        self.live.update({"mg_frac": 1.0, "h2_ml_min": 0.0, "o2_ml_min": 0.0, "i": 0.0, "sludge_pct": 0.0,
                          "pass_frac": 0.0, "t_el": self.design.environment.ambient_c if self.design else 25.0})
        self.bubbles.clear()
        self.o2.clear()
        self.electrons.clear()
        self.running = False
        self.timer.stop()
        self.update()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        if self.running:
            self.timer.start()
        super().showEvent(e)

    # ------------------------------------------------------------ анімація
    def _animate(self) -> None:
        self.phase += 0.04
        geo = getattr(self, "_geo", None)
        if not geo:
            return
        h2 = self.live.get("h2_ml_min", 0.0)
        target = int(min(70, 6 + h2 * 4)) if h2 > 0 else 0
        gaps = geo["gaps"]
        if gaps and len(self.bubbles) < target and self.rng.random() < 0.8:
            g = self.rng.choice(gaps)
            side = g["anode_side"]
            x = g["x0"] + 3 if side == "left" else g["x1"] - 3
            x += self.rng.uniform(-2, 2) * (1 if side == "left" else -1)
            self.bubbles.append([x, self.rng.uniform(geo["y0"] + 30, geo["y1"] - 10), self.rng.uniform(0.6, 1.6),
                                 self.rng.uniform(1.6, 3.6), g, self.rng.uniform(0, 6.28)])
        alive = []
        for b in self.bubbles:
            b[1] -= b[2] * 2.2
            b[5] += 0.25
            g = b[4]
            dx = 0.5 * math.sin(b[5])
            b[0] = min(max(b[0] + dx + (0.15 if g["anode_side"] == "left" else -0.15), g["x0"] + 2), g["x1"] - 2)
            if b[1] > geo["liquid_top"] + 2:
                alive.append(b)
        self.bubbles = alive
        o2 = self.live.get("o2_ml_min", 0.0)
        o2_target = int(min(24, 4 + o2 * 2)) if o2 > 0 and geo["air"] else 0
        if geo["air"] and len(self.o2) < o2_target and self.rng.random() < 0.6:
            side = self.rng.choice(geo["air"])
            self.o2.append([side, 0.0, self.rng.uniform(geo["y0"] + 20, geo["y1"] - 20), self.rng.uniform(0.012, 0.025)])
        self.o2 = [o for o in self.o2 if o[1] < 1.0]
        for o in self.o2:
            o[1] += o[3]
        i = self.live.get("i", 0.0)
        if i > 1e-4 and len(self.electrons) < 14 and self.rng.random() < 0.5:
            self.electrons.append(0.0)
        speed = 0.006 + min(0.02, i * 0.006)
        self.electrons = [e + speed for e in self.electrons if e + speed < 1.0]
        self.update()

    # ------------------------------------------------------------ малювання
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(T.PANEL))
        if self.design is None:
            p.end()
            return
        d = self.design
        cat = M.CATHODES[d.cathode]
        air = cat.category == "air"
        faces = d.geometry.faces
        w, h = self.width(), self.height()
        label_w = (235 if w > 700 else 200) if (self.show_labels and w > 540) else 0
        left, right = 16, w - 16 - label_w
        top, bottom = 64, h - 46
        mg_frac = max(0.0, min(1.0, self.live.get("mg_frac", 1.0)))
        t_mm = d.geometry.plate_thickness_mm if d.geometry.mass_mode == "thickness" else 1.0
        g_mm = d.geometry.gap_mm
        air_w, cat_w = 36.0, 16.0
        gap_w = min(110.0, 16.0 + 9.0 * g_mm)
        an_w0 = min(120.0, 12.0 + 20.0 * t_mm)
        wall_w = 10.0
        if faces == 2:
            parts = ([("air", air_w)] if air else [("wall", wall_w)]) + [("cat", cat_w), ("gap", gap_w), ("anode", an_w0),
                                                                       ("gap", gap_w), ("cat", cat_w)] + ([("air", air_w)] if air else [("wall", wall_w)])
        else:
            parts = ([("air", air_w)] if air else [("wall", wall_w)]) + [("cat", cat_w), ("gap", gap_w), ("anode", an_w0),
                                                                       ("mask", 10.0), ("wall", wall_w)]
        if not air:
            # занурений катод: катод усередині ємності, електроліт по обидва боки
            parts = [("wall", wall_w), ("gap", gap_w * 0.6)] + [x for x in parts if x[0] not in ("air", "wall")] + [("gap", gap_w * 0.6), ("wall", wall_w)]
        total = sum(pw for _, pw in parts)
        avail = right - left
        scale = min(1.6, avail / total) if total > 0 else 1.0
        x = left + (avail - total * scale) / 2
        y0, y1 = top, bottom
        liquid_top = y0 + 14
        rects = []
        for kind, pw in parts:
            rects.append((kind, QRectF(x, y0, pw * scale, y1 - y0)))
            x += pw * scale
        t_el = self.live.get("t_el", 25.0)
        el_col = _mix("#174E7A", "#7A3E1A", (t_el - 25.0) / 50.0)
        el_col.setAlpha(170)
        sludge = max(0.0, min(0.9, self.live.get("sludge_pct", 0.0) / 100.0))
        pass_frac = max(0.0, min(1.0, self.live.get("pass_frac", 0.0)))
        geo = {"gaps": [], "y0": y0, "y1": y1, "liquid_top": liquid_top, "air": []}
        anode_rect = None
        cath_rects = []
        # фон ємності (електроліт) — під анодом і зазорами
        for idx, (kind, r) in enumerate(rects):
            if kind == "air":
                grad = QLinearGradient(r.topLeft(), r.topRight())
                c1, c2 = QColor("#0F2433"), QColor("#13202B")
                if idx == 0:
                    c1, c2 = c2, c1
                grad.setColorAt(0, c1)
                grad.setColorAt(1, c2)
                p.fillRect(r, grad)
                geo["air"].append({"rect": r, "to_right": idx == 0})
            elif kind == "wall":
                p.fillRect(r, QColor("#2A3440"))
            elif kind == "gap":
                p.fillRect(QRectF(r.left(), liquid_top, r.width(), y1 - liquid_top), el_col)
                if sludge > 0:
                    sh = (y1 - liquid_top) * sludge * 0.85
                    sr = QRectF(r.left(), y1 - sh, r.width(), sh)
                    p.fillRect(sr, QColor(205, 210, 215, 150))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(235, 238, 240, 170))
                    rr = random.Random(idx)
                    for _ in range(int(sr.width() * sr.height() / 60)):
                        p.drawEllipse(QPointF(rr.uniform(sr.left(), sr.right()), rr.uniform(sr.top(), sr.bottom())), 0.8, 0.8)
                # сторона, де анод
                neighbors = [rects[idx - 1][0] if idx > 0 else "", rects[idx + 1][0] if idx + 1 < len(rects) else ""]
                side = "left" if neighbors[0] == "anode" else ("right" if neighbors[1] == "anode" else "none")
                if side != "none":
                    geo["gaps"].append({"x0": r.left(), "x1": r.right(), "anode_side": side})
            elif kind == "mask":
                p.fillRect(r, QColor("#1D252E"))
                p.setPen(QPen(QColor("#3A4552"), 1))
                k = r.top()
                while k < r.bottom():
                    p.drawLine(QPointF(r.left(), k + 8), QPointF(r.right(), k))
                    k += 7
        # катоди
        for kind, r in rects:
            if kind != "cat":
                continue
            cath_rects.append(r)
            if air:
                ptfe = QRectF(r.left(), r.top(), r.width() * 0.35, r.height())
                catl = QRectF(r.left() + r.width() * 0.35, r.top(), r.width() * 0.45, r.height())
                mesh = QRectF(r.left() + r.width() * 0.8, r.top(), r.width() * 0.2, r.height())
                if r.center().x() > (rects[0][1].left() + rects[-1][1].right()) / 2:
                    ptfe, mesh = QRectF(r.right() - r.width() * 0.35, r.top(), r.width() * 0.35, r.height()), QRectF(r.left(), r.top(), r.width() * 0.2, r.height())
                    catl = QRectF(r.left() + r.width() * 0.2, r.top(), r.width() * 0.45, r.height())
                p.fillRect(ptfe, QColor("#C9CED4"))
                p.fillRect(catl, QColor("#2B2F33"))
                p.fillRect(mesh, QColor("#8E99A6"))
                p.setPen(QPen(QColor("#5D6873"), 1))
                yy = r.top()
                while yy < r.bottom():
                    p.drawLine(QPointF(mesh.left(), yy), QPointF(mesh.right(), yy + 4))
                    yy += 6
            else:
                grad = QLinearGradient(r.topLeft(), r.topRight())
                grad.setColorAt(0, QColor("#2E3338"))
                grad.setColorAt(0.5, QColor("#4A5056"))
                grad.setColorAt(1, QColor("#2E3338"))
                p.fillRect(QRectF(r.left(), y0 + 6, r.width(), r.height() - 6), grad)
        # сепаратор
        if d.separator != "none":
            p.setPen(QPen(QColor("#E0C27A"), 1.4, Qt.DashLine))
            for kind, r in rects:
                if kind == "gap":
                    for gg in geo["gaps"]:
                        if abs(gg["x0"] - r.left()) < 0.1:
                            xs = r.left() + r.width() * (0.35 if gg["anode_side"] == "left" else 0.65)
                            p.drawLine(QPointF(xs, liquid_top + 4), QPointF(xs, y1 - 2))
        # анод
        for kind, r in rects:
            if kind != "anode":
                continue
            cx = r.center().x()
            ar = QRectF(cx - r.width() * mg_frac / 2, y0 + 8, max(2.0, r.width() * mg_frac), y1 - y0 - 8)
            if faces == 1:
                ar = QRectF(r.right() - max(2.0, r.width() * mg_frac), y0 + 8, max(2.0, r.width() * mg_frac), y1 - y0 - 8)
                p.fillRect(QRectF(r.left(), liquid_top, r.width() - ar.width(), y1 - liquid_top), el_col)
            else:
                p.fillRect(QRectF(r.left(), liquid_top, (r.width() - ar.width()) / 2, y1 - liquid_top), el_col)
                p.fillRect(QRectF(ar.right(), liquid_top, (r.width() - ar.width()) / 2, y1 - liquid_top), el_col)
            grad = QLinearGradient(ar.topLeft(), ar.topRight())
            grad.setColorAt(0, QColor("#8C96A0"))
            grad.setColorAt(0.45, QColor("#E4E9EE"))
            grad.setColorAt(1, QColor("#9AA4AE"))
            p.fillRect(ar, grad)
            if pass_frac > 0.01:
                fw = 1.0 + 3.0 * pass_frac
                film = QColor(236, 240, 244, int(90 + 120 * pass_frac))
                p.fillRect(QRectF(ar.left() - fw, liquid_top, fw, y1 - liquid_top), film)
                if faces == 2:
                    p.fillRect(QRectF(ar.right(), liquid_top, fw, y1 - liquid_top), film)
            anode_rect = ar
        # рамка ємності
        p.setPen(QPen(QColor(T.BORDER_2), 1.2))
        p.setBrush(Qt.NoBrush)
        inner_l = rects[1][1].left() if air else rects[0][1].left()
        inner_r = rects[-2][1].right() if air else rects[-1][1].right()
        if faces == 1 and air:
            inner_r = rects[-1][1].right()
        p.drawLine(QPointF(inner_l, y1), QPointF(inner_r, y1))
        # рівень рідини
        p.setPen(QPen(QColor(120, 180, 230, 120), 1))
        for gg in geo["gaps"]:
            p.drawLine(QPointF(gg["x0"], liquid_top), QPointF(gg["x1"], liquid_top))
        # бульбашки H2
        p.setPen(QPen(QColor(220, 240, 255, 200), 1))
        p.setBrush(QColor(200, 230, 255, 60))
        for b in self.bubbles:
            p.drawEllipse(QPointF(b[0], b[1]), b[3], b[3])
        # O2
        if air:
            p.setPen(QPen(QColor(T.SERIES[2]), 1.6))
            f = QFont()
            f.setPointSizeF(6.5)
            p.setFont(f)
            for side_i, prog, yy, _ in self.o2:
                a = side_i["rect"]
                if side_i["to_right"]:
                    xx = a.left() + 4 + prog * (a.width() - 10)
                    p.drawLine(QPointF(xx, yy), QPointF(xx + 5, yy))
                    p.drawLine(QPointF(xx + 5, yy), QPointF(xx + 2, yy - 2.5))
                    p.drawLine(QPointF(xx + 5, yy), QPointF(xx + 2, yy + 2.5))
                else:
                    xx = a.right() - 4 - prog * (a.width() - 10)
                    p.drawLine(QPointF(xx, yy), QPointF(xx - 5, yy))
                    p.drawLine(QPointF(xx - 5, yy), QPointF(xx - 2, yy - 2.5))
                    p.drawLine(QPointF(xx - 5, yy), QPointF(xx - 2, yy + 2.5))
            for a in geo["air"]:
                p.setPen(QColor(T.SERIES[2]))
                p.drawText(QRectF(a["rect"].left(), y1 - 18, a["rect"].width(), 14), Qt.AlignCenter, "O₂")
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.SERIES[2]))
            rr = random.Random(5)
            for gg in geo["gaps"]:
                for _ in range(10):
                    p.drawEllipse(QPointF(rr.uniform(gg["x0"] + 2, gg["x1"] - 2), rr.uniform(liquid_top + 4, y1 - 6)), 1.0, 1.0)
        # контакти й зовнішнє коло
        wire_y = 26
        neg_x = anode_rect.center().x() if anode_rect else left + 40
        p.setPen(QPen(QColor("#6B7785"), 2))
        if anode_rect:
            tab = QRectF(neg_x - 4, wire_y + 6, 8, y0 + 8 - wire_y - 6)
            p.fillRect(tab, QColor("#B9C1C9"))
        cath_xs = [r.center().x() for r in cath_rects]
        for cxp in cath_xs:
            p.fillRect(QRectF(cxp - 3, wire_y + 14, 6, y0 - wire_y - 14), QColor("#9AA4AE"))
        pos_x = max(cath_xs) if cath_xs else right - 40
        bus_l = min(cath_xs) if cath_xs else pos_x
        p.setPen(QPen(QColor("#9AA4AE"), 2))
        if len(cath_xs) > 1:
            p.drawLine(QPointF(bus_l, wire_y + 14), QPointF(pos_x, wire_y + 14))
        # провід через навантаження
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#7E8A97"), 2))
        load_c = QPointF((neg_x + pos_x) / 2, wire_y - 6)
        path = QPainterPath(QPointF(neg_x, wire_y + 6))
        path.lineTo(neg_x, wire_y - 6)
        path.lineTo(load_c.x() - 22, wire_y - 6)
        path.moveTo(load_c.x() + 22, wire_y - 6)
        path.lineTo(pos_x + 0.01, wire_y - 6)
        path.lineTo(pos_x, wire_y + 14)
        p.drawPath(path)
        lr = QRectF(load_c.x() - 22, wire_y - 15, 44, 18)
        p.setBrush(QColor(T.PANEL_2))
        p.setPen(QPen(QColor(T.BORDER_2), 1))
        p.drawRoundedRect(lr, 4, 4)
        f = QFont()
        f.setPointSizeF(7.0)
        p.setFont(f)
        p.setPen(QColor(T.TEXT_2))
        p.drawText(lr, Qt.AlignCenter, "навант.")
        f.setPointSizeF(9.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(T.SERIES[0]))
        p.drawText(QRectF(neg_x - 22, wire_y - 4, 16, 14), Qt.AlignCenter, "−")
        p.setPen(QColor(T.SERIES[7]))
        p.drawText(QRectF(pos_x + 4, wire_y - 4, 16, 14), Qt.AlignCenter, "+")
        # електрони: від «−» через навантаження до «+»
        if self.electrons:
            pts = [QPointF(neg_x, wire_y + 6), QPointF(neg_x, wire_y - 6), QPointF(pos_x, wire_y - 6), QPointF(pos_x, wire_y + 14)]
            seg = [math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in zip(pts, pts[1:])]
            tot = sum(seg)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.ACCENT))
            for e in self.electrons:
                s = e * tot
                for (a, b), L in zip(zip(pts, pts[1:]), seg):
                    if s <= L:
                        q = s / L if L > 0 else 0
                        p.drawEllipse(QPointF(a.x() + (b.x() - a.x()) * q, a.y() + (b.y() - a.y()) * q), 2.4, 2.4)
                        break
                    s -= L
        # розміри
        f = QFont()
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        if anode_rect is not None:
            p.drawText(QRectF(anode_rect.center().x() - 50, y1 + 4, 100, 14), Qt.AlignCenter,
                       f"t = {fmt(t_mm * mg_frac, 2)} мм")
        if geo["gaps"]:
            gg = geo["gaps"][0]
            p.drawText(QRectF(gg["x0"] - 20, y1 + 18, gg["x1"] - gg["x0"] + 40, 14), Qt.AlignCenter, f"зазор {fmt(g_mm, 1)} мм")
        p.drawText(QRectF(left, h - 16, w - left - 16, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   "Схематичний розріз комірки, не в масштабі")
        # підписи з виносками
        if label_w:
            self._labels(p, rects, anode_rect, cath_rects, geo, air, d, cat, right + 18, y0, y1, liquid_top, sludge, pass_frac)
        self._geo = geo
        p.end()

    def _labels(self, p, rects, anode_rect, cath_rects, geo, air, d, cat, lx, y0, y1, liquid_top, sludge, pass_frac):
        an = M.ANODES[d.anode]
        el = M.ELECTROLYTES[d.electrolyte]
        items = []
        if air and geo["air"]:
            a = geo["air"][-1]["rect"]
            items.append(("Повітря: O₂ до катода", QPointF(a.center().x(), y0 + 20), T.SERIES[2]))
        if cath_rects:
            r = cath_rects[-1]
            items.append((cat.name.split("(")[0].strip().replace("Повітряний катод", "Пов. катод"), QPointF(r.center().x(), y0 + 50), T.TEXT_2))
        if anode_rect is not None:
            items.append((f"Анод: {an.name.split('(')[0].strip()}", QPointF(anode_rect.center().x(), (y0 + y1) / 2), "#D7DEE5"))
            if pass_frac > 0.01:
                items.append(("Плівка Mg(OH)₂", QPointF(anode_rect.left() - 1, (y0 + y1) / 2 + 30), T.TEXT_2))
        if geo["gaps"]:
            gg = geo["gaps"][-1]
            items.append((f"Електроліт: {el.name.split('(')[0].strip()}", QPointF((gg["x0"] + gg["x1"]) / 2, liquid_top + 40), "#6FB3E8"))
            if d.separator != "none":
                items.append((f"Сепаратор: {M.SEPARATORS[d.separator].name}", QPointF((gg["x0"] + gg["x1"]) / 2, liquid_top + 80), "#E0C27A"))
            items.append(("Бульбашки H₂ (самокорозія)", QPointF((gg["x0"] + gg["x1"]) / 2, liquid_top + 120), T.TEXT_2))
            if sludge > 0.005:
                items.append(("Шлам Mg(OH)₂", QPointF((gg["x0"] + gg["x1"]) / 2, y1 - 6), T.TEXT_2))
        items.append(("Контакти: «−» анод, «+» катод", QPointF((rects[0][1].left() + rects[-1][1].right()) / 2, 20), T.TEXT_2))
        f = QFont()
        f.setPointSizeF(8.0)
        p.setFont(f)
        items.sort(key=lambda it: it[1].y())
        n = len(items)
        span = (y1 - y0 + 40)
        for k, (text, anchor, color) in enumerate(items):
            ty = y0 - 30 + span * (k + 0.5) / n
            p.setPen(QPen(QColor(T.BORDER_2), 1))
            p.drawLine(anchor, QPointF(lx - 6, ty))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(anchor, 2.2, 2.2)
            p.setPen(QColor(color))
            p.drawText(QRectF(lx, ty - 9, self.width() - lx - 6, 18), Qt.AlignLeft | Qt.AlignVCenter, text)


class SystemDiagram(QWidget):
    """Батарея комірок → DC/DC → шина (суперконденсатор) → USB-C → навантаження."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.design: Design | None = None
        self.load_label = "Телефон"
        self.v = {}
        self.offset = 0.0
        self.running = False
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

    def set_design(self, design: Design, load_label: str) -> None:
        self.design = design
        self.load_label = load_label
        self.update()

    def set_live(self, values: dict, running: bool) -> None:
        self.v = values
        self.running = running
        if running and self.isVisible() and not self.timer.isActive():
            self.timer.start()
        if not running:
            self.timer.stop()
        self.update()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self.offset = (self.offset + 1.2) % 16
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(T.PANEL))
        if self.design is None:
            p.end()
            return
        d = self.design
        v = self.v
        w = self.width()
        s, par = stack_counts(d.stack)
        cap_on = d.supercap.enabled and d.converter.enabled
        nodes = [
            ("Батарея комірок", f"{s} посл. × {par} пар.", f"{fmt(v.get('v_term', 0), 2)} В · {fmt(v.get('i_ext', 0), 2)} А"),
            ("DC/DC", "MPPT" if d.converter.control == "mppt" else "простий boost",
             f"ККД {fmt(v.get('conv_eff', float('nan')), 0)} %" if d.converter.enabled else "вимкнено"),
            ("USB-C", f"{fmt(d.converter.v_out, 1)} В", "увімкнено" if v.get("usb_on", 0) > 0.5 else "вимкнено"),
            (self.load_label, v.get("load_line", ""), v.get("load_line2", "")),
        ]
        n = len(nodes)
        bw = min(170.0, (w - 40 - (n - 1) * 46) / n)
        bh = 64.0
        gap = (w - 24 - n * bw) / (n - 1) if n > 1 else 0
        ytop = 18.0
        rects = []
        for k in range(n):
            rects.append(QRectF(12 + k * (bw + gap), ytop, bw, bh))
        flows = [v.get("p_term", 0.0), v.get("p_usb_from_bus", v.get("p_usb", 0.0)), v.get("p_usb", 0.0)]
        for k in range(n - 1):
            a, b = rects[k], rects[k + 1]
            yy = a.center().y()
            pw = flows[k] if k < len(flows) else 0.0
            active = pw > 1e-4
            pen = QPen(QColor(T.ACCENT if active else T.BORDER_2), 2, Qt.DashLine if active else Qt.SolidLine)
            if active:
                pen.setDashOffset(-self.offset)
            p.setPen(pen)
            p.drawLine(QPointF(a.right() + 2, yy), QPointF(b.left() - 6, yy))
            p.setBrush(QColor(T.ACCENT if active else T.BORDER_2))
            p.setPen(Qt.NoPen)
            tri = QPainterPath(QPointF(b.left() - 2, yy))
            tri.lineTo(b.left() - 9, yy - 4.5)
            tri.lineTo(b.left() - 9, yy + 4.5)
            tri.closeSubpath()
            p.drawPath(tri)
            f = QFont()
            f.setPointSizeF(8.0)
            p.setFont(f)
            p.setPen(QColor(T.TEXT_2))
            p.drawText(QRectF(a.right(), yy - 20, b.left() - a.right(), 14), Qt.AlignCenter, f"{fmt(pw, 2)} Вт")
        for k, (title, l1, l2) in enumerate(nodes):
            r = rects[k]
            p.setBrush(QColor(T.PANEL_2))
            p.setPen(QPen(QColor(T.BORDER_2), 1))
            p.drawRoundedRect(r, 9, 9)
            f = QFont()
            f.setPointSizeF(8.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(T.TEXT))
            p.drawText(QRectF(r.left() + 10, r.top() + 6, r.width() - 20, 16), Qt.AlignLeft, title)
            f.setBold(False)
            f.setPointSizeF(8.0)
            p.setFont(f)
            p.setPen(QColor(T.TEXT_2))
            p.drawText(QRectF(r.left() + 10, r.top() + 24, r.width() - 20, 16), Qt.AlignLeft, l1)
            p.drawText(QRectF(r.left() + 10, r.top() + 41, r.width() - 20, 16), Qt.AlignLeft, l2)
        # суперконденсатор під шиною між DC/DC і USB-C
        a, b = rects[1], rects[2]
        bus_x = (a.right() + b.left()) / 2
        cr = QRectF(bus_x - 80, ytop + bh + 30, 160, 52)
        p.setPen(QPen(QColor(T.BORDER_2), 1, Qt.SolidLine if cap_on else Qt.DotLine))
        p.setBrush(QColor(T.PANEL_2) if cap_on else Qt.NoBrush)
        p.drawRoundedRect(cr, 9, 9)
        cap_p = v.get("cap_p", 0.0)
        pen = QPen(QColor(T.SERIES[3] if cap_on and abs(cap_p) > 1e-4 else T.BORDER_2), 2,
                   Qt.DashLine if cap_on and abs(cap_p) > 1e-4 else Qt.SolidLine)
        if cap_on and abs(cap_p) > 1e-4:
            pen.setDashOffset(-self.offset if cap_p > 0 else self.offset)
        p.setPen(pen)
        p.drawLine(QPointF(bus_x, a.center().y()), QPointF(bus_x, cr.top()))
        f = QFont()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(T.TEXT if cap_on else T.MUTED))
        p.drawText(QRectF(cr.left() + 10, cr.top() + 6, cr.width() - 20, 16), Qt.AlignLeft, "Суперконденсатор")
        f.setBold(False)
        f.setPointSizeF(8.0)
        p.setFont(f)
        p.setPen(QColor(T.TEXT_2 if cap_on else T.MUTED))
        if cap_on:
            txt = f"{fmt(v.get('cap_j', 0.0), 0)} Дж · {fmt(v.get('cap_v', 0.0), 2)} В"
            txt2 = ("заряд " if cap_p > 1e-4 else "розряд " if cap_p < -1e-4 else "") + (f"{fmt(abs(cap_p), 2)} Вт" if abs(cap_p) > 1e-4 else "очікування")
        else:
            txt, txt2 = "не встановлено", "SmartBoost вимкнено"
        p.drawText(QRectF(cr.left() + 10, cr.top() + 22, cr.width() - 20, 14), Qt.AlignLeft, txt)
        p.drawText(QRectF(cr.left() + 10, cr.top() + 36, cr.width() - 20, 14), Qt.AlignLeft, txt2)
        p.end()
