"""Темна тема інтерфейсу та кольори графіків."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0A0E13"
PANEL = "#111820"
PANEL_2 = "#161F29"
PANEL_3 = "#1C2733"
BORDER = "#1F2A36"
BORDER_2 = "#2A3746"
TEXT = "#E8EDF2"
TEXT_2 = "#A9B4C0"
MUTED = "#6B7785"
ACCENT = "#38BDF8"
ACCENT_DIM = "#0E3A52"

# Категоріальна палітра графіків (перевірена на поверхні #111820: CVD та контраст)
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

# Статуси (лише для станів, завжди з текстом/значком)
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"

LEVEL_COLORS = {"ok": GOOD, "info": TEXT_2, "warning": WARNING, "critical": CRITICAL}
LEVEL_ICONS = {"ok": "✔", "info": "ℹ", "warning": "▲", "critical": "✖"}

STATUS_COLORS = {
    "reference": "#3987e5",
    "literature": "#9085e9",
    "assumption": "#c98500",
    "user": "#A9B4C0",
    "calibrated": "#199e70",
}

FONT_FAMILIES = ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Arial"]


QSS = f"""
* {{ outline: none; }}
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QToolTip {{ background: {PANEL_3}; color: {TEXT}; border: 1px solid {BORDER_2}; padding: 6px; border-radius: 6px; }}
QFrame#Card, QWidget#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#TopBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QFrame#SideBar {{ background: #0D1218; border-right: 1px solid {BORDER}; }}
QFrame#RightPanel {{ background: #0D1218; border-left: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Secondary {{ color: {TEXT_2}; }}
QLabel#H1 {{ font-size: 17pt; font-weight: 600; }}
QLabel#H2 {{ font-size: 12.5pt; font-weight: 600; }}
QLabel#H3 {{ font-size: 10.5pt; font-weight: 600; color: {TEXT_2}; }}
QLabel#KpiValue {{ font-size: 15pt; font-weight: 600; }}
QLabel#KpiCaption {{ color: {MUTED}; font-size: 8.5pt; letter-spacing: 0.5px; }}
QLabel#Brand {{ font-size: 13pt; font-weight: 700; letter-spacing: 2px; color: {TEXT}; }}
QLabel#BrandSub {{ color: {MUTED}; font-size: 8pt; letter-spacing: 1px; }}
QLabel#Badge {{ border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }}

QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 6px 12px; color: {TEXT}; }}
QPushButton:hover {{ background: {PANEL_3}; border-color: #3A4A5C; }}
QPushButton:pressed {{ background: #233140; }}
QPushButton:disabled {{ color: {MUTED}; background: #0F151C; border-color: {BORDER}; }}
QPushButton:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; color: {TEXT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #04121C; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #5CCBFA; }}
QPushButton#Primary:disabled {{ background: #1B3A4A; color: #5B7A8A; border-color: #1B3A4A; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: {TEXT_2}; }}
QPushButton#Ghost:hover {{ background: {PANEL_2}; border-color: {BORDER_2}; color: {TEXT}; }}
QPushButton#Speed {{ padding: 5px 9px; min-width: 38px; }}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER_2}; border-radius: 7px; padding: 4px 8px;
    selection-background-color: {ACCENT_DIM}; selection-color: {TEXT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox::up-button, QSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {TEXT_2}; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER_2}; selection-background-color: {ACCENT_DIM}; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_2}; background: {PANEL_2}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER_2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_2}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4A5C; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_2}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListWidget#Nav {{ background: transparent; border: none; padding: 4px; }}
QListWidget#Nav::item {{ color: {TEXT_2}; padding: 9px 10px; margin: 2px 4px; border-radius: 8px; }}
QListWidget#Nav::item:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QListWidget#Nav::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}

QTableWidget, QTableView {{ background: {PANEL}; alternate-background-color: #131B24; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 8px; selection-background-color: {ACCENT_DIM}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL_2}; color: {TEXT_2}; border: none; border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER}; padding: 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {PANEL_2}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {TEXT_2}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid {BORDER_2}; border-radius: 6px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QToolButton {{ background: transparent; border: none; color: {TEXT_2}; padding: 6px 4px; font-weight: 600; text-align: left; }}
QToolButton:hover {{ color: {TEXT}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER_2}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QSplitter::handle {{ background: {BORDER}; }}
QMessageBox {{ background: {PANEL}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(10.0)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.Base, PANEL_2), (QPalette.AlternateBase, PANEL),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, PANEL_2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT_DIM), (QPalette.HighlightedText, TEXT),
                        (QPalette.ToolTipBase, PANEL_3), (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    pg.setConfigOptions(antialias=True, background=PANEL, foreground=TEXT_2)


def badge_style(color: str) -> str:
    c = QColor(color)
    return (f"background: rgba({c.red()},{c.green()},{c.blue()},40); color: {color}; "
            f"border: 1px solid rgba({c.red()},{c.green()},{c.blue()},110);")
