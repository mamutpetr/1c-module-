"""Лінійні іконки навігації, намальовані QPainter (без зовнішніх файлів)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .. import theme as T


def _pix(draw, color: str, size: int = 40) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size / 13.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size / 24.0
    p.scale(s, s)
    draw(p)
    p.end()
    return pm


def _bolt(p):
    path = QPainterPath(QPointF(13, 2))
    for x, y in ((5, 13), (11, 13), (10, 22), (19, 10), (13, 10), (13, 2)):
        path.lineTo(x, y)
    p.drawPath(path)


def _layers(p):
    for dy in (0, 5, 10):
        path = QPainterPath(QPointF(12, 3 + dy))
        path.lineTo(21, 7.5 + dy)
        path.lineTo(12, 12 + dy)
        path.lineTo(3, 7.5 + dy)
        path.closeSubpath()
        if dy == 0:
            p.drawPath(path)
        else:
            p.drawPolyline([QPointF(3, 7.5 + dy), QPointF(12, 12 + dy), QPointF(21, 7.5 + dy)])


def _phone(p):
    p.drawRoundedRect(QRectF(6.5, 2.5, 11, 19), 2.5, 2.5)
    p.drawLine(QPointF(10.5, 18.5), QPointF(13.5, 18.5))
    p.drawLine(QPointF(12, 7), QPointF(10.5, 11))
    p.drawLine(QPointF(10.5, 11), QPointF(13.5, 11))
    p.drawLine(QPointF(13.5, 11), QPointF(12, 15))


def _cap(p):
    p.drawLine(QPointF(2, 12), QPointF(9, 12))
    p.drawLine(QPointF(15, 12), QPointF(22, 12))
    p.drawLine(QPointF(9, 5), QPointF(9, 19))
    path = QPainterPath(QPointF(16, 5))
    path.quadTo(QPointF(13, 12), QPointF(16, 19))
    p.drawPath(path)


def _compare(p):
    p.drawRoundedRect(QRectF(3, 4, 7.5, 16), 1.5, 1.5)
    p.drawRoundedRect(QRectF(13.5, 4, 7.5, 16), 1.5, 1.5)
    p.drawLine(QPointF(5.5, 14), QPointF(8, 9))
    p.drawLine(QPointF(16, 11), QPointF(18.5, 15))


def _target(p):
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.drawEllipse(QPointF(12, 12), 5, 5)
    p.drawPoint(QPointF(12, 12))
    p.drawLine(QPointF(12, 1.5), QPointF(12, 4.5))
    p.drawLine(QPointF(12, 19.5), QPointF(12, 22.5))


def _flask(p):
    path = QPainterPath(QPointF(9, 3))
    path.lineTo(9, 9)
    path.lineTo(3.5, 19)
    path.quadTo(3, 21, 5, 21)
    path.lineTo(19, 21)
    path.quadTo(21, 21, 20.5, 19)
    path.lineTo(15, 9)
    path.lineTo(15, 3)
    p.drawPath(path)
    p.drawLine(QPointF(7.5, 3), QPointF(16.5, 3))
    p.drawLine(QPointF(6.5, 15), QPointF(17.5, 15))


def _coin(p):
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.drawLine(QPointF(12, 6), QPointF(12, 18))
    path = QPainterPath(QPointF(15, 9))
    path.quadTo(QPointF(12, 7.5), QPointF(9.5, 9))
    path.quadTo(QPointF(8.5, 11.5), QPointF(12, 12))
    path.quadTo(QPointF(15.5, 12.5), QPointF(14.5, 15))
    path.quadTo(QPointF(12, 16.5), QPointF(9, 15))
    p.drawPath(path)


def _check(p):
    p.drawRoundedRect(QRectF(4, 3, 16, 18), 2, 2)
    p.drawLine(QPointF(8, 8), QPointF(16, 8))
    p.drawLine(QPointF(8, 12), QPointF(16, 12))
    p.drawPolyline([QPointF(8, 16), QPointF(10, 18), QPointF(15, 14.5)])


DRAWERS = {"bolt": _bolt, "layers": _layers, "phone": _phone, "cap": _cap, "compare": _compare,
           "target": _target, "flask": _flask, "coin": _coin, "check": _check}


def nav_icon(name: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pix(DRAWERS[name], T.TEXT_2), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pix(DRAWERS[name], T.ACCENT), QIcon.Selected, QIcon.Off)
    icon.addPixmap(_pix(DRAWERS[name], T.ACCENT), QIcon.Active, QIcon.Off)
    return icon


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(T.ACCENT_DIM))
    p.setPen(QPen(QColor(T.ACCENT), 3))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    p.end()
    base = QIcon(pm)
    over = _pix(_bolt, T.ACCENT, 64)
    p = QPainter(pm)
    p.drawPixmap(0, 0, over)
    p.end()
    return QIcon(pm) if not pm.isNull() else base
